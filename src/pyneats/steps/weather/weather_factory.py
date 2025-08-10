# weather_factory.py
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Mapping, Optional, ClassVar

import xarray as xr
from pycontrails import DiskCacheStore, MetDataset
from pycontrails.core.met_var import (
    AirTemperature,
    CloudAreaFractionInAtmosphereLayer,
    EastwardWind,
    Geopotential,
    MassFractionOfCloudIceInAir,
    NorthwardWind,
    RelativeHumidity,
    SpecificHumidity,
    VerticalVelocity,
)
from pycontrails.datalib.ecmwf import ERA5, PotentialVorticity, SurfaceSolarDownwardRadiation
from pycontrails.models.cocip import Cocip
from pycontrails.core.met_var import TOAOutgoingLongwaveFlux, TOANetDownwardShortwaveFlux
from pycontrails.core.met_var import MetVariable

from pyneats.steps.weather.weather_provider import WeatherProviderProtocol, WeatherProvider

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_WEATHER_OFFSET_H",
    "DEFAULT_PRESSURE_LEVELS_HPA",
    "DEFAULT_HORIZONTAL_RES_DEG",
    "WeatherFactoryParams",
    "WeatherFactoryError",
    "WeatherFactoryProtocol",
    "ERA5Factory",
    "DWDFactory",
]

# ---- configuration ----
DEFAULT_WEATHER_OFFSET_H: Final[int] = 36
DEFAULT_PRESSURE_LEVELS_HPA: Final[tuple[float, ...]] = (
    550, 500, 450, 400, 350, 300, 250, 225, 200, 175, 150, 125
)
DEFAULT_HORIZONTAL_RES_DEG: Final[float] = 0.25


# ---- error type ----
class WeatherFactoryError(RuntimeError):
    """Raised when the weather factory fails to load or standardize datasets."""


# ---- params ----
@dataclass(frozen=True)
class WeatherFactoryParams:
    data_dir: str
    horizontal_resolution: float = DEFAULT_HORIZONTAL_RES_DEG
    pressure_levels: tuple[float, ...] = DEFAULT_PRESSURE_LEVELS_HPA
    weather_offset_hours: int = DEFAULT_WEATHER_OFFSET_H

    def time_bounds(self, dt: datetime) -> tuple[str, str]:
        """Return (dt, dt + offset) as ISO strings."""
        later = dt + timedelta(hours=self.weather_offset_hours)
        fmt = "%Y-%m-%d %H:%M:%S"
        return dt.strftime(fmt), later.strftime(fmt)


# ---- protocol for factories ----
class WeatherFactoryProtocol:
    def __call__(self, asofdate: datetime, /) -> WeatherProviderProtocol:  # pragma: no cover
        raise NotImplementedError


# ---- ERA5 factory ----
class ERA5Factory(WeatherFactoryProtocol):
    """Thin wrapper building a WeatherProvider from ERA5 via pycontrails."""

    def __init__(self, params: WeatherFactoryParams) -> None:
        self.params = params

    def __call__(self, asofdate: datetime, /) -> WeatherProviderProtocol:
        cache = DiskCacheStore(cache_dir=self.params.data_dir, allow_clear=True)
        t0, t1 = self.params.time_bounds(asofdate)

        try:
            era5_ml = ERA5(
                time=(t0, t1),
                variables=(Cocip.met_variables + Cocip.optional_met_variables),
                pressure_levels=self.params.pressure_levels,
                grid=self.params.horizontal_resolution,
                cachestore=cache,
            )
            met = era5_ml.open_metdataset()

            era5_sl = ERA5(
                time=(t0, t1),
                variables=Cocip.rad_variables,
                grid=self.params.horizontal_resolution,
                cachestore=cache,
            )
            rad = era5_sl.open_metdataset()

        except Exception as e:
            logger.exception("Failed to open ERA5 datasets")
            raise WeatherFactoryError(f"ERA5 loading failed: {e}") from e

        logger.info(
            "ERA5 weather ready",
            extra={
                "time_start": t0,
                "time_end": t1,
                "grid_deg": self.params.horizontal_resolution,
                "levels_hpa": len(self.params.pressure_levels),
            },
        )
        # Surface wind is included in MET in ERA5 CoCiP recipes; pass MET for wind as well.
        return WeatherProvider(met, rad, met)


