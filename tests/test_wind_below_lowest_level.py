"""Wind below the lowest level of the wind data (``wind_below_lowest_level``).

Synthetic weather: the wind data has levels 600, 700 and 843.1 hPa (as the DWD
ICON wind store) from 01:00 to 03:00. The wind is uniform in longitude, latitude
and time, and differs per level, so the expected values are exact.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from dacite.exceptions import WrongTypeError
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.physics import units

from pyneats.core.neats_default_parameters import DEFAULT_WIND_BELOW_LOWEST_LEVEL
from pyneats.steps.weather.weather_provider import WeatherProvider
from pyneats.steps.weather.weather_provider import WeatherProviderParams


LONGITUDES = np.arange(-5.0, 5.01, 1.0)
LATITUDES = np.arange(40.0, 50.01, 1.0)
TIMES = pd.date_range("2025-07-09T01:00", "2025-07-09T03:00", freq="1h").to_numpy()
WIND_LEVELS = np.array([600.0, 700.0, 843.1])
MET_LEVELS = np.array([200.0, 300.0, 400.0, 600.0, 700.0, 843.1])
LOWEST = 843.1
# (eastward, northward) wind per wind level [m/s]
WIND_BY_LEVEL = {600.0: (20.0, -6.0), 700.0: (14.0, -4.0), 843.1: (8.0, -2.0)}

# Altitudes [m]: above the lowest level, at it, then below it down to the ground
ALTITUDES = np.array([3500.0, units.pl_to_m(LOWEST), 1000.0, 300.0, 0.0])


def _dataset(variables: dict[str, np.ndarray], levels: np.ndarray) -> MetDataset:
    dims = ("longitude", "latitude", "level", "time")
    shape = (LONGITUDES.size, LATITUDES.size, levels.size, TIMES.size)
    data_vars = {
        name: (dims, np.broadcast_to(per_level[None, None, :, None], shape).copy())
        for name, per_level in variables.items()
    }
    coords = {
        "longitude": LONGITUDES,
        "latitude": LATITUDES,
        "level": levels,
        "time": TIMES,
    }
    return MetDataset(xr.Dataset(data_vars, coords=coords))


@pytest.fixture
def weather() -> dict[str, MetDataset]:
    wind = _dataset(
        {
            "eastward_wind": np.array([WIND_BY_LEVEL[lv][0] for lv in WIND_LEVELS]),
            "northward_wind": np.array([WIND_BY_LEVEL[lv][1] for lv in WIND_LEVELS]),
        },
        WIND_LEVELS,
    )
    met = _dataset(
        {
            "air_temperature": np.full(MET_LEVELS.size, 250.0),
            "specific_humidity": np.full(MET_LEVELS.size, 1e-3),
        },
        MET_LEVELS,
    )
    rad = _dataset({"top_net_thermal_radiation": np.array([-240.0])}, np.array([-1.0]))
    return {"met": met, "rad": rad, "wind": wind}


def _flight(flight_id: str, start: str, altitudes: np.ndarray = ALTITUDES) -> Flight:
    n = altitudes.size
    return Flight(
        data={
            "longitude": np.linspace(-1.0, 1.0, n),
            "latitude": np.full(n, 45.0),
            "altitude": altitudes,
            "time": pd.date_range(start, periods=n, freq="5min"),
        },
        attrs={
            "flight_id": flight_id,
            "aircraft_type": "A320",
            "departure_airport": "LEMD",
            "arrival_airport": "LEBL",
            "model_type": "BADA4",
            "aobt": start,
        },
    )


def _provider(weather: dict[str, MetDataset], mode: str | None) -> WeatherProvider:
    kwargs = {} if mode is None else {"wind_below_lowest_level": mode}
    return WeatherProvider(
        met=weather["met"],
        rad=weather["rad"],
        wind=weather["wind"],
        params=WeatherProviderParams(humidity_scaling=None, **kwargs),
    )


def _winds(provider: WeatherProvider, flight: Flight) -> tuple[np.ndarray, np.ndarray]:
    out = provider.run(flight)
    return np.asarray(out["u_wind"]), np.asarray(out["v_wind"])


def _expected(mode: str) -> tuple[np.ndarray, np.ndarray]:
    u_low, v_low = WIND_BY_LEVEL[LOWEST]
    # At or above the lowest level: interpolated between the levels
    level = units.m_to_pl(ALTITUDES)
    u = np.interp(level, WIND_LEVELS, [WIND_BY_LEVEL[lv][0] for lv in WIND_LEVELS])
    v = np.interp(level, WIND_LEVELS, [WIND_BY_LEVEL[lv][1] for lv in WIND_LEVELS])
    below = level > LOWEST
    factor = {
        "zero": np.zeros(below.sum()),
        "constant": np.ones(below.sum()),
        "linear": ALTITUDES[below] / units.pl_to_m(LOWEST),
    }[mode]
    u[below] = u_low * factor
    v[below] = v_low * factor
    return u, v


def test_default_is_zero() -> None:
    assert DEFAULT_WIND_BELOW_LOWEST_LEVEL == "zero"
    assert WeatherProviderParams().wind_below_lowest_level == "zero"


@pytest.mark.parametrize("mode", ["zero", "constant", "linear"])
def test_flight_wind_below_lowest_level(
    weather: dict[str, MetDataset], mode: str
) -> None:
    u, v = _winds(_provider(weather, mode), _flight("F1", "2025-07-09T01:30"))
    u_exp, v_exp = _expected(mode)
    np.testing.assert_allclose(u, u_exp, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(v, v_exp, rtol=1e-5, atol=1e-6)


def test_default_matches_zero(weather: dict[str, MetDataset]) -> None:
    flight = _flight("F1", "2025-07-09T01:30")
    u_def, v_def = _winds(_provider(weather, None), flight)
    u_zero, v_zero = _winds(_provider(weather, "zero"), flight)
    np.testing.assert_array_equal(u_def, u_zero)
    np.testing.assert_array_equal(v_def, v_zero)


@pytest.mark.parametrize("mode", ["constant", "linear"])
def test_level_is_held_never_time(weather: dict[str, MetDataset], mode: str) -> None:
    # Starts at 00:40: the first points are before the wind data (01:00).
    flight = _flight("F1", "2025-07-09T00:40")
    u, v = _winds(_provider(weather, mode), flight)
    before = pd.to_datetime(flight["time"]) < pd.Timestamp(TIMES[0])
    assert before.sum() == 4
    np.testing.assert_array_equal(u[before], 0.0)
    np.testing.assert_array_equal(v[before], 0.0)
    # The point at 01:00 is at 0 m: "constant" holds the wind, "linear" gives 0
    u_exp, _ = _expected(mode)
    np.testing.assert_allclose(u[~before], u_exp[~before], rtol=1e-5, atol=1e-6)


def _three_flights() -> list[Flight]:
    return [
        _flight("F1", "2025-07-09T01:30"),
        _flight("F2", "2025-07-09T00:50"),
        _flight("F3", "2025-07-09T02:00", altitudes=ALTITUDES[::-1].copy()),
    ]


@pytest.mark.parametrize("mode", ["zero", "constant", "linear"])
def test_fleet_equals_flight(weather: dict[str, MetDataset], mode: str) -> None:
    provider = _provider(weather, mode)
    # Flight path first: run_fleet rewrites flight_id in the attrs of its inputs
    solo = {f.attrs["flight_id"]: _winds(provider, f) for f in _three_flights()}
    fleet_out, errors = provider.run_fleet(_three_flights())
    assert errors == []
    assert len(fleet_out) == len(solo)
    for got in fleet_out:
        u, v = solo[got.attrs["flight_id"].split("_")[0]]  # composite id: "F1_LEBL_..."
        np.testing.assert_allclose(np.asarray(got["u_wind"]), u, rtol=1e-6, atol=1e-9)
        np.testing.assert_allclose(np.asarray(got["v_wind"]), v, rtol=1e-6, atol=1e-9)


def test_unknown_mode_is_rejected(weather: dict[str, MetDataset]) -> None:
    with pytest.raises(WrongTypeError, match="wind_below_lowest_level"):
        _provider(weather, "log")
