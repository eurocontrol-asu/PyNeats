"""A flight that cannot be converted from JSON fails alone.

``neats_json_to_flights`` keeps raising by default. With a ``failures`` list,
the flight is left out and recorded instead, and ``FleetRunner`` turns it
into a per-flight error record while the other flights go on.
"""

from __future__ import annotations

import copy
import gc
import json
import weakref
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from pyneats.core.views import FlightView
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.parsing.neats_io import FlightConversionFailure
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.weather.weather_store import ZarrPaths
from tests.conftest import assert_climate_payload_equal


GOLDEN_INPUT = Path(__file__).parent / "data" / "golden" / "fleet_5_flights_input.json"
GOLDEN_OUTPUT = (
    Path(__file__).parent / "data" / "golden" / "fleet_5_flights_output.json"
)


def _golden_flights() -> list[dict[str, Any]]:
    with GOLDEN_INPUT.open(encoding="utf-8") as fh:
        flights: list[dict[str, Any]] = json.load(fh)
    return flights


def _with_bad_ts(flight: dict[str, Any], flight_id: str) -> dict[str, Any]:
    """Copy of ``flight`` renamed ``flight_id``, with one invalid ``ts``."""
    bad = copy.deepcopy(flight)
    fi = bad["flight_information"]
    fi["flight_identification"] = flight_id
    fi["trajectory"]["trajectory_data"][3]["ts"] = "garbage"
    return bad


# ---------------------------------------------------------------------------
# neats_json_to_flights
# ---------------------------------------------------------------------------


def test_default_still_raises() -> None:
    good = _golden_flights()[0]
    with pytest.raises(ValueError, match="flight 'BADTS', trajectory point 3"):
        neats_json_to_flights([good, _with_bad_ts(good, "BADTS")])


def test_failures_list_isolates_the_bad_flight() -> None:
    flights = _golden_flights()
    failures: list[FlightConversionFailure] = []
    out = neats_json_to_flights(
        [flights[0], _with_bad_ts(flights[0], "BADTS"), flights[1]],
        failures=failures,
    )
    assert [df.attrs["flight_id"] for df in out] == [
        flights[0]["flight_information"]["flight_identification"],
        flights[1]["flight_information"]["flight_identification"],
    ]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.index == 1
    assert failure.attrs["flight_id"] == "BADTS"
    assert failure.attrs["aircraft_type"] == "A320"
    assert isinstance(failure.error, ValueError)
    assert "trajectory point 3" in str(failure.error)
    # No traceback is kept anywhere in the chain, so the record does not
    # keep the input alive.
    assert failure.error.__traceback__ is None
    assert failure.error.__cause__ is not None
    assert failure.error.__cause__.__traceback__ is None


def test_failure_does_not_keep_the_input_alive() -> None:
    """With cyclic garbage collection off, the input is freed on return."""

    class Flights(list):  # list subclass so it can be weak-referenced
        pass

    good = _golden_flights()[0]
    flights = Flights([good, _with_bad_ts(good, "BADTS")])
    ref = weakref.ref(flights)
    failures: list[FlightConversionFailure] = []
    gc.disable()
    try:
        neats_json_to_flights(flights, failures=failures)
        del flights
        assert ref() is None
    finally:
        gc.enable()
    assert len(failures) == 1


@pytest.mark.parametrize(
    "not_a_sequence",
    [{"flight_information": {}}, {"flights": []}, "a string", b"bytes"],
)
def test_non_sequence_input_is_a_file_error(not_a_sequence: Any) -> None:
    """A whole-file shape error raises; it is not recorded as flight failures."""
    failures: list[FlightConversionFailure] = []
    with pytest.raises(TypeError, match="expected a sequence of flight objects"):
        neats_json_to_flights(not_a_sequence, failures=failures)
    assert failures == []


@pytest.mark.parametrize(
    "malformed",
    [
        {"flight_information": {"trajectory": [{"lat": 1.0}]}},  # list, not mapping
        {"flight_information": "not a mapping"},
        "not a flight object",
    ],
)
def test_malformed_flight_is_recorded_not_raised(malformed: Any) -> None:
    good = _golden_flights()[0]
    failures: list[FlightConversionFailure] = []
    out = neats_json_to_flights([malformed, good], failures=failures)
    assert len(out) == 1
    assert [f.index for f in failures] == [0]
    assert "flight_id" not in failures[0].attrs


def test_failures_list_gives_identical_output_for_valid_flights() -> None:
    flights = _golden_flights()
    failures: list[FlightConversionFailure] = []
    with_list = neats_json_to_flights(flights, failures=failures)
    default = neats_json_to_flights(flights)
    assert failures == []
    assert len(with_list) == len(default)
    for a, b in zip(with_list, default, strict=True):
        pd.testing.assert_frame_equal(a, b, check_exact=True)
        assert a.attrs == b.attrs


