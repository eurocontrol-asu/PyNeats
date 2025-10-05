from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final, Literal, Mapping, Protocol, runtime_checkable, Any

import numpy as np
from numpy.typing import NDArray
import pandas as pd
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.humidity_scaling import HumidityScaling
from pycontrails.models.humidity_scaling import ConstantHumidityScaling

from pyneats.core.neats_defaults import DEFAULT_HUMIDITY_SCALING
from pyneats.core.steps import BaseStep, Step, StepError, BaseParams
from pyneats.core.views import ValidationError
from pyneats.steps.trajectory import Flight4D

__all__ = [
    "DEFAULT_REQUIRED_WEATHER_COLS",
    "FlightWithWeather",
    "WeatherStepError",
    "HumidityScalingModel",
    "PcHumidityScalingAdapter",
    "WeatherProviderParams",
    "WeatherProviderProtocol",
    "WeatherProvider",
]

logger = logging.getLogger(__name__)

# ---------------------------- Schema ---------------------------------

DEFAULT_REQUIRED_WEATHER_COLS: Final[tuple[str, ...]] = (
    "u_wind",
    "v_wind",
    "air_temperature",
    "specific_humidity",
)
DEFAULT_OPTIONAL_WEATHER_COLS: Final[tuple[str, ...]] = ("air_pressure",)


class FlightWithWeather(Flight4D):
    """Typed, zero-copy view asserting required weather columns exist."""

    REQUIRED = DEFAULT_REQUIRED_WEATHER_COLS
    OPTIONAL = DEFAULT_OPTIONAL_WEATHER_COLS


# ---------------------------- Errors ---------------------------------


class WeatherStepError(StepError):
    """Normalized domain error for the weather step."""


# ------------------------- Contracts (Option A) ----------------------


@runtime_checkable
class HumidityScalingModel(Protocol):
    """Strict contract: humidity scaling *must* return a Flight."""

    def eval(self, source: Flight) -> Flight: ...


class PcHumidityScalingAdapter(HumidityScalingModel):
    """
    Adapter to wrap pycontrails' ConstantHumidityScaling so that `.eval()` returns a Flight.
    If pycontrails returns None (in-place) we pass back the input Flight.
    """

    def __init__(self, humidity_scaling: HumidityScaling) -> None:
        self.humidity_scaling = humidity_scaling

    def eval(self, source: Flight) -> Flight:
        result = self.humidity_scaling.eval(source=source)

        if result is None:
            # in-place mutation contract → return the original Flight
            return source

        if isinstance(result, Flight):
            return result

        # Accept a FlightView-like with `.dataframe`
        if hasattr(result, "dataframe"):
            return Flight(
                data=result.dataframe,
                attrs=getattr(result, "attrs", getattr(source, "attrs", None)),
            )

        # Accept a raw pandas DataFrame
        if isinstance(result, pd.DataFrame):
            return Flight(data=result, attrs=getattr(source, "attrs", None))

        raise TypeError(f"Unsupported humidity_scaling output: {type(result)!r}")


# ---------------------------- Params ---------------------------------

InterpolationMethod = Literal["linear", "nearest"]


@dataclass(frozen=True)
class WeatherProviderParams(BaseParams):
    # Downselect buffers (lon, lat in deg; time as np.timedelta64; level in model coords)
    lon_buf: tuple[float, float] = (0.0, 0.0)
    lat_buf: tuple[float, float] = (0.0, 0.0)
    time_buf: tuple[np.timedelta64, np.timedelta64] = (
        np.timedelta64(0, "h"),
        np.timedelta64(0, "h"),
    )
    level_buf: tuple[float, float] = (0.0, 0.0)

    method: InterpolationMethod = "linear"
    use_indices: bool = True

    # Strict contract: either None, or a model that returns a Flight
    humidity_scaling: HumidityScalingModel | None = field(
        default_factory=lambda: PcHumidityScalingAdapter(
            humidity_scaling=DEFAULT_HUMIDITY_SCALING
        )
    )

    # Mapping: met variable → output column name on Flight
    var_map: Mapping[str, str] = field(
        default_factory=lambda: {
            "eastward_wind": "u_wind",
            "northward_wind": "v_wind",
            "air_temperature": "air_temperature",
            "specific_humidity": "specific_humidity",
            # Optionally include: "air_pressure": "air_pressure",
        }
    )


# --------------------------- Protocol --------------------------------


@runtime_checkable
class WeatherProviderProtocol(Step[Flight4D, FlightWithWeather], Protocol):
    def met(self) -> MetDataset: ...
    def rad(self) -> MetDataset: ...
    def ds_met(self) -> MetDataset | None: ...
    def ds_rad(self) -> MetDataset | None: ...
    def downselect(self, flight: Flight4D, met: MetDataset) -> MetDataset: ...


