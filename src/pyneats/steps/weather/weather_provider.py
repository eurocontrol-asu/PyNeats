"""
Weather Provider Module

Defines WeatherProvider and related classes for integrating meteorological data into flight trajectories.
Allows downselecting meteorological datasets to the flight envelope, interpolating required weather variables, and optionally applying humidity scaling.

Key Components
--------------
- WeatherProviderParams: Configuration for WeatherProvider (lon/lat/time buffers, etc.)
- WeatherProvider: Main class for processing flight data and integrating weather information
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Final
from typing import Protocol
from typing import runtime_checkable

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pycontrails import Fleet
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.humidity_scaling import HumidityScaling

from pyneats.core.fleet_utils import fleet_to_flights
from pyneats.core.fleet_utils import flights_to_fleet
from pyneats.core.neats_default_parameters import DEFAULT_HUMIDITY_SCALING
from pyneats.core.neats_default_parameters import DEFAULT_LAT_BUF
from pyneats.core.neats_default_parameters import DEFAULT_LEVEL_BUF
from pyneats.core.neats_default_parameters import DEFAULT_LON_BUF
from pyneats.core.neats_default_parameters import DEFAULT_TIME_BUF
from pyneats.core.neats_default_parameters import DEFAULT_WEATHER_INTEPOLATION_METHOD
from pyneats.core.neats_default_parameters import DEFAULT_WEATHER_USE_INDICES
from pyneats.core.neats_default_parameters import InterpolationMethod
from pyneats.core.steps import BaseParams
from pyneats.core.steps import BaseStep
from pyneats.core.steps import Step
from pyneats.core.steps import StepError
from pyneats.core.views import ValidationError
from pyneats.steps.parsing import Flight4D


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
DEFAULT_OPTIONAL_WEATHER_COLS: Final[tuple[str, ...]] = (
    "geopotential",
    "potential_vorticity",
)

WIND_VARS: Final[tuple[str, ...]] = ("eastward_wind", "northward_wind")


class FlightWithWeather(Flight4D):
    """
    Typed, zero-copy view asserting required weather columns exist.

    Attributes
    ----------
    REQUIRED : tuple[str, ...]
        Required weather columns.
    OPTIONAL : tuple[str, ...]
        Optional weather columns.
    """

    REQUIRED = DEFAULT_REQUIRED_WEATHER_COLS
    OPTIONAL = DEFAULT_OPTIONAL_WEATHER_COLS


# ---------------------------- Errors ---------------------------------


class WeatherStepError(StepError):
    """
    Normalized domain error for the weather step.
    """


# ------------------------- Contracts (Option A) ----------------------


@runtime_checkable
class HumidityScalingModel(Protocol):
    """
    Strict contract: humidity scaling *must* return a Flight.

    Methods
    -------
    eval(source: Flight) -> Flight
        Evaluate humidity scaling on a Flight.
    """

    def eval(self, source: Flight) -> Flight: ...


class PcHumidityScalingAdapter(HumidityScalingModel):
    """
    Adapter to wrap pycontrails' HumidityScaling so that `.eval()` returns a Flight.

    If pycontrails returns None (in-place), the input Flight is returned.
    """

    def __init__(self, humidity_scaling: HumidityScaling) -> None:
        self.humidity_scaling = humidity_scaling

    def eval(self, source: Flight) -> Flight:
        result = self.humidity_scaling.eval(source=source)

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


@dataclass(frozen=True)
class WeatherProviderParams(BaseParams):
    """Parameters for WeatherProvider step."""

    # Downselect buffers (lon, lat in deg; time as np.timedelta64; level in model coords)
    lon_buf: tuple[float, float] = DEFAULT_LON_BUF
    lat_buf: tuple[float, float] = DEFAULT_LAT_BUF
    time_buf: tuple[np.timedelta64, np.timedelta64] = DEFAULT_TIME_BUF
    level_buf: tuple[float, float] = DEFAULT_LEVEL_BUF

    method: InterpolationMethod = DEFAULT_WEATHER_INTEPOLATION_METHOD
    use_indices: bool = DEFAULT_WEATHER_USE_INDICES

    # Strict contract: either None, or a model that returns a Flight
    humidity_scaling: HumidityScalingModel | None = field(
        default_factory=lambda: PcHumidityScalingAdapter(
            humidity_scaling=DEFAULT_HUMIDITY_SCALING
        )
        if DEFAULT_HUMIDITY_SCALING is not None
        else None
    )

    # Mapping: met variable → output column name on Flight
    var_map: Mapping[str, str] = field(
        default_factory=lambda: {
            "eastward_wind": "u_wind",
            "northward_wind": "v_wind",
            "air_temperature": "air_temperature",
            "specific_humidity": "specific_humidity",
            "geopotential": "geopotential",
            "potential_vorticity": "potential_vorticity",
        }
    )


# --------------------------- Protocol --------------------------------


@runtime_checkable
class WeatherProviderProtocol(Step[Flight4D, FlightWithWeather], Protocol):
    """Structural contract for WeatherProvider implementations."""

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
    output_schema = FlightWithWeather

    def __init__(
        self,
        met: MetDataset,
        rad: MetDataset,
        wind: MetDataset | None = None,
        *,
        params: WeatherProviderParams | None = None,
        **params_kwargs: Any,
    ) -> None:
        super().__init__(params, **params_kwargs)

        self._met = met
        self._rad = rad
        self._wind = wind
        self._ds_met: MetDataset | None = None
        self._ds_rad: MetDataset | None = None
        self._ds_wind: MetDataset | None = None

    # --- accessors ----------------------------------------------------

    def met(self) -> MetDataset:
        """Return the full MET (pressure-level) dataset loaded on init."""
        return self._met

    def rad(self) -> MetDataset:
        """Return the full radiation dataset loaded on init."""
        return self._rad

    def wind(self) -> MetDataset | None:
        """Return the dedicated wind dataset if provided, else ``None``.

        When ``None``, wind variables fall back to the MET dataset during
        ``run()``.
        """
        return self._wind

    def ds_met(self) -> MetDataset | None:
        return self._ds_met

    def ds_rad(self) -> MetDataset | None:
        return self._ds_rad

    def ds_wind(self) -> MetDataset | None:
        return self._ds_wind

    # --- helpers ------------------------------------------------------

    def downselect(self, flight: Flight4D, met: MetDataset) -> MetDataset:
        """
        Downselects the meteorological dataset to the relevant subset for a given flight.

        This method calls the `downselect_met` method from PyContrails of the
        provided `Flight4D` object, passing in the meteorological dataset and
        buffer parameters
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
        """Intersect a trajectory with meteorological fields.

        For each ``met_var → out_col`` entry in ``params.var_map``:

        - **Wind vars** are read from the dedicated wind dataset if provided,
          otherwise fall back to the MET dataset. NaN values are replaced by 0.
        - **Non-wind vars** are read from the MET dataset only.
        - Missing vars raise ``KeyError`` if the column is in
          ``DEFAULT_REQUIRED_WEATHER_COLS``, otherwise they are silently
          skipped (optional).

        Also computes ``air_pressure`` from trajectory level coordinates and,
        if ``params.humidity_scaling`` is set, applies humidity scaling via its
        ``.eval()`` method.

        Args:
            flight: Typed ``Flight4D`` view (time, lat, lon, altitude).

        Returns:
            ``FlightWithWeather`` — zero-copy view with all meteorological
            columns attached and ``air_pressure`` computed.

        Raises:
            WeatherStepError: If the input is not a valid Flight4D, if a
                required meteorological variable is missing, if a column-length
                mismatch occurs, or if humidity scaling fails.
        """
        # Ensure upstream contract
        try:
            flight = Flight4D.from_flight(flight)
        except ValidationError as e:
            raise WeatherStepError(
                type(self).__name__, f"input is not Flight4D: {e}"
            ) from e

        # Downselect datasets
        self._ds_met = self.downselect(flight, self._met)
        self._ds_rad = self.downselect(flight, self._rad)
        if self._wind is not None:
            self._ds_wind = self.downselect(flight, self._wind)

        # Intersect MET variables and build a new Flight
        try:
            new_cols: dict[str, NDArray[np.floating[Any]]] = {}

            for met_var, out_col in self.params.var_map.items():
                src_ds = None

                if met_var in WIND_VARS:
                    # prefer wind dataset
                    if self._ds_wind is not None and met_var in self._ds_wind:
                        src_ds = self._ds_wind
                    # fallback to MET
                    elif met_var in self._ds_met:
                        src_ds = self._ds_met
                else:
                    # non-wind → MET only
                    if met_var in self._ds_met:
                        src_ds = self._ds_met

                if src_ds is None:
                    # missing in both places (or MET missing for non-wind)
                    if out_col in DEFAULT_REQUIRED_WEATHER_COLS:
                        if met_var in WIND_VARS:
                            raise KeyError(
                                f"required wind var '{met_var}' missing (looked in WIND then MET)"
                            )
                        raise KeyError(f"required met var '{met_var}' missing in MET")
                    # optional → skip
                    continue

                src = src_ds[met_var]
                vals = flight.intersect_met(
                    src,
                    method=self.params.method,
                    use_indices=self.params.use_indices,
                )

                if met_var in WIND_VARS:
                    vals = np.nan_to_num(vals, nan=0.0)

                new_cols[out_col] = vals

            df = flight.dataframe.reset_index(drop=True)

            # Assign columns directly (safer than concat with a new DF)
            for k, v in new_cols.items():
                if v.shape[0] != len(df):
                    raise ValueError(
                        f"Length mismatch for column {k}: {v.shape[0]} vs {len(df)}"
                    )
                df[k] = v

            # Directly compute and assign air_pressure
            df["air_pressure"] = flight.air_pressure

            base = Flight(
                data=df, attrs=getattr(flight, "attrs", None), fuel=flight.fuel
            )

        except Exception as e:
            raise WeatherStepError(type(self).__name__, f"intersect failed: {e}") from e

        # Optional humidity scaling
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

    def run_fleet(
        self, flights: list[Flight4D]
    ) -> tuple[list[FlightWithWeather], list[dict[str, Any]]]:
        """
        Fleet-level vectorized weather intersection.

        Converts List[Flight] → Fleet, downselects weather datasets to fleet envelope,
        intersects weather variables, optionally applies humidity scaling,
        then converts Fleet → List[Flight].

        Args:
            flights: List of interpolated flights (Flight4D)

        Returns:
            Tuple of (flights with weather data, error records for dropped flights)

        Raises:
            WeatherStepError: If weather intersection or humidity scaling fails
        """
        t0 = time.time()
        logger.info("Fleet-level weather intersection for %d flights...", len(flights))

        # Convert to Fleet
        pyc_fleet = flights_to_fleet(flights)

        # Downselect meteorological datasets to fleet envelope
        ds_met = pyc_fleet.downselect_met(
            self._met,
            longitude_buffer=self.params.lon_buf,
            latitude_buffer=self.params.lat_buf,
            time_buffer=self.params.time_buf,
            level_buffer=self.params.level_buf,
        )

        ds_wind = None
        if self._wind is not None:
            ds_wind = pyc_fleet.downselect_met(
                self._wind,
                longitude_buffer=self.params.lon_buf,
                latitude_buffer=self.params.lat_buf,
                time_buffer=self.params.time_buf,
                level_buffer=self.params.level_buf,
            )

        # Intersect weather variables
        new_cols = self._intersect_weather_variables(pyc_fleet, ds_met, ds_wind)

        # Add weather columns to fleet dataframe
        df = pyc_fleet.dataframe.reset_index(drop=True)
        for k, v in new_cols.items():
            df[k] = v

        # Directly compute and assign air_pressure for the entire fleet
        df["air_pressure"] = pyc_fleet.air_pressure

        fleet_with_weather = Fleet(
            data=df, attrs=pyc_fleet.attrs, fl_attrs=pyc_fleet.fl_attrs
        )

        logger.info("Weather intersection complete in %.2fs", time.time() - t0)

        # Convert back to List[Flight], detecting dropped flights
        flights_with_weather, errors = fleet_to_flights(
            fleet_with_weather, step_name="weather intersection"
        )

        # Optional humidity scaling
        if self.params.humidity_scaling is not None:
            flights_with_weather, scaling_errors = self._apply_humidity_scaling_fleet(
                flights_with_weather
            )
            errors.extend(scaling_errors)

        # Type narrowing
        typed = [FlightWithWeather.from_flight(f) for f in flights_with_weather]

        return typed, errors

    def _intersect_weather_variables(
        self, fleet: Fleet, ds_met: MetDataset, ds_wind: MetDataset | None
    ) -> dict[str, np.ndarray]:
        """Intersect weather variables for a fleet."""
        new_cols: dict[str, np.ndarray] = {}

        for met_var, out_col in self.params.var_map.items():
            src_ds = None

            if met_var in WIND_VARS:
                # Prefer wind dataset
                if ds_wind is not None and met_var in ds_wind:
                    src_ds = ds_wind
                # Fallback to MET
                elif met_var in ds_met:
                    src_ds = ds_met
            else:
                # Non-wind → MET only
                if met_var in ds_met:
                    src_ds = ds_met

            if src_ds is None:
                # Missing in both places (or MET missing for non-wind)
                if out_col in DEFAULT_REQUIRED_WEATHER_COLS:
                    if met_var in WIND_VARS:
                        raise KeyError(
                            f"required wind var '{met_var}' missing (looked in WIND then MET)"
                        )
                    raise KeyError(f"required met var '{met_var}' missing in MET")
                # Optional → skip
                continue

            src = src_ds[met_var]
            vals = fleet.intersect_met(
                src, method=self.params.method, use_indices=self.params.use_indices
            )

            if met_var in WIND_VARS:
                vals = np.nan_to_num(vals, nan=0.0)

            new_cols[out_col] = vals

        return new_cols

    def _apply_humidity_scaling_fleet(
        self, flights: list[FlightWithWeather]
    ) -> tuple[list[FlightWithWeather], list[dict[str, Any]]]:
        """Apply humidity scaling to a fleet."""
        if self.params.humidity_scaling is None:
            return flights, []

        t0 = time.time()
        logger.info("Applying humidity scaling...")

        fleet = flights_to_fleet(flights)

        # Call humidity scaling eval() which should return a Flight/Fleet
        scaled = self.params.humidity_scaling.eval(fleet)

        # Handle different return types
        if isinstance(scaled, Fleet):
            fleet = scaled
        elif isinstance(scaled, Flight):
            # Convert single Flight back to Fleet (shouldn't happen but handle it)
            fleet = Fleet.from_seq([scaled])
        else:
            raise WeatherStepError(
                type(self).__name__,
                f"humidity_scaling returned unexpected type: {type(scaled)}",
            )

        logger.info("Humidity scaling complete in %.2fs", time.time() - t0)
        return fleet_to_flights(fleet, step_name="humidity scaling")