# ---------------------------------------------------------------------------
# FleetRunner loading stage (no BADA or weather needed)
# ---------------------------------------------------------------------------


def _runner_for(
    flights: list[dict[str, Any]], tmp_path: Path
) -> FleetRunnerLargeEmitter:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(flights), encoding="utf-8")
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(path),
        zarr_paths=ZarrPaths(tmp_path / "met.zarr", tmp_path / "rad.zarr", None),
        bada_path=str(tmp_path),
        params={},
    )
    return FleetRunnerLargeEmitter(cfg)


def test_runner_records_the_bad_flight_and_keeps_the_others(tmp_path: Path) -> None:
    flights = _golden_flights()
    runner = _runner_for([flights[0], _with_bad_ts(flights[0], "BADTS")], tmp_path)
    runner._load_trajectories()

    assert runner.source_fleet is not None
    assert len(runner.source_fleet) == 1
    assert not runner._pipeline_aborted
    (record,) = runner.error_records
    assert record["flight_information"]["flight_id"] == "BADTS"
    assert (
        record["flight_information"]["departure_airport"]
        == (flights[0]["flight_information"]["departure_airport"])
    )
    assert record["error"].startswith("Failed at parsing: ValueError(")
    assert "trajectory point 3" in record["error"]


def test_runner_aborts_when_every_flight_fails(tmp_path: Path) -> None:
    flight = _golden_flights()[0]
    runner = _runner_for(
        [_with_bad_ts(flight, "BAD1"), _with_bad_ts(flight, "BAD2")], tmp_path
    )
    # The weather paths do not exist: eval() must stop before loading them
    # and return the error records instead of raising.
    runner.eval()

    assert runner._pipeline_aborted
    assert runner.met is None
    assert runner.results is not None
    assert [
        r["flight_information"]["flight_id"] for r in runner.results["flight_results"]
    ] == ["BAD1", "BAD2"]


def test_runner_rejects_a_json_file_that_is_not_an_array(tmp_path: Path) -> None:
    runner = _runner_for([], tmp_path)
    (tmp_path / "input.json").write_text(
        json.dumps(_golden_flights()[0]), encoding="utf-8"
    )
    with pytest.raises(TypeError, match="expected a sequence of flight objects"):
        runner._load_trajectories()
    assert runner.error_records == []


def test_runner_names_a_flight_without_id_by_position(tmp_path: Path) -> None:
    good = _golden_flights()[0]
    runner = _runner_for([good, "not a flight object"], tmp_path)  # type: ignore[list-item]
    runner._load_trajectories()

    (record,) = runner.error_records
    assert record["flight_information"]["flight_id"] == "input_flight_1"


# ---------------------------------------------------------------------------
# End to end on the golden flights (needs BADA and weather)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_golden_fleet_with_one_bad_flight(
    weather: Any, weather_path: Path | None, bada_path: Path | None, tmp_path: Path
) -> None:
    """The five golden flights give their golden results; the added bad
    flight gives one error record and does not stop the run."""
    if weather is None or weather_path is None:
        pytest.skip("Weather data not available")
    if bada_path is None or not bada_path.exists():
        pytest.skip("BADA data not available")

    flights = _golden_flights()
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(flights[:2] + [_with_bad_ts(flights[0], "BADTS")] + flights[2:]),
        encoding="utf-8",
    )
    wind = weather_path / "icon_wind.zarr"
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(path),
        zarr_paths=ZarrPaths(
            weather_path / "icon_met.zarr",
            weather_path / "icon_rad.zarr",
            wind if wind.is_dir() else None,
        ),
        bada_path=str(bada_path),
        params={},
    )
    runner = FleetRunnerLargeEmitter(cfg)
    runner.eval()

    assert runner.fleet_with_climate_impact is not None
    with GOLDEN_OUTPUT.open(encoding="utf-8") as fh:
        golden = [FlightView.from_dict(d) for d in json.load(fh)]
    assert len(runner.fleet_with_climate_impact) == len(golden)
    for flight, expected in zip(runner.fleet_with_climate_impact, golden, strict=True):
        assert_climate_payload_equal(
            flight.attrs["climate_impact"],
            expected.attrs["climate_impact"],
            rtol=1e-3,
        )

    (record,) = runner.error_records
    assert record["flight_information"]["flight_id"] == "BADTS"
    assert record["error"].startswith("Failed at parsing:")
    assert runner.results is not None
    assert record in runner.results["flight_results"]
