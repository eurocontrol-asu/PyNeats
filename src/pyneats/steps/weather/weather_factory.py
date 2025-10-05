# steps/weather/weather_factory.py
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final, Mapping, Optional

import xarray as xr
from pycontrails import DiskCacheStore, MetDataset
from pycontrails.core.met_var import (
    MetVariable,
    AirTemperature,
    CloudAreaFractionInAtmosphereLayer,
    EastwardWind,
    Geopotential,
    MassFractionOfCloudIceInAir,
    NorthwardWind,
    RelativeHumidity,
    SpecificHumidity,
    VerticalVelocity,
    TOAOutgoingLongwaveFlux,
    TOANetDownwardShortwaveFlux,
)
from pycontrails.datalib.ecmwf import (
    ERA5,
    PotentialVorticity,
    SurfaceSolarDownwardRadiation,
)
from pycontrails.models.cocip import Cocip

from pyneats.steps.weather.weather_provider import (
    WeatherProvider,
    WeatherProviderProtocol,
)
from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_WEATHER_OFFSET_H",
    "DEFAULT_PRESSURE_LEVELS_HPA",
    "DEFAULT_HORIZONTAL_RES_DEG",
    "WeatherFactoryParams",
    "ERA5DiskCacheSpec",
    "DWDZarrCacheSpec",
    "WeatherCacheConfig",
    "WeatherFactoryError",
    "WeatherFactoryProtocol",
    "ERA5Factory",
    "DWDFactory",
]

# ---------------- defaults ----------------
DEFAULT_WEATHER_OFFSET_H: Final[int] = 36
DEFAULT_PRESSURE_LEVELS_HPA: Final[tuple[float, ...]] = (
    550,
    500,
    450,
    400,
    350,
    300,
    250,
    225,
    200,
    175,
    150,
    125,
)
DEFAULT_HORIZONTAL_RES_DEG: Final[float] = 0.25
DEFAULT_SDR_ACCUMULATE_DT_S: Final[int] = 3600  # 1 hour


# ---------------- error ----------------
class WeatherFactoryError(RuntimeError):
    """Raised when a weather factory fails to load or standardize datasets."""


# ---------------- cache specs ----------------
@dataclass(frozen=True)
class ERA5DiskCacheSpec:
    """PyContrails DiskCacheStore (used with ERA5)."""

    cache_dir: str
    consolidated: bool = True
    read_only: bool = False
    allow_clear: bool = False
    compressor: Optional[str] = None


@dataclass(frozen=True)
class DWDZarrCacheSpec:
    met_store: str
    rad_store: str
    wind_store: Optional[str] = None  # make optional
    build_if_missing: bool = True
    consolidated: bool = True  # kept for backward compat; not used on read anymore
    # xarray chunk hints for writing (ignored for read)
    met_chunks: Optional[Mapping[str, int]] = None
    rad_chunks: Optional[Mapping[str, int]] = None
    wind_chunks: Optional[Mapping[str, int]] = None
    # Unit fix: convert SDR [W m-2] to [J m-2] by multiplying by dt (seconds)
    sdr_accumulate_dt_s: Optional[int] = (
        DEFAULT_SDR_ACCUMULATE_DT_S  # 1 hour by default; None to skip
    )


@dataclass(frozen=True)
class WeatherCacheConfig:
    """Unified cache config; pick the one relevant for the backend."""

    disk: Optional[ERA5DiskCacheSpec] = None  # ERA5
    zarr: Optional[DWDZarrCacheSpec] = None  # DWD


# ---------------- params ----------------
@dataclass(frozen=True)
class WeatherFactoryParams:
    # for ERA5 and for DWD live reading
    data_dir: str
    horizontal_resolution: float = DEFAULT_HORIZONTAL_RES_DEG
    pressure_levels: tuple[float, ...] = DEFAULT_PRESSURE_LEVELS_HPA
    weather_offset_hours: int = DEFAULT_WEATHER_OFFSET_H

    # unified optional cache config
    cache: Optional[WeatherCacheConfig] = None

    # optional xarray chunks (read-time hints)
    chunks: Optional[Mapping[str, int]] = None

    def time_bounds(self, dt: datetime) -> tuple[str, str]:
        later = dt + timedelta(hours=self.weather_offset_hours)
        fmt = "%Y-%m-%d %H:%M:%S"
        return dt.strftime(fmt), later.strftime(fmt)


# ---------------- protocol ----------------
class WeatherFactoryProtocol:
    def __call__(
        self, asofdate: datetime, hour: Optional[int] = None
    ) -> WeatherProviderProtocol:  # pragma: no cover
        raise NotImplementedError


