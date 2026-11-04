"""The "accf" (CLIMaCCF) non-CO2 backend works for every flight of a fleet.

ACCF-WX, two bugs:

1. ``ACCFModel`` built one pycontrails ``ACCF`` in ``_post_init`` and called
   its ``eval`` for every flight. ``ACCF.eval`` replaces ``self.met`` and
   ``self.surface`` with copies cut to the evaluated flight, and
   ``FleetRunner`` keeps one step per process for all flights, so the
   second flight had only the weather of the first one. In a real 5-flight
   fleet, flights 2-5 failed with an IndexError in CLIMaCCF.
2. ``FleetRunner`` did not give the step its met / surface datasets, so with
   ``non_co2_model="accf"`` every flight failed ("ACCF requires both 'met'
   and 'surface'") unless the caller put them in ``params``.

The fake ``ACCF`` below does what pycontrails 0.60.2 ``ACCF.eval`` does with
the weather (cut ``met`` / ``surface`` to the flight and keep the cut copies),
so these tests run in CI without the ``climaccf`` package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pycontrails import Flight
from pycontrails.core.met import MetDataset

from pyneats.runners import FleetRunnerLargeEmitter
from pyneats.runners import FleetRunnerParams
from pyneats.runners import fleet
from pyneats.steps.climate_functions import climaccf
from pyneats.steps.climate_functions.climaccf import ACCFModel
from pyneats.steps.weather.weather_store import ZarrPaths


GOLDEN_INPUT = Path(__file__).parent / "data" / "golden" / "fleet_5_flights_input.json"

LONGITUDES = np.arange(-10.0, 10.5, 0.5)  # 41 points
LATITUDES = np.arange(40.0, 50.5, 0.5)
LEVELS = np.array([200.0, 250.0, 300.0])
TIMES = pd.date_range("2025-07-09T00:00", periods=4, freq="1h")

MET_VARS = {
    "air_temperature": (220.0, "K"),
    "specific_humidity": (1e-4, "kg kg**-1"),
    "potential_vorticity": (2e-6, "K m**2 kg**-1 s**-1"),
    "geopotential": (1e5, "m**2 s**-2"),
    "relative_humidity": (0.5, "1"),
    "northward_wind": (1.0, "m s**-1"),
    "eastward_wind": (10.0, "m s**-1"),
}
# Names and units of the PyNEATS rad store (DWD/ICON cache)
RAD_VARS = {
    "surface_solar_downward_radiation": (3.6e6, "J m**-2"),
    "toa_outgoing_longwave_flux": (240.0, "W m**-2"),
}


def _met_dataset(
    variables: dict[str, tuple[float, str]], levels: np.ndarray
) -> MetDataset:
    shape = (LONGITUDES.size, LATITUDES.size, levels.size, TIMES.size)
    rng = np.random.default_rng(0)
    data_vars = {
        name: (
            ("longitude", "latitude", "level", "time"),
            value * (1.0 + 0.01 * rng.random(shape)),
            {"units": units},
        )
        for name, (value, units) in variables.items()
    }
    coords = {
        "longitude": LONGITUDES,
        "latitude": LATITUDES,
        "level": levels,
        "time": TIMES,
    }
    return MetDataset(xr.Dataset(data_vars, coords=coords))


@pytest.fixture
def met() -> MetDataset:
    return _met_dataset(MET_VARS, LEVELS)


@pytest.fixture
def rad() -> MetDataset:
    return _met_dataset(RAD_VARS, np.array([-1.0]))


def _flight(flight_id: str, lon0: float) -> Flight:
    n = 5
    return Flight(
        data={
            "longitude": np.linspace(lon0, lon0 + 1.0, n),
            "latitude": np.full(n, 45.0),
            "altitude": np.full(n, 10_500.0),
            "time": pd.date_range("2025-07-09T01:00", periods=n, freq="5min"),
            "fuel_burn": np.full(n, 100.0),
            "nox_ei": np.full(n, 0.015),
        },
        attrs={"flight_id": flight_id, "aircraft_type": "A320"},
    )


def _flights() -> list[Flight]:
    # Far apart: the weather cut to one flight does not cover the others.
    return [_flight("F1", -8.0), _flight("F2", 0.0), _flight("F3", 7.0)]


class FakeACCF:
    """Stand-in for pycontrails ``ACCF`` with the same weather handling."""

    seen: ClassVar[list[tuple[str, int, int]]] = []

    def __init__(
        self, met: MetDataset, surface: MetDataset | None = None, **params: Any
    ) -> None:
        self.met = met
        self.surface = surface

    def eval(self, source: Flight) -> Flight:
        assert self.surface is not None
        FakeACCF.seen.append(
            (
                source.attrs["flight_id"],
                self.met.data.sizes["longitude"],
                self.surface.data.sizes["longitude"],
            )
        )
        # pycontrails models.py downselect_met / accf.py eval
        self.met = source.downselect_met(self.met)
        self.surface = source.downselect_met(self.surface)
        out = source.copy()
        t = source.intersect_met(self.met["air_temperature"])
        for name in ("aCCF_CH4", "aCCF_O3", "aCCF_H2O"):
            out[name] = t * 1e-15
        return out


@pytest.fixture
def fake_accf(monkeypatch: pytest.MonkeyPatch) -> type[FakeACCF]:
    monkeypatch.setattr(FakeACCF, "seen", [])
    monkeypatch.setattr(climaccf, "ACCF", FakeACCF)
    # The fake output has no contrail columns; skip the output view check.
    monkeypatch.setattr(
        climaccf.FlightWithSegmentATR,
        "from_flight",
        classmethod(lambda cls, f: f),
    )
    return FakeACCF


def _assert_full_weather_for_every_flight(seen: list[tuple[str, int, int]]) -> None:
    assert [s[0] for s in seen] == ["F1", "F2", "F3"]
    for flight_id, n_met, n_surface in seen:
        assert (n_met, n_surface) == (LONGITUDES.size, LONGITUDES.size), (
            f"{flight_id}: ACCF got the weather cut to an earlier flight"
        )


def _atr(flight: Flight) -> list[float]:
    return [
        float(np.nansum(flight[c])) for c in ("ATR_20_CH4", "ATR_20_O3", "ATR_20_H2O")
    ]


# -----------------------------------------------------------------------------
# Bug 1: one step, several flights
# -----------------------------------------------------------------------------


def test_one_step_gives_each_flight_the_full_weather(
    fake_accf: type[FakeACCF], met: MetDataset, rad: MetDataset
) -> None:
    step = ACCFModel(met=met, surface=rad)
    fleet_atr = [_atr(step(f)) for f in _flights()]

    _assert_full_weather_for_every_flight(fake_accf.seen)
    solo_atr = [_atr(ACCFModel(met=met, surface=rad)(f)) for f in _flights()]
    assert fleet_atr == solo_atr


def test_step_does_not_change_the_given_weather(
    fake_accf: type[FakeACCF], met: MetDataset, rad: MetDataset
) -> None:
    step = ACCFModel(met=met, surface=rad)
    for f in _flights():
        step(f)
    assert step.params.met is met
    assert met.data.sizes["longitude"] == LONGITUDES.size
    assert rad.data.sizes["longitude"] == LONGITUDES.size


# -----------------------------------------------------------------------------
# Bug 2: FleetRunner gives met / surface to the step
# -----------------------------------------------------------------------------


class _FakeWeather:
    def __init__(self, met: Any, rad: Any) -> None:
        self._met, self._rad = met, rad

    def met(self) -> Any:
        return self._met

    def rad(self) -> Any:
        return self._rad

    def wind(self) -> None:
        return None


def _runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    met: Any,
    rad: Any,
    *,
    non_co2_model: str,
    params: dict[str, Any] | None = None,
    njobs: int = 1,
    prefer: str = "processes",
) -> FleetRunnerLargeEmitter:
    monkeypatch.setattr(fleet, "_STEP_CACHE", {})
    monkeypatch.setattr(
        fleet, "get_weather_from_zarr", lambda *a, **k: _FakeWeather(met, rad)
    )
    # Not under test, and they need more met variables.
    monkeypatch.setattr(fleet, "WeatherProvider", lambda **k: None)
    monkeypatch.setattr(fleet, "CoCiPModel", lambda **k: None)
    runner = FleetRunnerLargeEmitter(
        FleetRunnerParams(
            trajectory_json_filepath=str(GOLDEN_INPUT),
            zarr_paths=ZarrPaths(str(tmp_path / "met"), str(tmp_path / "rad")),
            non_co2_model=non_co2_model,
            params=params or {},
            njobs=njobs,
            prefer=prefer,
        )
    )
    runner._load_weather()
    return runner


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """build() records its params and returns a step echoing them."""
    calls: list[dict[str, Any]] = []

    def fake_build(interface: Any, name: str, **params: Any) -> Any:
        calls.append(params)
        return lambda x: params

    monkeypatch.setattr(fleet, "build", fake_build)
    return calls


def test_fleet_runner_gives_met_and_surface_to_accf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builds: list[dict[str, Any]]
) -> None:
    met, rad = object(), object()
    runner = _runner(tmp_path, monkeypatch, met, rad, non_co2_model="accf")
    params = runner.non_co2_model(None)
    assert params["met"] is met
    assert params["surface"] is rad


def test_fleet_runner_keeps_met_and_surface_given_in_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builds: list[dict[str, Any]]
) -> None:
    met, rad, own_met = object(), object(), object()
    runner = _runner(
        tmp_path,
        monkeypatch,
        met,
        rad,
        non_co2_model="accf",
        params={"non_co2_model": {"met": own_met}},
    )
    params = runner.non_co2_model(None)
    assert params["met"] is own_met
    assert params["surface"] is rad


def test_fleet_runner_gives_no_weather_to_local_accf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builds: list[dict[str, Any]]
) -> None:
    runner = _runner(
        tmp_path, monkeypatch, object(), object(), non_co2_model="local_accf"
    )
    params = runner.non_co2_model(None)
    assert "met" not in params
    assert "surface" not in params


@pytest.mark.parametrize("weather_in_params", [False, True], ids=["runner", "params"])
@pytest.mark.parametrize(
    ("njobs", "prefer"), [(1, "processes"), (2, "threads")], ids=["njobs1", "threads"]
)
def test_fleet_accf_step_runs_every_flight_on_full_weather(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_accf: type[FakeACCF],
    met: MetDataset,
    rad: MetDataset,
    njobs: int,
    prefer: str,
    weather_in_params: bool,
) -> None:
    # "runner": no met / surface in params, the runner must give them (bug 2).
    # "params": given by the caller, as before the fix (bug 1 only).
    params = (
        {"non_co2_model": {"met": met, "surface": rad}} if weather_in_params else {}
    )
    runner = _runner(
        tmp_path,
        monkeypatch,
        met,
        rad,
        non_co2_model="accf",
        params=params,
        njobs=njobs,
        prefer=prefer,
    )
    runner.fleet_with_contrails = _flights()  # type: ignore[assignment]
    runner._other_nonco2()

    assert runner.error_records == []
    assert runner.fleet_with_nonco2 is not None
    assert len(runner.fleet_with_nonco2) == 3
    assert sorted(s[0] for s in fake_accf.seen) == ["F1", "F2", "F3"]
    for _, n_met, n_surface in fake_accf.seen:
        assert (n_met, n_surface) == (LONGITUDES.size, LONGITUDES.size)


# -----------------------------------------------------------------------------
# Real pycontrails ACCF (no climaccf needed to build it)
# -----------------------------------------------------------------------------


def test_new_pycontrails_accf_per_flight_shares_and_keeps_the_weather(
    met: MetDataset, rad: MetDataset
) -> None:
    """A new ``ACCF`` per flight neither copies nor changes the given weather."""
    met_arrays = {k: v.values.copy() for k, v in met.data.items()}
    step = ACCFModel(met=met, surface=rad)
    surface = step._accf_surface
    surface_units = {k: v.attrs["units"] for k, v in surface.data.items()}
    surface_arrays = {k: v.values.copy() for k, v in surface.data.items()}

    impls = [step._new_impl() for _ in range(3)]

    for impl in impls:
        assert impl.met is not met
        for name, arr in met.data.items():
            # Same array: no copy of the met per flight
            assert np.shares_memory(impl.met.data[name].values, arr.values)
        # ACCF turns W m-2 into J m-2 (x 3600) on its own copy of the surface
        olr = impl.surface.data["top_net_thermal_radiation"]
        np.testing.assert_array_equal(
            olr.values, surface_arrays["top_net_thermal_radiation"] * 3600.0
        )
    for name, arr in met.data.items():
        np.testing.assert_array_equal(arr.values, met_arrays[name])
    assert {k: v.attrs["units"] for k, v in surface.data.items()} == surface_units
    for name, arr in surface.data.items():
        np.testing.assert_array_equal(arr.values, surface_arrays[name])


def test_relative_humidity_in_percent_is_divided_once_and_not_in_place(
    rad: MetDataset,
) -> None:
    """RH in "%" reaches every ``ACCF`` as a proportion, the given met unchanged.

    pycontrails ``ACCF.__init__`` divides RH in "%" by 100 in place, on an
    array it shares with the given (numpy-backed) met. Without care, each new
    ``ACCF`` per flight divided the given values by 100 again.
    """
    met = _met_dataset({**MET_VARS, "relative_humidity": (50.0, "%")}, LEVELS)
    rh_given = met.data["relative_humidity"].values.copy()
    step = ACCFModel(met=met, surface=rad)

    for _ in range(3):
        impl = step._new_impl()
        rh = impl.met.data["relative_humidity"]
        assert rh.attrs["units"] == "1"
        np.testing.assert_allclose(rh.values, rh_given / 100.0, rtol=0, atol=0)
    np.testing.assert_array_equal(met.data["relative_humidity"].values, rh_given)
    assert met.data["relative_humidity"].attrs["units"] == "%"
    # The other met variables are still shared, not copied
    assert np.shares_memory(
        impl.met.data["air_temperature"].values, met.data["air_temperature"].values
    )


# -----------------------------------------------------------------------------
# Real CLIMaCCF on the real weather
# -----------------------------------------------------------------------------


@pytest.mark.requires_weather
@pytest.mark.slow
@pytest.mark.skipif(
    importlib.util.find_spec("climaccf") is None,
    reason="climaccf is not installed (not a PyNEATS dependency)",
)
def test_real_climaccf_one_step_equals_one_step_per_flight(
    weather: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    if weather is None:
        pytest.skip("weather data not available")
    # The test flights carry no contrail columns; skip the output view check.
    monkeypatch.setattr(
        climaccf.FlightWithSegmentATR,
        "from_flight",
        classmethod(lambda cls, f: f),
    )
    met, rad = weather.met(), weather.rad()

    def real_flight(flight_id: str, lon0: float, lat0: float) -> Flight:
        n = 20
        return Flight(
            data={
                "longitude": np.linspace(lon0, lon0 + 4.0, n),
                "latitude": np.linspace(lat0, lat0 + 2.0, n),
                "altitude": np.full(n, 11_000.0),
                "time": pd.date_range("2025-07-10T10:00", periods=n, freq="3min"),
                "fuel_burn": np.full(n, 100.0),
                "nox_ei": np.full(n, 0.015),
            },
            attrs={"flight_id": flight_id, "aircraft_type": "A320"},
        )

    def flights() -> list[Flight]:
        return [
            real_flight("EU", 0.0, 45.0),
            real_flight("US", -90.0, 35.0),
            real_flight("AS", 100.0, 20.0),
        ]

    step = ACCFModel(met=met, surface=rad)
    fleet_atr = [_atr(step(f)) for f in flights()]
    solo_atr = [_atr(ACCFModel(met=met, surface=rad)(f)) for f in flights()]
    assert fleet_atr == solo_atr
    assert all(np.isfinite(v).all() and any(v) for v in map(np.array, fleet_atr))
