# steps/weather/weather_provider.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final, Literal, Mapping, Optional, Protocol, runtime_checkable, cast

import numpy as np
import pandas as pd
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.humidity_scaling import ConstantHumidityScaling

from pyneats.core.steps import BaseStep, Step, StepError
from pyneats.core.views import FlightView

__all__ = [
    "DEFAULT_REQUIRED_WEATHER_COLS",
    "FlightWithWeather",
    "WeatherStepError",
    "WeatherProviderParams",
    "WeatherProvider",
    "WeatherProviderProtocol",
]

logger = logging.getLogger(__name__)

DEFAULT_REQUIRED_WEATHER_COLS: Final[tuple[str, ...]] = (
    "u_wind",
    "v_wind",
    "air_temperature",
    "specific_humidity",
)
DEFAULT_OPTIONAL_WEATHER_COLS: Final[tuple[str, ...]] = ("air_pressure",)

class FlightWithWeather(FlightView):
    REQUIRED = DEFAULT_REQUIRED_WEATHER_COLS
    OPTIONAL = DEFAULT_OPTIONAL_WEATHER_COLS

class WeatherStepError(StepError):
    """Normalized domain error for the weather step."""

InterpolationMethod = Literal["linear", "nearest"]

@dataclass(frozen=True)
class WeatherProviderParams:
    lon_buf: tuple[float, float] = (0.0, 0.0)
    lat_buf: tuple[float, float] = (0.0, 0.0)
    time_buf: tuple[np.timedelta64, np.timedelta64] = (np.timedelta64(0, "h"), np.timedelta64(0, "h"))
    level_buf: tuple[float, float] = (0.0, 0.0)

    method: InterpolationMethod = "linear"
    use_indices: bool = True

    humidity_scaling: Optional[ConstantHumidityScaling] = field(
        default_factory=lambda: ConstantHumidityScaling(rhi_adj=0.99)
    )

    var_map: Mapping[str, str] = field(
        default_factory=lambda: {
            "eastward_wind": "u_wind",
            "northward_wind": "v_wind",
            "air_temperature": "air_temperature",
            "specific_humidity": "specific_humidity",
        }
    )

@runtime_checkable
class WeatherProviderProtocol(Step[Flight, FlightWithWeather], Protocol):
    def met(self) -> MetDataset: ...
    def rad(self) -> MetDataset: ...
    def ds_met(self) -> MetDataset: ...
    def ds_rad(self) -> MetDataset: ...
    def downselect(self, flight: Flight) -> MetDataset: ...
    def intersect(self, flight: Flight) -> Flight: ...

class WeatherProvider(BaseStep[Flight, FlightWithWeather]):
    def __init__(self, met: MetDataset, 
                 rad: MetDataset, 
                 wind: MetDataset, *, params: WeatherProviderParams | None = None) -> None:
        super().__init__()
        self._met = met
        self._rad = rad
        self.wind = wind
        self.params = params or WeatherProviderParams()

        self._ds_met: MetDataset | None = None
        self._ds_rad: MetDataset | None = None

    def met(self) -> MetDataset:  # accessor
        return self._met

    def ds_met(self) -> MetDataset | None:  # accessor
        return self._ds_met
    
    def ds_rad(self) -> MetDataset | None:  # accessor
        return self._ds_rad
    
    def rad(self) -> MetDataset:  # accessor
        return self._rad

    def intersect(self, flight: Flight) -> Flight:
        """
        Intersect MET on the trajectory and return a Flight (typed view is a Flight subclass).
        Prefer calling the step directly: provider(flight).
        """
        out = self(flight)            # FlightWithWeather (subclass of Flight)
        return out                    # zero-copy; fine to return as Flight

    def downselect(self, flight: Flight, met: MetDataset) -> MetDataset:
        try:
            return flight.downselect_met(
                met,
                longitude_buffer=self.params.lon_buf,
                latitude_buffer=self.params.lat_buf,
                time_buffer=self.params.time_buf,
                level_buffer=self.params.level_buf,
            )
        except Exception as e:
            raise WeatherStepError(type(self).__name__, f"downselect failed: {e}") from e

    def run(self, flight: Flight) -> FlightWithWeather:
        
        self._ds_met = self.downselect(flight, self._met)
        self._ds_rad = self.downselect(flight, self._rad)

        df = cast(pd.DataFrame, flight.data)
        try:
            for met_var, out_col in self.params.var_map.items():
                if met_var not in self._ds_met:
                    if out_col in DEFAULT_REQUIRED_WEATHER_COLS:
                        raise KeyError(f"required met var '{met_var}' missing in downselected MET")
                    continue
                vals = flight.intersect_met(
                    self._ds_met[met_var],
                    method=self.params.method,
                    use_indices=self.params.use_indices,
                )
                if met_var in ("eastward_wind", "northward_wind"):
                    vals = np.nan_to_num(vals, nan=0.0)
                df[out_col] = vals
        except Exception as e:
            raise WeatherStepError(type(self).__name__, f"intersect failed: {e}") from e

        if self.params.humidity_scaling is not None:
            try:
                result = self.params.humidity_scaling.eval(source=flight)

                if isinstance(result, Flight):
                    # model returned a new Flight
                    flight = result

                elif result is None:
                    # model mutated `flight` in place -> nothing to do
                    pass

                elif hasattr(result, "dataframe"):
                    # model returned something with a `.dataframe` (e.g., FlightView/DataFrame-like)
                    flight = Flight(
                        data=result.dataframe,
                        attrs=getattr(result, "attrs", getattr(flight, "attrs", None)),
                    )

                else:
                    raise TypeError(
                        f"Unexpected return from humidity_scaling.eval: {type(result)!r}"
                    )

            except Exception as e:
                raise WeatherStepError(type(self).__name__, f"humidity scaling failed: {e}") from e
            
        try:
            out = FlightWithWeather.from_flight(flight)
        except Exception as e:
            raise WeatherStepError(type(self).__name__, f"validation failed: {e}") from e

        return out