# ---------------- ERA5 ----------------
class ERA5Factory(WeatherFactoryProtocol):
    """
    Build a WeatherProvider from ERA5. If cache.disk is provided, pass a DiskCacheStore.
    API is the same as DWD (__call__(asofdate, hour=None)); hour is ignored.
    """

    def __init__(self, params: WeatherFactoryParams) -> None:
        self.params = params

    def __call__(
        self, asofdate: datetime, hour: Optional[int] = None
    ) -> WeatherProviderProtocol:
        disk = self.params.cache.disk if self.params.cache else None
        cachestore = (
            DiskCacheStore(cache_dir=disk.cache_dir, allow_clear=disk.allow_clear)
            if disk
            else None
        )

        t0, t1 = self.params.time_bounds(asofdate)
        xr_kwargs = {"chunks": self.params.chunks} if self.params.chunks else None

        try:
            era5_ml = ERA5(
                time=(t0, t1),
                variables=(Cocip.met_variables + Cocip.optional_met_variables),
                pressure_levels=self.params.pressure_levels,
                grid=self.params.horizontal_resolution,
                cachestore=cachestore,
            )
            met = era5_ml.open_metdataset(xr_kwargs=xr_kwargs)

            era5_sl = ERA5(
                time=(t0, t1),
                variables=Cocip.rad_variables,
                grid=self.params.horizontal_resolution,
                cachestore=cachestore,
            )
            rad = era5_sl.open_metdataset(xr_kwargs=xr_kwargs)

        except Exception as e:
            logger.exception("ERA5 loading failed")
            raise WeatherFactoryError(f"ERA5 loading failed: {e}") from e

        extra: dict[str, object] = {
            "time_start": t0,
            "time_end": t1,
            "grid_deg": self.params.horizontal_resolution,
            "levels_hpa": len(self.params.pressure_levels),
            "cache_dir": (disk.cache_dir if disk else None),
        }
        logger.info("ERA5 weather ready", extra=extra)

        return WeatherProvider(met=met, rad=rad, wind=met)