# ---- DWD ICON-2mom factory ----
class DWDFactory(WeatherFactoryProtocol):
    """
    Build a WeatherProvider from DWD ICON-2mom forecast files already on disk.

    Expects files like:
        MRV_T_<step>_<YYYYMMDD><HH>.nc   (MET + RAD variables)
        MRV_T_UV_<step>_<YYYYMMDD><HH>.nc (surface U/V)
    """

    _required_map: ClassVar[Mapping[str, MetVariable]] = {
        "u": EastwardWind,
        "v": NorthwardWind,
        "omega": VerticalVelocity,
        "temp": AirTemperature,
        "qv": SpecificHumidity,
        "qi": MassFractionOfCloudIceInAir,
    }

    _optional_map: ClassVar[Mapping[str, MetVariable]] = {
        "geopot": Geopotential,
        "clc": CloudAreaFractionInAtmosphereLayer,
        "rhi": RelativeHumidity,
        "pv": PotentialVorticity,
    }

    _rad_map: ClassVar[Mapping[str, MetVariable]] = {
        "tsr": TOANetDownwardShortwaveFlux,
        "olr": TOAOutgoingLongwaveFlux,
        "sdr": SurfaceSolarDownwardRadiation,
    }

    _wind_map:  ClassVar[Mapping[str, MetVariable]] = {
        'u': EastwardWind,
        'v': NorthwardWind}

    def __init__(self, params: WeatherFactoryParams) -> None:
        self.params = params

    # --- public ---
    def __call__(self, asofdate: datetime, hour: Optional[int] = None) -> WeatherProviderProtocol:
        run_hour = hour if hour is not None else asofdate.hour
        date_str = asofdate.strftime("%Y%m%d")

        try:
            # MET + RAD in one file set; standardize once, then split
            ds_all = self._load_and_standardize(
                prefix="MRV_T",
                date_str=date_str,
                hour=run_hour,
                var_map={**self._required_map, **self._optional_map, **self._rad_map},
            )
            # MET selection
            met_vars = [v.standard_name for v in {**self._required_map, **self._optional_map}.values()]
            ds_met = ds_all[met_vars]
            met = MetDataset(ds_met)  # zero-copy view into ds_all

            # RAD selection → ensure a level dimension exists (CoCiP expects it)
            rad_vars = [v.standard_name for v in self._rad_map.values()]
            ds_rad = ds_all[rad_vars]
            if "level" not in ds_rad.dims:
                ds_rad = ds_rad.expand_dims({"level": [-1]})
            rad = MetDataset(ds_rad)

            # WIND (surface U/V) lives in a different file set
            ds_wind = self._load_and_standardize(
                prefix="MRV_T_UV",
                date_str=date_str,
                hour=run_hour,
                var_map=type(self)._wind_map,   # or DWDFactory._wind_map
            )
            wind = MetDataset(ds_wind)

        except WeatherFactoryError:
            raise
        except Exception as e:
            logger.exception("Failed to construct DWD WeatherProvider")
            raise WeatherFactoryError(f"DWD processing failed: {e}") from e

        logger.info(
            "DWD weather ready",
            extra={"date": date_str, "hour": run_hour, "dir": self.params.data_dir},
        )
        return WeatherProvider(met, rad, wind)

    # --- helpers ---
    def _load_and_standardize(
        self,
        *,
        prefix: str,
        date_str: str,
        hour: int,
        var_map: Mapping[str, MetVariable],
    ) -> xr.Dataset:
        files = self._select_files(prefix, self.params.data_dir, date_str, hour)
        if not files:
            msg = f"No files for {prefix} on {date_str} at hour {hour:02d} in {self.params.data_dir}"
            logger.error(msg)
            raise WeatherFactoryError(msg)

        try:
            ds = xr.open_mfdataset(files, combine="by_coords")  # lazy, no copy
            ds = self._standardize_dims(ds)
            # Convert Pa→hPa if 'level' is a coordinate in Pa; tolerate if already hPa
            if "level" in ds.coords:
                # Heuristics: pressure in Pa is typically > 1000*100; hPa <= 1100
                sample = float(ds["level"].values[0])
                if sample > 2000:  # Pa
                    ds = ds.assign_coords(level=ds["level"].astype("float64") / 100.0)

            ds = self._standardize_vars(ds, var_map)

            # provenance
            ds.attrs.update({"provider": "DWD", "dataset": "ICON-2mom", "product": "forecast"})

        except WeatherFactoryError:
            raise
        except Exception as e:
            logger.exception("Failed to open/standardize DWD dataset")
            raise WeatherFactoryError(f"DWD standardization failed: {e}") from e

        return ds

    @staticmethod
    def _select_files(prefix: str, directory: str, date: str, hour: int) -> list[str]:
        patt = re.compile(fr"^{re.escape(prefix)}_\d{{3}}_{date}{hour:02d}\.nc$")
        candidates = (os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".nc"))
        return sorted(f for f in candidates if patt.match(os.path.basename(f)))

    @staticmethod
    def _standardize_dims(ds: xr.Dataset) -> xr.Dataset:
        # rename both dims and coords if present; idempotent if already standard
        remap = {"plev": "level", "lat": "latitude", "lon": "longitude"}
        existing_vars = {k: v for k, v in remap.items() if k in ds.variables}
        existing_dims = {k: v for k, v in remap.items() if k in ds.dims}

        if existing_dims:
            ds = ds.rename_dims(existing_dims)
        if existing_vars:
            ds = ds.rename_vars(existing_vars)

        # Sometimes surface wind is 'U'/'V'
        if "U" in ds.variables or "V" in ds.variables:
            rename_uv = {}
            if "U" in ds.variables:
                rename_uv["U"] = "u"
            if "V" in ds.variables:
                rename_uv["V"] = "v"
            ds = ds.rename_vars(rename_uv)
        return ds

    @staticmethod
    def _standardize_vars(ds: xr.Dataset, var_map: Mapping[str, MetVariable]) -> xr.Dataset:
        for raw, mv in var_map.items():
            if raw in ds:
                std = mv.standard_name
                ds[raw].attrs.update({"long_name": mv.long_name, "standard_name": std, "units": mv.units})
                if raw != std:
                    ds = ds.rename({raw: std})
        return ds
