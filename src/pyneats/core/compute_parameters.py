
"""
Default computation parameters for NEATS pipeline modules.

This module defines constants and default chunking strategies for weather and radiative data,
as well as parallelization and Zarr caching strategies.

Attributes
----------
DEFAULT_NJOBS : int
    Default number of jobs for parallel processing.
DEFAULT_BATCH_SIZE : int
    Default batch size for processing.
DEFAULT_JOBLIB_PREFERENCE : str
    Default joblib backend preference.
DEFAULT_WEATHER_OFFSET_H : int
    Default weather offset in hours.
DEFAULT_HORIZONTAL_RES_DEG : float
    Default horizontal resolution in degrees.
DEFAULT_SDR_ACCUMULATE_DT_S : int
    Default SDR accumulation time in seconds.
DEFAULT_MET_CHUNKS : Mapping[str, Any]
    Default chunk sizes for meteorological data.
DEFAULT_RAD_CHUNKS : Mapping[str, Any]
    Default chunk sizes for radiative data.
DEFAULT_WIND_CHUNKS : Mapping[str, Any]
    Default chunk sizes for wind data.
DEFAULT_ZARR_CACHING_STRATEGY : Literal
    Default Zarr caching strategy.
"""

from collections.abc import Mapping
from typing import Any, Final, Literal

__all__ = ["DEFAULT_NJOBS", "DEFAULT_BATCH_SIZE", "DEFAULT_JOBLIB_PREFERENCE"]

DEFAULT_NJOBS: Final[int] = -1
DEFAULT_BATCH_SIZE: Final[int] = 16
DEFAULT_JOBLIB_PREFERENCE: Final[str] = "processes"

DEFAULT_WEATHER_OFFSET_H: Final[int] = 36

DEFAULT_HORIZONTAL_RES_DEG: Final[float] = 0.25
DEFAULT_SDR_ACCUMULATE_DT_S: Final[int] = 3600  # 1 hour


# Default chunk dimensions for xarray operations using zarr backend

DEFAULT_MET_CHUNKS: Final[Mapping[str, Any]] = {
    "time": 1,
    "level": 10,
    "latitude": 256,
    "longitude": 256,
}

DEFAULT_RAD_CHUNKS: Final[Mapping[str, Any]] = {
    "time": 1,
    "level": 1,
    "latitude": 256,
    "longitude": 256,
}

DEFAULT_WIND_CHUNKS: Final[Mapping[str, Any]] = {
    "time": 1,
    "level": 10,
    "latitude": 256,
    "longitude": 256,
}

# Zarr Chunking
ZARR_CACHING_STRATEGY = Literal["all_variables", "by_variable"]
DEFAULT_ZARR_CACHING_STRATEGY: Final[ZARR_CACHING_STRATEGY] = "all_variables"

