# steps/weather/weather_store.py (excerpt)


# weather_store.py
# Utilities for handling weather data storage and retrieval (Zarr/NetCDF)

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Mapping, Tuple, Dict
import os
import xarray as xr
from pycontrails import MetDataset
from .weather_provider import WeatherProvider


# Stores paths to Zarr datasets for meteorological, radiative, and wind data
@dataclass(frozen=True)
class ZarrPaths:
    met_store: str
    rad_store: str
    wind_store: Optional[str] = None


# Check if a Zarr store is consolidated (has .zmetadata)
def _is_consolidated(path: str) -> bool:
    return os.path.exists(os.path.join(path, ".zmetadata"))


# Normalize chunk mapping to a sorted tuple for cache keying
def _norm_chunks(
    ch: Optional[Mapping[str, int]]
) -> Optional[Tuple[Tuple[str, int], ...]]:
    if not ch:
        return None
    return tuple(sorted((k, int(v)) for k, v in ch.items()))


# In-memory cache for opened MetDataset objects (per process)
_DATASET_CACHE: Dict[
    Tuple[str, Optional[str], Optional[str], Optional[Tuple[Tuple[str, int], ...]]],
    MetDataset,
] = {}


# Open a MetDataset from a Zarr store, with optional time slicing and chunking, using cache
def _open_metdataset_from_zarr(
    path: str,
    *,
    t0: Optional[str],
    t1: Optional[str],
    chunks: Optional[Mapping[str, int]],
) -> MetDataset:
    """
    Open a Zarr dataset as MetDataset, optionally slice by time and rechunk.
    Uses a per-process cache to avoid repeated disk reads.
    """
    key = (path, t0, t1, _norm_chunks(chunks))
    if key in _DATASET_CACHE:
        return _DATASET_CACHE[key]

    ds = xr.open_zarr(path, consolidated=_is_consolidated(path))
    if t0 and t1:
        ds = ds.sel(time=slice(t0, t1))
    if chunks:
        ds = ds.chunk(chunks)

    md = MetDataset(ds)
    _DATASET_CACHE[key] = md
    return md


# Open wind MetDataset, or fall back to met if wind store is not provided
def _open_wind_metdataset(
    wind_path: Optional[str],
    met_fallback: MetDataset,
    *,
    t0: Optional[str],
    t1: Optional[str],
    chunks: Optional[Mapping[str, int]],
) -> MetDataset:
    """
    Open wind MetDataset from Zarr, or reuse met_fallback if wind_path is None.
    """
    if wind_path is None:
        return met_fallback
    return _open_metdataset_from_zarr(wind_path, t0=t0, t1=t1, chunks=chunks)


# Public API: Load weather data from Zarr stores and return a WeatherProvider
def get_weather_from_zarr(
    zp: ZarrPaths,
    *,
    t0: Optional[str] = None,
    t1: Optional[str] = None,
    chunks: Optional[Mapping[str, int]] = None,
) -> WeatherProvider:
    """
    Load meteorological, radiative, and wind data from Zarr stores and return a WeatherProvider.
    Optionally slice by time and rechunk.
    """
    met = _open_metdataset_from_zarr(zp.met_store, t0=t0, t1=t1, chunks=chunks)
    rad = _open_metdataset_from_zarr(zp.rad_store, t0=t0, t1=t1, chunks=chunks)
    wind = _open_wind_metdataset(zp.wind_store, met, t0=t0, t1=t1, chunks=chunks)
    return WeatherProvider(met=met, rad=rad, wind=wind)
