"""Tests for FleetRunnerPerformanceOnly._extract_results().

We bypass __init__ (which needs full BADA/Zarr infrastructure) and test the
result-extraction logic directly by pre-populating the runner's internal state.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pandas as pd
import pytest

from pyneats.runners.performance_runner import FleetRunnerPerformanceOnly
from pyneats.runners.performance_runner import _to_list_or_null


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runner(**overrides) -> FleetRunnerPerformanceOnly:
    """Return a runner instance with __init__ bypassed."""
    runner = object.__new__(FleetRunnerPerformanceOnly)
    runner._pipeline_aborted = False
    runner.fleet_with_performance = None
    runner.error_records = []
    runner.results = None
    for k, v in overrides.items():
        setattr(runner, k, v)
    return runner


def _make_perf_flight(
    flight_id: str = "FL001",
    departure_airport: str = "EGLL",
    arrival_airport: str = "LFPG",
    aobt: str = "2025-01-01 10:00:00",
    aircraft_type: str = "A320",
    engine_uid: str | None = None,
    fuel_flow: list[float | None] | None = None,
    aircraft_mass: list[float] | None = None,
    true_airspeed: list[float] | None = None,
    timestamps: list[str] | None = None,
) -> MagicMock:
    """Return a mock FlightWithPerformance with .attrs and .dataframe."""
    attrs = {
        "flight_id": flight_id,
        "departure_airport": departure_airport,
        "arrival_airport": arrival_airport,
        "aobt": aobt,
        "aircraft_type": aircraft_type,
    }
    if engine_uid is not None:
        attrs["engine_uid"] = engine_uid

    n = len(fuel_flow or [1.0])
    ts_raw = timestamps or [f"2025-01-01T10:0{i}:00+00:00" for i in range(n)]

    # Build a real DataFrame so _to_list_or_null works naturally
    data: dict = {}

    # timestamps as Timestamp objects (mimics pycontrails Flight.dataframe)
    time_col = pd.to_datetime(ts_raw, utc=True)

    data["time"] = time_col
    if fuel_flow is not None:
        data["fuel_flow"] = fuel_flow
    if aircraft_mass is not None:
        data["aircraft_mass"] = aircraft_mass
    if true_airspeed is not None:
        data["true_airspeed"] = true_airspeed

    df = pd.DataFrame(data)

    mock_flight = MagicMock()
    mock_flight.attrs = attrs
    mock_flight.dataframe = df
    return mock_flight


# ---------------------------------------------------------------------------
# _to_list_or_null helper
# ---------------------------------------------------------------------------


def test_to_list_or_null_normal():
    assert _to_list_or_null([1.0, 2.5, 3.0]) == [1.0, 2.5, 3.0]


def test_to_list_or_null_nan_becomes_null():
    result = _to_list_or_null([1.0, float("nan"), 3.0])
    assert result[0] == 1.0
    assert result[1] is None
    assert result[2] == 3.0


def test_to_list_or_null_none_becomes_null():
    result = _to_list_or_null([1.0, None, 3.0])
    assert result[1] is None


# ---------------------------------------------------------------------------
# _extract_results — aborted pipeline
# ---------------------------------------------------------------------------


def test_extract_results_pipeline_aborted():
    error_record = {"flight_information": {"flight_id": "FL999"}, "error": "oops"}
    runner = _make_runner(
        _pipeline_aborted=True,
        error_records=[error_record],
    )

    with (
        patch(
            "pyneats.runners.performance_runner.FleetReport.collect", return_value={}
        ),
        patch("pyneats.runners.performance_runner.clear_dataset_cache"),
    ):
        runner._extract_results()

    assert runner.results is not None
    assert runner.results["flight_results"] == [error_record]


# ---------------------------------------------------------------------------
# _extract_results — normal case, single flight
# ---------------------------------------------------------------------------


def test_extract_results_single_flight():
    flight = _make_perf_flight(
        flight_id="FL001",
        departure_airport="EGLL",
        arrival_airport="LFPG",
        aircraft_type="A320",
        fuel_flow=[1.1, 1.2, 1.3],
        aircraft_mass=[70000.0, 69950.0, 69900.0],
        true_airspeed=[240.0, 242.0, 244.0],
    )
    runner = _make_runner(fleet_with_performance=[flight])

    with (
        patch(
            "pyneats.runners.performance_runner.FleetReport.collect", return_value={}
        ),
        patch("pyneats.runners.performance_runner.clear_dataset_cache"),
    ):
        runner._extract_results()

    assert runner.results is not None
    results = runner.results["flight_results"]
    assert len(results) == 1

    rec = results[0]
    fi = rec["flight_information"]
    assert fi["flight_id"] == "FL001"
    assert fi["departure_airport"] == "EGLL"
    assert fi["arrival_airport"] == "LFPG"
    assert fi["aircraft_type"] == "A320"

    perf = rec["performance"]
    assert perf["fuel_flow"] == [1.1, 1.2, 1.3]
    assert perf["aircraft_mass"] == [70000.0, 69950.0, 69900.0]
    assert perf["true_airspeed"] == [240.0, 242.0, 244.0]
    assert len(perf["timestamps"]) == 3


def test_extract_results_engine_uid_in_output():
    """engine_uid from attrs must appear in flight_information."""
    flight = _make_perf_flight(
        flight_id="FL002",
        engine_uid="CFM56-5B4",
        fuel_flow=[1.0],
        aircraft_mass=[70000.0],
        true_airspeed=[240.0],
    )
    runner = _make_runner(fleet_with_performance=[flight])

    with (
        patch(
            "pyneats.runners.performance_runner.FleetReport.collect", return_value={}
        ),
        patch("pyneats.runners.performance_runner.clear_dataset_cache"),
    ):
        runner._extract_results()

    fi = runner.results["flight_results"][0]["flight_information"]
    assert fi["engine_uid"] == "CFM56-5B4"


def test_extract_results_nan_fuel_flow_serialised_as_null():
    """NaN values in fuel_flow must become None in the output."""
    flight = _make_perf_flight(
        fuel_flow=[1.0, float("nan"), 1.2],
        aircraft_mass=[70000.0, 69975.0, 69950.0],
        true_airspeed=[240.0, 241.0, 242.0],
    )
    runner = _make_runner(fleet_with_performance=[flight])

    with (
        patch(
            "pyneats.runners.performance_runner.FleetReport.collect", return_value={}
        ),
        patch("pyneats.runners.performance_runner.clear_dataset_cache"),
    ):
        runner._extract_results()

    ff = runner.results["flight_results"][0]["performance"]["fuel_flow"]
    assert ff[0] == 1.0
    assert ff[1] is None
    assert ff[2] == pytest.approx(1.2)


def test_extract_results_missing_column_omitted():
    """A column absent from the dataframe is simply not included in output."""
    flight = _make_perf_flight(
        fuel_flow=[1.0],
        # aircraft_mass and true_airspeed not passed → not in df
    )
    runner = _make_runner(fleet_with_performance=[flight])

    with (
        patch(
            "pyneats.runners.performance_runner.FleetReport.collect", return_value={}
        ),
        patch("pyneats.runners.performance_runner.clear_dataset_cache"),
    ):
        runner._extract_results()

    perf = runner.results["flight_results"][0]["performance"]
    assert "fuel_flow" in perf
    assert "aircraft_mass" not in perf
    assert "true_airspeed" not in perf


def test_extract_results_error_records_appended():
    """Error records from failed flights appear alongside successful ones."""
    good_flight = _make_perf_flight(
        flight_id="FL001",
        fuel_flow=[1.0],
        aircraft_mass=[70000.0],
        true_airspeed=[240.0],
    )
    error_record = {
        "flight_information": {"flight_id": "FL_BAD"},
        "error": "perf failed",
    }
    runner = _make_runner(
        fleet_with_performance=[good_flight],
        error_records=[error_record],
    )

    with (
        patch(
            "pyneats.runners.performance_runner.FleetReport.collect", return_value={}
        ),
        patch("pyneats.runners.performance_runner.clear_dataset_cache"),
    ):
        runner._extract_results()

    results = runner.results["flight_results"]
    assert len(results) == 2
    ids = {r.get("flight_information", {}).get("flight_id") for r in results}
    assert "FL001" in ids
    assert "FL_BAD" in ids


# ---------------------------------------------------------------------------
# Class-level: no-op overrides do not raise
# ---------------------------------------------------------------------------


def test_noop_steps_return_self():
    runner = _make_runner()
    assert runner._emissions() is runner
    assert runner._climate_impact() is runner
    assert runner._climate_metrics() is runner
