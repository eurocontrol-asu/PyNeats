# ruff: noqa: F401
import pytest
from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr
from pyneats.steps.weather.weather_provider import WeatherProvider
from datetime import datetime, timedelta
import logging


_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)


@pytest.fixture
def weather(weather_path) -> WeatherProvider | None:  # noqa: F811
    if not weather_path.is_dir():
        _log.warning("weather_path does not exist: {weather_path}. Some tests may be skipped")

    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"  # may not exist

    if not met_store.is_dir():
        _log.warning("met_store does not exist: {weather_path}. Some tests may be skipped")
        return None

    if not rad_store.is_dir():
        _log.warning("rad_store does not exist: {weather_path}. Some tests may be skipped")
        return None

    if not wind_store.is_dir():
        _log.warning("wind_store does not exist: {weather_path}. Some tests may be skipped")
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
