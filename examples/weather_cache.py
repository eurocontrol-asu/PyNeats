import os
from datetime import datetime

from pyneats.steps.weather.weather_factory import (
    DWDFactory,
    DWDZarrCacheSpec,
    WeatherCacheConfig,
    WeatherFactoryParams,
)

WEATHER_PATH = "/path/to/DWD/files"
ZARR_PATH = "/path/to/zarr/files"
ASOFDATE = datetime(2025, 7, 9, 0, 0, 0)
TIME_OF_DAY = 0

met_store = os.path.join(ZARR_PATH, "met_cache", "icon_met.zarr")
rad_store = os.path.join(ZARR_PATH, "met_cache", "icon_rad.zarr")
wind_store = os.path.join(ZARR_PATH, "met_cache", "icon_wind.zarr")  # optional


zspec = DWDZarrCacheSpec(
    met_store=met_store,
    rad_store=rad_store,
    wind_store=wind_store,  # set None to skip wind
    build_if_missing=True,
    met_chunks={"time": 1, "level": 10, "latitude": 256, "longitude": 256},  # on-disk chunks
    rad_chunks={"time": 1, "level": 1, "latitude": 256, "longitude": 256},  # on-disk chunks
    sdr_accumulate_dt_s=None,
)
params = WeatherFactoryParams(data_dir=WEATHER_PATH, cache=WeatherCacheConfig(zarr=zspec))
factory = DWDFactory(params)

# ⛏️ This writes the Zarrs (met/rad; see wind note below)
factory.build_cache(ASOFDATE, hour=TIME_OF_DAY, overwrite=False)
