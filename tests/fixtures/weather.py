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
    if weather_path is None or not weather_path.is_dir():
        _log.warning(f"weather_path does not exist: {weather_path}. Some tests may be skipped")
        return None
        
    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"  # may not exist

    if not met_store.is_dir():
        _log.warning(f"met_store does not exist: {met_store}. Some tests may be skipped")
        return None

    if not rad_store.is_dir():
        _log.warning(f"rad_store does not exist: {rad_store}. Some tests may be skipped")
        return None

    if not wind_store.is_dir():
        _log.warning(f"wind_store does not exist: {wind_store}. Some tests may be skipped")
        wind_store = None # optional

    return get_weather_from_zarr(ZarrPaths(met_store, rad_store, wind_store))
