import os
import pytest
from pathlib import Path
from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr
from pyneats.steps.weather.weather_provider import WeatherProvider
from datetime import datetime, timedelta


@pytest.fixture
def weather() -> WeatherProvider:
    weather_path = os.environ.get("TEST_MET_CACHE_DIR", "./tests/data")
    weather_path = Path(weather_path)

    if not weather_path.is_dir():
        raise RuntimeError(
            f"Test weather path directory does not exist: {weather_path}"
        )

    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"  # may not exist

    if not met_store.is_dir():
        raise RuntimeError(f"MET weather path directory does not exist: {met_store}")

    if not rad_store.is_dir():
        raise RuntimeError(f"RAD weather path directory does not exist: {rad_store}")

    if not wind_store.is_dir():
        wind_store = None

    asof = datetime.strptime("2025-07-09 00:00:00", "%Y-%m-%d %H:%M:%S")
    t0 = asof.strftime("%Y-%m-%d %H:%M:%S")
    t1 = (asof + timedelta(hours=36)).strftime("%Y-%m-%d %H:%M:%S")

    # Create ZarrPath
    zp = ZarrPaths(str(met_store), str(rad_store), str(wind_store))

    return get_weather_from_zarr(
        zp,
        t0=t0,
        t1=t1,
        chunks={"time": 1, "level": 10, "latitude": 256, "longitude": 256},
    )