# ---------------- DWD ICON-2mom ----------------
class DWDFactory(WeatherFactoryProtocol):
    """
    DWD factory that can either:
      - read NetCDF files directly (no cache), or
      - build & read Zarr stores (cache.zarr).
    """

    # Maps (matching your “dirty” script)
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

    _wind_map: ClassVar[Mapping[str, MetVariable]] = {
        "u": EastwardWind,
        "v": NorthwardWind,
    }

    def __init__(self, params: WeatherFactoryParams) -> None:
        self.params = params

    # ---------- public API ----------
    def __call__(
        self, asofdate: datetime, hour: Optional[int] = None
    ) -> WeatherProviderProtocol:

        zc = self.params.cache.zarr if self.params.cache else None
        run_hour = asofdate.hour if hour is None else hour
        date_str = asofdate.strftime("%Y%m%d")

        if zc:
            # build if requested + missing (consider wind_store too if provided)
            if zc.build_if_missing:
                need_build = (not os.path.exists(zc.met_store)) or (
                    not os.path.exists(zc.rad_store)
                )
                if zc.wind_store is not None:
                    need_build = need_build or (not os.path.exists(zc.wind_store))
                if need_build:
                    self.build_cache(asofdate, hour=run_hour, overwrite=False)

            # compute a time window (optional) and open via weather_store
            t0, t1 = self.params.time_bounds(asofdate)
            try:
                zp = ZarrPaths(zc.met_store, zc.rad_store, zc.wind_store)
                wp = get_weather_from_zarr(zp, t0=t0, t1=t1, chunks=self.params.chunks)
            except Exception as e:
                logger.exception("Failed to open DWD zarr cache")
                raise WeatherFactoryError(f"Open zarr cache failed: {e}") from e

            logger.info(
                "DWD weather ready (zarr cache)",
                extra={
                    "met_store": zc.met_store,
                    "rad_store": zc.rad_store,
                    "wind_store": zc.wind_store,
                    "date": date_str,
                    "hour": run_hour,
                },
            )
            return wp

        # Fallback: live NetCDF read (no cache)
        try:
            ds_all = self._load_and_standardize_live(
                prefix="MRV_T",
                date_str=date_str,
                hour=run_hour,
                var_map={**self._required_map, **self._optional_map, **self._rad_map},
            )

            met_vars = [
                v.standard_name
                for v in {**self._required_map, **self._optional_map}.values()
            ]
            rad_vars = [v.standard_name for v in self._rad_map.values()]

            ds_met = ds_all[met_vars]
            ds_rad = ds_all[rad_vars]

            if "level" not in ds_rad.dims:
                ds_rad = ds_rad.expand_dims({"level": [-1]})

            met = MetDataset(ds_met)
            rad = MetDataset(ds_rad)

            # WIND
            ds_wind = self._load_and_standardize_live(
                prefix="MRV_T_UV",
                date_str=date_str,
                hour=run_hour,
                var_map=self._wind_map,
            )

            wind = MetDataset(ds_wind)

        except Exception as e:
            logger.exception("DWD live processing failed")
            raise WeatherFactoryError(f"DWD processing failed: {e}") from e

        logger.info(
            "DWD weather ready (live)",
            extra={"date": date_str, "hour": run_hour, "dir": self.params.data_dir},
        )
        return WeatherProvider(met=met, rad=rad, wind=wind)

    # ---------- cache builder ----------
    def build_cache(
        self, asofdate: datetime, *, hour: Optional[int] = None, overwrite: bool = False
    ) -> tuple[str, str]:
        """
        Build (or rebuild) the DWD zarr cache. Returns (met_store, rad_store) paths.
        Mirrors your “dirty” script: rename dims, unit fixes, map vars, chunk, write, consolidate.
        """
        zc = self.params.cache.zarr if self.params.cache else None
        if not zc:
            raise WeatherFactoryError(
                "No ZarrCacheSpec provided; cannot build zarr cache."
            )

        run_hour = asofdate.hour if hour is None else hour
        date_str = asofdate.strftime("%Y%m%d")

        if (
            (not overwrite)
            and os.path.exists(zc.met_store)
            and os.path.exists(zc.rad_store)
        ):
            logger.info(
                "DWD zarr cache already exists; skipping write",
                extra={"met_store": zc.met_store, "rad_store": zc.rad_store},
            )
            return (zc.met_store, zc.rad_store)

        # 1) open live NetCDF
        ds_all = self._load_and_standardize_live(
            prefix="MRV_T",
            date_str=date_str,
            hour=run_hour,
            var_map={**self._required_map, **self._optional_map, **self._rad_map},
        )

        # 2) split
        met_vars = [
            v.standard_name
            for v in {**self._required_map, **self._optional_map}.values()
        ]
        rad_vars = [v.standard_name for v in self._rad_map.values()]
        met_ds_xr = ds_all[met_vars]
        rad_ds_xr = ds_all[rad_vars]
        if "level" not in rad_ds_xr.dims:
            rad_ds_xr = rad_ds_xr.expand_dims({"level": [-1]})

        # 3) chunk (use defaults similar to your script)
        met_chunks = zc.met_chunks or {
            "time": 1,
            "level": 10,
            "latitude": 256,
            "longitude": 256,
        }
        rad_chunks = zc.rad_chunks or {
            "time": 1,
            "level": 1,
            "latitude": 256,
            "longitude": 256,
        }
        met_ds_xr = met_ds_xr.chunk(met_chunks)
        rad_ds_xr = rad_ds_xr.chunk(rad_chunks)

        # 4) write zarr (metadata already consolidated during write)

        mode = "w"  # we already checked existence above
        try:
            met_dir = os.path.dirname(zc.met_store)
            rad_dir = os.path.dirname(zc.rad_store)
            os.makedirs(met_dir, exist_ok=True)
            os.makedirs(rad_dir, exist_ok=True)

            # optional SDR accumulation (W m-2 -> J m-2)
            if (zc.sdr_accumulate_dt_s is not None) and (
                "surface_solar_downward_radiation" in rad_ds_xr
            ):
                sdr = "surface_solar_downward_radiation"
                rad_ds_xr[sdr] = rad_ds_xr[sdr] * float(zc.sdr_accumulate_dt_s)
                rad_ds_xr[sdr].attrs["units"] = "J m**-2"

            met_ds_xr.to_zarr(zc.met_store, mode=mode, consolidated=True)
            rad_ds_xr.to_zarr(zc.rad_store, mode=mode, consolidated=True)

        except Exception as e:
            raise WeatherFactoryError(f"Writing zarr failed: {e}") from e

        if zc.wind_store:
            ds_wind = self._load_and_standardize_live(
                prefix="MRV_T_UV",
                date_str=date_str,
                hour=run_hour,
                var_map=self._wind_map,
            )
            # choose sensible 2D chunks (add level if present)

            wind_ds_xr = ds_wind[[v.standard_name for v in self._wind_map.values()]]
            wind_chunks = zc.wind_chunks or {
                "time": 1,
                "level": 10,
                "latitude": 256,
                "longitude": 256,
            }
            wind_ds_xr = wind_ds_xr.chunk(wind_chunks)


            # Combine two wind sources along level dimension 

            wind_ds_xr_low = ds_wind[[v.standard_name for v in self._wind_map.values()]]
            wind_ds_xr_high  = met_ds_xr[[v.standard_name for v in self._wind_map.values()]]
            wind_ds_combined = xr.concat(
                [wind_ds_xr_low, wind_ds_xr_high],
                dim="level",
                data_vars="all",
                coords="minimal",
                compat="equals",
            )
            wind_ds_combined = wind_ds_combined.sortby("level")
            
            wind_ds_xr = wind_ds_combined.chunk(wind_chunks)


            os.makedirs(os.path.dirname(zc.wind_store), exist_ok=True)
            wind_ds_xr.to_zarr(zc.wind_store, mode=mode, consolidated=True)

        logger.info(
            "DWD zarr cache built",
            extra={"met_store": zc.met_store, "rad_store": zc.rad_store},
        )
        return (zc.met_store, zc.rad_store)

    # ---------- live loader (NetCDF) mirroring your script ----------
    def _load_and_standardize_live(
        self,
        prefix: str,
        date_str: str,
        hour: int,
        var_map: Mapping[str, MetVariable],
    ) -> xr.Dataset:

        files = self._select_files(prefix, self.params.data_dir, date_str, hour)
        if not files:
            raise WeatherFactoryError(
                f"No files for {prefix} on {date_str} at hour {hour:02d} in {self.params.data_dir}"
            )

        try:
            ds = xr.open_mfdataset(files, combine="by_coords")
            ds = self._standardize_dims(ds)
            # Convert Pa → hPa on level coord if needed
            if "level" in ds and float(ds["level"].values[0]) > 2000.0:
                ds = ds.assign_coords(level=ds["level"].astype("float64") / 100.0)

            # Unit fixes BEFORE mapping (match your script)
            if "clc" in ds:
                ds["clc"] = ds["clc"] / 100.0
                ds["clc"].attrs["units"] = "1"
            if "rhi" in ds and ds["rhi"].attrs.get("units", "-") in ("-", "%"):
                ds["rhi"].attrs["units"] = "1"
            # SDR conversion is done later during zarr build if requested

            # Map variables and sanity check units
            # ds = self._standardize_vars(ds, {**self._required_map, **self._optional_map, **self._rad_map})
            ds = self._standardize_vars(ds, var_map)

            ds.attrs.update(
                {"provider": "DWD", "dataset": "ICON-2mom", "product": "forecast"}
            )

        except Exception as e:
            raise WeatherFactoryError(f"DWD standardization failed: {e}") from e

        return ds

    @staticmethod
    def _select_files(prefix: str, directory: str, date: str, hour: int) -> list[str]:
        patt = re.compile(rf"^{re.escape(prefix)}_\d{{3}}_{date}{hour:02d}\.nc$")
        candidates = (
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.endswith(".nc")
        )
        return sorted(f for f in candidates if patt.match(os.path.basename(f)))

    @staticmethod
    def _standardize_dims(ds: xr.Dataset) -> xr.Dataset:
        remap = {"plev": "level", "lat": "latitude", "lon": "longitude"}
        if any(k in ds.dims for k in remap):
            ds = ds.rename_dims({k: v for k, v in remap.items() if k in ds.dims})
        if any(k in ds.variables for k in remap):
            ds = ds.rename_vars({k: v for k, v in remap.items() if k in ds.variables})

        # uppercase U/V variants
        uv = {}
        if "U" in ds.variables:
            uv["U"] = "u"
        if "V" in ds.variables:
            uv["V"] = "v"
        if uv:
            ds = ds.rename_vars(uv)
        return ds

    @staticmethod
    def _norm_units(u: Optional[str]) -> str:
        if not u:
            return ""
        # light normalization: remove spaces/asterisks; fold "**" → "^"
        return u.replace("**", "^").replace("*", "").replace(" ", "")

    def _standardize_vars(
        self, ds: xr.Dataset, var_map: Mapping[str, MetVariable]
    ) -> xr.Dataset:
        for raw, mv in var_map.items():
            if raw not in ds:
                logger.debug("%s not found in dataset", raw)
                continue

            std = mv.standard_name
            src_da = ds[raw]

            src_units: str = str(src_da.attrs.get("units", "") or "")
            tgt_units_raw: Optional[str] = getattr(mv, "units", None)
            tgt_units: str = self._norm_units(tgt_units_raw)
            src_units_n: str = self._norm_units(src_units)

            if src_units_n and tgt_units and src_units_n != tgt_units:
                logger.warning(
                    "Unit mismatch for %s: src=%s tgt=%s",
                    raw,
                    src_units,
                    tgt_units_raw or "",
                )

            # update attrs safely; only set 'units' if we actually have one
            new_attrs = {
                "long_name": mv.long_name,
                "standard_name": std,
            }
            if tgt_units_raw:  # avoid writing None
                new_attrs["units"] = tgt_units_raw
            src_da.attrs.update(new_attrs)

            if raw != std:
                ds = ds.rename({raw: std})

        return ds
