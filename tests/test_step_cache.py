"""The per-process step cache never hands a runner another runner's step.

Fleet steps are built lazily and cached per process. The cache was keyed by
(interface, name) only, so with njobs=1 (or threads, or a reused worker pool) a
second runner in the same process reused the first runner's steps, e.g. its
parser without the airport fuel file, or with it when the second had none.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from joblib.externals import cloudpickle

from pyneats.runners import FleetRunnerLargeEmitter
from pyneats.runners import FleetRunnerParams
from pyneats.runners import fleet
from pyneats.steps.parsing import TrajectoryParser
from pyneats.steps.weather.weather_store import ZarrPaths


GOLDEN_INPUT = Path(__file__).parent / "data" / "golden" / "fleet_5_flights_input.json"


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Empty cache; build() records its params and returns a step echoing them."""
    calls: list[dict[str, Any]] = []

    def fake_build(interface: Any, name: str, **params: Any) -> Any:
        calls.append(params)
        return lambda x: params

    monkeypatch.setattr(fleet, "_STEP_CACHE", {})
    monkeypatch.setattr(fleet, "build", fake_build)
    return calls


def test_each_callable_uses_its_own_params(builds: list[dict[str, Any]]) -> None:
    a = fleet.make_step_func(TrajectoryParser, "neats", {"p": 1})
    b = fleet.make_step_func(TrajectoryParser, "neats", {"p": 2})
    assert a(None) == {"p": 1}
    assert b(None) == {"p": 2}
    assert a(None) == {"p": 1}


def test_step_built_once_per_callable_and_process(builds: list[dict[str, Any]]) -> None:
    fn = fleet.make_step_func(TrajectoryParser, "neats", {"p": 1})
    # Workers receive a pickled copy of the callable for every batch: it must
    # reuse the step already built in that process, not build a new one.
    copy = cloudpickle.loads(cloudpickle.dumps(fn))
    for f in (fn, copy, fn, copy):
        f(None)
    assert len(builds) == 1


@pytest.mark.parametrize("first_with_file", [False, True])
def test_second_runner_in_same_process_uses_its_own_airport_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_with_file: bool
) -> None:
    monkeypatch.setattr(fleet, "_STEP_CACHE", {})
    airport_file = tmp_path / "airport_fuel.csv"
    airport_file.write_text("Airport;q_fuel\nLZIB;43500000\n", encoding="utf-8")
    zarr = ZarrPaths(str(tmp_path / "met"), str(tmp_path / "rad"))

    def q_fuel_lzib(with_file: bool) -> float:
        runner = FleetRunnerLargeEmitter(
            FleetRunnerParams(
                trajectory_json_filepath=str(GOLDEN_INPUT),
                zarr_paths=zarr,
                airport_fuel_path=str(airport_file) if with_file else None,
                njobs=1,
            )
        )
        runner._load_trajectories()
        runner._parse_flight()
        assert runner.parsed_fleet
        (flight,) = [
            f for f in runner.parsed_fleet if f.attrs["departure_airport"] == "LZIB"
        ]
        return float(flight.fuel.q_fuel)

    expected = {True: 43.5e6, False: 42.8e6}
    for with_file in (first_with_file, not first_with_file):
        assert q_fuel_lzib(with_file) == expected[with_file]
