# weather.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, Tuple, Mapping, Optional, cast

import numpy as np
import pandas as pd
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.humidity_scaling import ConstantHumidityScaling

__all__ = [
    "WeatherProviderParams",
    "WeatherProviderProtocol",
    "WeatherStepError",
    "DEFAULT_REQUIRED_WEATHER_COLS",
    "FlightWithWeather",
    "WeatherProvider",
]

logger = logging.getLogger(__name__)

# Columns we guarantee after intersection
DEFAULT_REQUIRED_WEATHER_COLS: Final[tuple[str, ...]] = (
    "u_wind",             # from eastward_wind
    "v_wind",             # from northward_wind
    "air_temperature",
    "specific_humidity",
)

# ---------- Errors ----------
class WeatherStepError(RuntimeError):
    """Raised when weather downselect/intersection fails or yields invalid output."""


# ---------- Validated view (zero-copy) ----------
class FlightWithWeather(Flight):
    """
    Zero-copy view of a Flight guaranteed to contain core weather columns.
    """

    def __init__(self, data: pd.DataFrame, attrs: Optional[dict[str, Any]] = None) -> None:
        super().__init__(data=data, attrs=attrs)

    @classmethod
    def from_flight(
        cls,
        flight: Flight,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_WEATHER_COLS,
    ) -> "FlightWithWeather":
        missing = [c for c in required_cols if c not in flight]
        if missing:
            raise KeyError(f"FlightWithWeather missing required columns: {missing}")
        return cls(
            data=cast(pd.DataFrame, flight.data),
            attrs=getattr(flight, "attrs", None),
        )

    def has_columns(self, *cols: str) -> bool:
        return all(c in self for c in cols)


# ---------- Params ----------
@dataclass(frozen=True)
class WeatherProviderParams:
    """
    Configuration for weather buffering and interpolation.
    """
    lon_buf: Tuple[float, float] = (0.0, 0.0)
    lat_buf: Tuple[float, float] = (0.0, 0.0)
    time_buf: Tuple[np.timedelta64, np.timedelta64] = (
        np.timedelta64(0, "h"),
        np.timedelta64(0, "h"),
    )
    level_buf: Tuple[float, float] = (0.0, 0.0)
    interpolation_method: Literal["linear", "nearest"] = "linear"
    # Humidity scaling (optional); if set, applied after intersection
    humidity_scaling: Optional[ConstantHumidityScaling] = ConstantHumidityScaling(rhi_adj=0.99)


# ---------- Protocol ----------
class WeatherProviderProtocol(Protocol):
    """Protocol for weather data providers with met/rad datasets and intersection logic."""

    def met(self) -> MetDataset: ...
    def rad(self) -> MetDataset: ...
    def downselect(self, flight: Flight) -> MetDataset: ...
    def intersect(self, flight: Flight) -> Flight: ...


# ---------- Implementation ----------
class WeatherProvider(WeatherProviderProtocol):
    """
    Provide weather along a Flight:
      - downselect buffered region from `met`
      - interpolate core variables onto the trajectory
      - (optionally) apply humidity scaling
    Returns a base `Flight`; validate to `FlightWithWeather` at the boundary if needed.
    """

    def __init__(
        self,
        met: MetDataset,
        rad: MetDataset,
        wind: MetDataset,  # kept for future TAS/derived fields if you need it later
        params: Optional[WeatherProviderParams] = None,
    ) -> None:
        self._met = met
        self._rad = rad
        self._wind = wind
        self.params = params or WeatherProviderParams()

    # Avoid name clash with attributes; expose accessors
    def met(self) -> MetDataset:
        return self._met

    def rad(self) -> MetDataset:
        return self._rad

    def downselect(self, flight: Flight) -> MetDataset:
        """Down-select `met` to a buffered region around the flight."""
        try:
            return flight.downselect_met(
                self._met,
                longitude_buffer=self.params.lon_buf,
                latitude_buffer=self.params.lat_buf,
                time_buffer=self.params.time_buf,
                level_buffer=self.params.level_buf,
            )
        except Exception as e:
            logger.exception("Weather downselect failed")
            raise WeatherStepError(f"Weather downselect failed: {e}") from e

    def intersect(self, flight: Flight) -> Flight:
        """
        Interpolate weather variables onto the trajectory, optionally apply humidity scaling,
        and return a base `Flight` with weather columns.
        """
        # 1) Downselect met to flight corridor
        ds_met = self.downselect(flight)

        # 2) Interpolate vars
        try:
            df = cast(pd.DataFrame, flight.data).copy()
            # Map met vars → flight columns (aliases)
            var_map: Mapping[str, str] = {
                "eastward_wind": "u_wind",
                "northward_wind": "v_wind",
                "air_temperature": "air_temperature",
                "specific_humidity": "specific_humidity",
            }

            for met_var, out_col in var_map.items():
                vals = flight.intersect_met(
                    ds_met[met_var],
                    method=self.params.interpolation_method,
                    use_indices=True,
                )
                # Avoid NaNs for wind components if desired; keep others as-is
                if met_var in ("eastward_wind", "northward_wind"):
                    vals = np.nan_to_num(vals, nan=0.0)
                df[out_col] = vals

            out = Flight(data=df, attrs=getattr(flight, "attrs", None))

        except Exception as e:
            logger.exception("Weather interpolation failed")
            raise WeatherStepError(f"Weather interpolation failed: {e}") from e

        # 3) Optional: humidity scaling model adds/adjusts humidity-derived fields
        if self.params.humidity_scaling is not None:
            try:
                scaled = self.params.humidity_scaling.eval(source=out)  # GeoVectorDataset | Flight
                if not isinstance(scaled, Flight):
                    # Re-wrap into a Flight to keep our return type stable
                    df = scaled.dataframe  # GeoVectorDataset has `.dataframe`
                    out = Flight(data=df, attrs=getattr(scaled, "attrs", None))
                else:
                    out = scaled
            except Exception as e:
                logger.exception("Humidity scaling failed")
                raise WeatherStepError(f"Humidity scaling failed: {e}") from e
            
        # 4) Validate presence of required columns (zero-copy)
        try:
            _ = FlightWithWeather.from_flight(out)
        except KeyError as e:
            logger.error("Weather output missing required columns: %s", e)
            raise WeatherStepError(f"Weather output missing required columns: {e}") from e

        logger.info("Weather intersection completed successfully")
        return out
