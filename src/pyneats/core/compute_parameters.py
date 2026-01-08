from typing  import Final, Mapping, Any, Literal

__all__ = [
    "DEFAULT_NJOBS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_JOBLIB_PREFERENCE"
]

DEFAULT_NJOBS: Final[int] = -1
DEFAULT_BATCH_SIZE: Final[int] = 16
DEFAULT_JOBLIB_PREFERENCE: Final[str] = "processes"

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


# Default chunk dimensions for xarray operations using zarr backend

DEFAULT_MET_CHUNKS: Final[Mapping[str, Any]]  = {
    "time": 1,
    "level": 10,
    "latitude": 256,
    "longitude": 256,
}

DEFAULT_RAD_CHUNKS: Final[Mapping[str, Any]]  = {
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
DEFAULT_ZARR_CACHING_STRATEGY : Final[ZARR_CACHING_STRATEGY] = "by_variable"