# ------------------------- Implementation ---------------------------


class WeatherProvider(
    BaseStep[
        Flight4D,
        FlightWithWeather,
        WeatherProviderParams,
    ]
):
    """
    Flight4D → FlightWithWeather

    - Downselect MET/RAD to the flight envelope
    - Intersect configured variables (var_map)
    - Optionally apply humidity scaling (strict Flight-returning contract)
    - Validate output via FlightWithWeather.from_flight (zero-copy)
    """

    default_params = WeatherProviderParams

    def __init__(
        self,
        met: MetDataset,
        rad: MetDataset,
        wind: MetDataset,
        *,
        params: WeatherProviderParams | None = None,
        **params_kwargs: Any,
    ) -> None:
        super().__init__(params, **params_kwargs)

        self._met = met
        self._rad = rad
        self.wind = wind
        self._ds_met: MetDataset | None = None
        self._ds_rad: MetDataset | None = None

    # --- accessors ----------------------------------------------------

    def met(self) -> MetDataset:
        return self._met

    def rad(self) -> MetDataset:
        return self._rad

    def ds_met(self) -> MetDataset | None:
        return self._ds_met

    def ds_rad(self) -> MetDataset | None:
        return self._ds_rad

    # --- helpers ------------------------------------------------------

    def downselect(self, flight: Flight4D, met: MetDataset) -> MetDataset:
        """
        Downselects the meteorological dataset to the relevant subset for a given flight.

        This method calls the `downselect_met` method from PyContrails of the provided `Flight4D` object,
        passing in the meteorological dataset and buffer parameters

        Args:
            flight (Flight4D): The flight object containing trajectory and downselection logic.
            met (MetDataset): The meteorological dataset to be filtered.

        Returns:
            MetDataset: The subset of the meteorological dataset relevant to the flight.

        """
        try:
            return flight.downselect_met(
                met,
                longitude_buffer=self.params.lon_buf,
                latitude_buffer=self.params.lat_buf,
                time_buffer=self.params.time_buf,
                level_buffer=self.params.level_buf,
            )
        except Exception as e:
            raise WeatherStepError(
                type(self).__name__, f"downselect failed: {e}"
            ) from e

    # --- main step ----------------------------------------------------

    def run(self, flight: Flight4D) -> FlightWithWeather:
        # Ensure upstream contract (cheap; explicit)
        try:
            flight = Flight4D.from_flight(flight)
        except ValidationError as e:
            raise WeatherStepError(
                type(self).__name__, f"input is not Flight4D: {e}"
            ) from e

        # Downselect datasets
        self._ds_met = self.downselect(flight, self._met)
        self._ds_rad = self.downselect(flight, self._rad)

        # Intersect MET variables and build a new Flight (no in-place mutation)
        try:
            new_cols: dict[str, NDArray[np.floating[Any]]] = {}

            for met_var, out_col in self.params.var_map.items():
                if met_var not in self._ds_met:
                    if out_col in DEFAULT_REQUIRED_WEATHER_COLS:
                        raise KeyError(
                            f"required met var '{met_var}' missing in downselected MET"
                        )
                    continue

                vals = flight.intersect_met(
                    self._ds_met[met_var],
                    method=self.params.method,
                    use_indices=self.params.use_indices,
                )

                # Optional: ensure consistent dtype
                vals = (
                    np.nan_to_num(vals, nan=0.0)
                    if met_var in ("eastward_wind", "northward_wind")
                    else vals
                )
                # If you want strict float64 everywhere:
                # vals = np.asarray(vals, dtype=np.float64)

                new_cols[out_col] = vals

            # IMPORTANT: use the DataFrame view, not .data
            df = flight.dataframe.reset_index(drop=True)

            # Assign columns directly (safer than concat with a new DF)
            for k, v in new_cols.items():
                if v.shape[0] != len(df):
                    raise ValueError(
                        f"Length mismatch for column {k}: {v.shape[0]} vs {len(df)}"
                    )
                df[k] = v

            base = Flight(data=df, attrs=getattr(flight, "attrs", None))

        except Exception as e:
            raise WeatherStepError(type(self).__name__, f"intersect failed: {e}") from e

        # Optional humidity scaling with strict Flight-returning contract
        if self.params.humidity_scaling is not None:
            try:
                base = self.params.humidity_scaling.eval(base)
            except Exception as e:
                raise WeatherStepError(
                    type(self).__name__, f"humidity scaling failed: {e}"
                ) from e

        # Final validation (single source of truth)
        try:
            return FlightWithWeather.from_flight(base)
        except ValidationError as e:
            raise WeatherStepError(
                type(self).__name__, f"validation failed: {e}"
            ) from e
