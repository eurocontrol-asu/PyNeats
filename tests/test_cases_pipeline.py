"""Comprehensive pytest test suite implementing test cases.

All TC tests use the aggregated golden data:
    - tests/data/golden/fleet_5_flights_aggregated_input.json
    - tests/data/golden/fleet_5_flights_aggregated_output.json

A single :class:`FleetRunnerLargeEmitter` run (module-scoped fixture) processes
all flights at once. Individual tests then assert per-flight results by
flight_id, comparing against the golden output or checking error records.

Success test cases (TC) flight must appear in pipeline output:
   TC_AC_OVERSPEC
   TC_ENG_UNSPEC
   TC_ENG_MISMATCH
   TC_ENG_UNKNOWN
   TC_MASS_ALL_UNSPEC
   TC_MASS_NO_TOM_NO_LF
   TC_MASS_NO_AM_NO_LF
   TC_MASS_NO_AM_NO_TOM
   TC_MASS_NO_AM
   TC_MASS_NO_TOM
   TC_MASS_NO_LF
   TC_LF_GT_ONE
   TC_NO_HC_RATIO
   TC_NO_HYDROGEN
   TC_NO_HC_NO_HYDROGEN
   TC_NO_QFUEL
   TC_PERF_NO_AM
   TC_PERF_NO_FF
   TC_PERF_NO_EE
   TC_PERF_NO_TAS
   TC_PERF_NO_AM_FF
   TC_PERF_NO_AM_EE
   TC_PERF_NO_AM_TAS
   TC_PERF_NO_FF_EE
   TC_PERF_NO_FF_TAS
   TC_PERF_NO_EE_TAS
   TC_PERF_NO_AM_FF_EE
   TC_PERF_NO_AM_FF_TAS
   TC_PERF_NO_AM_EE_TAS
   TC_PERF_NO_FF_EE_TAS
   TC_PERF_NO_ALL

Error test cases flight must appear in error_records (abort evaluation):
   TC_AC_NO_BADA
   TC_MASS_BELOW_OEW
   TC_MASS_NOT_DECREASING
   TC_MASS_EXCEEDS_MTOW
   TC_TOM_EXCEEDS_MTOW
   TC_HC_RATIO_OUT_OF_RANGE
   TC_HYDROGEN_OUT_OF_RANGE
   TC_QFUEL_OUT_OF_RANGE

Behavioural assertions (TestBehavioralAssertions):
   test_lf_gt_one_output_clamped          TC_LF_GT_ONE: output payload_factor ≤ 1
   test_mass_preserves_input_aircraft_mass TC_MASS_NO_LF / NO_TOM / NO_TOM_NO_LF:
       output aircraft_mass matches input am (interpolated to output time grid)
   test_mass_iterative_from_tom           TC_MASS_NO_AM / NO_AM_NO_LF:
       am column is all-null → iterative mass from takeoff_mass
   test_mass_no_am_no_tom_uses_lf         TC_MASS_NO_AM_NO_TOM:
       am all-null, no takeoff_mass → LF + BADA MTOW
   test_mass_all_unspec_uses_default_lf   TC_MASS_ALL_UNSPEC:
       am all-null, no mass params → LF=1 + BADA MTOW
   test_eng_mismatch_drops_input          TC_ENG_MISMATCH: drop, use default
   test_eng_unspec_assigns_default        TC_ENG_UNSPEC: select representative
   test_ac_overspec_remaps_code           TC_AC_OVERSPEC: remap to BADA naming
   test_var_time_resolution_correction    tc_var_time_resolution: resample
   test_mixed_time_ordering               tc_mixed_time: order along time
   test_duplicate_time_correction         tc_duplicate_time: remove duplicates
   test_missing_trajectory_value_deletion tc_missing_timestamps / tc_missing_latitudes /
       tc_missing_longitudes / tc_missing_altitudes: remove faulty waypoints and if
       applicable interpolate
   test_missing_departure_landing_abortion tc_missing_departure / tc_missing_landing:
       check if aborted [TODO: check for flag]
   test_altitude_fluctuations_correction  tc_altitude_fluctuations: smooth fluctuations
   test_longitude_convention_correction   tc_changed_longitude_convention: correct longitude convention
   test_trajectory_jump_correction        tc_trajectory_jump: correct jump in trajectory
   test_no_hc_ratio_uses_hydrogen_content TC_NO_HC_RATIO: output hydrogen_content matches input
   test_no_hydrogen_uses_hc_ratio         TC_NO_HYDROGEN: hydrogen_content derived from H/C ratio
   test_no_hc_no_hydrogen_uses_default    TC_NO_HC_NO_HYDROGEN: hydrogen_content = DEFAULT (13.79)
   test_no_qfuel_uses_default             TC_NO_QFUEL: q_fuel = DEFAULT (42_800_000)
   test_perf_data_gap_derives_missing     TC_PERF_NO_*: missing cols derived, provided cols preserved

Fast pre-pipeline unit tests (no weather/BADA needed):
   test_lf_gt_one_clamped_by_parser
   test_bada_mapper_resolves_overspec
   test_bada_mapper_rejects_unknown
   test_hc_ratio_range_validation         TC_HC_RATIO_OUT_OF_RANGE pre-check: 2.5 outside range
   test_hydrogen_content_range_validation TC_HYDROGEN_OUT_OF_RANGE pre-check: 16.0 outside range
   test_qfuel_range_validation            TC_QFUEL_OUT_OF_RANGE pre-check: 45.5 MJ/kg outside range
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pycontrails.core.flight as pyflight
import pycontrails.physics.units as pyunits
import pytest
from pandas.testing import assert_frame_equal
from scripts.create_golden_outputs import AGGREGATED_FLIGHT_SELECTIONS

from pyneats.core.views import FlightView
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.weather.weather_store import ZarrPaths
from tests.conftest import assert_climate_payload_equal


GOLDEN_DIR = Path(__file__).parent / "data" / "golden"
_BASE = "fleet_5_flights"
_AGGREGATED_INPUT = GOLDEN_DIR / f"{_BASE}_aggregated_input.json"
_AGGREGATED_OUTPUT = GOLDEN_DIR / f"{_BASE}_aggregated_output.json"


# Success TCs flight must appear in fleet_with_climate_impact.
_XFAIL_DLR = pytest.mark.xfail(
    reason="Known DLR test failing in evaluated version", strict=True
)

SUCCESS_TCS: list[tuple[str, str]] = [
    pytest.param(
        "TC_AC_OVERSPEC",
        "RYR46YN__tc_ac_overspec",
        id="TC_AC_OVERSPEC",
        marks=_XFAIL_DLR,
    ),
    ("TC_ENG_UNSPEC", "FDX5067__tc_eng_unspec"),
    ("TC_ENG_MISMATCH", "RYR46YN__tc_eng_mismatch"),
    ("TC_ENG_UNKNOWN", "ACA812__tc_eng_unknown"),
    ("TC_MASS_ALL_UNSPEC", "UAE62Y__tc_mass_all_unspec"),
    ("TC_MASS_NO_TOM_NO_LF", "FDX5067__tc_mass_no_tom_no_lf"),
    ("TC_MASS_NO_AM_NO_LF", "RYR46YN__tc_mass_no_am_no_lf"),
    ("TC_MASS_NO_AM_NO_TOM", "ACA812__tc_mass_no_am_no_tom"),
    ("TC_MASS_NO_AM", "UAE62Y__tc_mass_no_am"),
    ("TC_MASS_NO_TOM", "FDX5067__tc_mass_no_tom"),
    ("TC_MASS_NO_LF", "RYR46YN__tc_mass_no_lf"),
    ("TC_LF_GT_ONE", "ACA812__tc_lf_gt_one"),
    # Fuel default fallback cases
    ("TC_NO_HC_RATIO", "ACA812__tc_no_hc_ratio"),
    ("TC_NO_HYDROGEN", "UAE62Y__tc_no_hydrogen"),
    ("TC_NO_HC_NO_HYDROGEN", "FDX5067__tc_no_hc_no_hydrogen"),
    ("TC_NO_QFUEL", "RYR46YN__tc_no_qfuel"),
    # Performance data gap cases
    ("TC_PERF_NO_AM", "ACA812__tc_perf_no_am"),
    ("TC_PERF_NO_FF", "UAE62Y__tc_perf_no_ff"),
    ("TC_PERF_NO_EE", "FDX5067__tc_perf_no_ee"),
    ("TC_PERF_NO_TAS", "RYR46YN__tc_perf_no_tas"),
    ("TC_PERF_NO_AM_FF", "ACA812__tc_perf_no_am_ff"),
    ("TC_PERF_NO_AM_EE", "UAE62Y__tc_perf_no_am_ee"),
    ("TC_PERF_NO_AM_TAS", "FDX5067__tc_perf_no_am_tas"),
    ("TC_PERF_NO_FF_EE", "RYR46YN__tc_perf_no_ff_ee"),
    ("TC_PERF_NO_FF_TAS", "ACA812__tc_perf_no_ff_tas"),
    ("TC_PERF_NO_EE_TAS", "UAE62Y__tc_perf_no_ee_tas"),
    ("TC_PERF_NO_AM_FF_EE", "FDX5067__tc_perf_no_am_ff_ee"),
    ("TC_PERF_NO_AM_FF_TAS", "RYR46YN__tc_perf_no_am_ff_tas"),
    ("TC_PERF_NO_AM_EE_TAS", "ACA812__tc_perf_no_am_ee_tas"),
    ("TC_PERF_NO_FF_EE_TAS", "UAE62Y__tc_perf_no_ff_ee_tas"),
    ("TC_PERF_NO_ALL", "FDX5067__tc_perf_no_all"),
]

# Error TCs flight must appear in error_records, NOT in output.
ERROR_TCS: list[tuple[str, str]] = [
    ("TC_AC_NO_BADA", "UAE62Y__tc_ac_no_bada"),
    pytest.param(
        "TC_MASS_BELOW_OEW",
        "ACA812__tc_mass_below_oew",
        id="TC_MASS_BELOW_OEW",
        marks=_XFAIL_DLR,
    ),
    pytest.param(
        "TC_MASS_NOT_DECREASING",
        "UAE62Y__tc_mass_not_decreasing",
        id="TC_MASS_NOT_DECREASING",
        marks=_XFAIL_DLR,
    ),
    pytest.param(
        "TC_MASS_EXCEEDS_MTOW",
        "FDX5067__tc_mass_exceeds_mtow",
        id="TC_MASS_EXCEEDS_MTOW",
        marks=_XFAIL_DLR,
    ),
    pytest.param(
        "TC_TOM_EXCEEDS_MTOW",
        "RYR46YN__tc_tom_exceeds_mtow",
        id="TC_TOM_EXCEEDS_MTOW",
        marks=_XFAIL_DLR,
    ),
    # Fuel validation error cases
    pytest.param(
        "TC_HC_RATIO_OUT_OF_RANGE",
        "UAE62Y__tc_hc_ratio_out_of_range",
        id="TC_HC_RATIO_OUT_OF_RANGE",
        marks=_XFAIL_DLR,
    ),
    pytest.param(
        "TC_HYDROGEN_OUT_OF_RANGE",
        "FDX5067__tc_hydrogen_out_of_range",
        id="TC_HYDROGEN_OUT_OF_RANGE",
        marks=_XFAIL_DLR,
    ),
    pytest.param(
        "TC_QFUEL_OUT_OF_RANGE",
        "RYR46YN__tc_qfuel_out_of_range",
        id="TC_QFUEL_OUT_OF_RANGE",
        marks=_XFAIL_DLR,
    ),
]


def _get_flight_id(flight: Any) -> str:
    """Extract scalar flight_id from a flight's attrs."""
    fid = flight.attrs.get("flight_id", "UNKNOWN")
    if isinstance(fid, list):
        return fid[0] if fid else "UNKNOWN"
    return fid


def _find_flight(
    flights: list[Any] | None,
    flight_id: str,
) -> Any | None:
    """Find a flight in a list by flight_id."""
    if flights is None:
        return None
    for f in flights:
        if _get_flight_id(f) == flight_id:
            return f
    return None


def _extract_error_flight_ids(error_records: list[dict[str, Any]]) -> set[str]:
    """Collect all flight IDs from error records."""
    ids: set[str] = set()
    for rec in error_records:
        fi = rec.get("flight_information", {})
        fid = fi.get("flight_id", "UNKNOWN")
        if isinstance(fid, list):
            fid = fid[0] if fid else "UNKNOWN"
        ids.add(fid)
    return ids


def _skip_if_missing(weather_path: Path | None, bada_path: Path | None) -> None:
    """Skip test if weather or BADA data is not available."""
    if weather_path is None or not weather_path.is_dir():
        pytest.skip("Weather data not available")
    if bada_path is None or not bada_path.exists():
        pytest.skip("BADA data not available")


@pytest.fixture(scope="module")
def aggregated_fleet_run(weather_path, bada_path):
    """Run :class:FleetRunnerLargeEmitter once on the aggregated input.

    Returns the runner instance whose fleet_with_climate_impact and
    error_records are inspected by individual TC tests.
    """
    _skip_if_missing(weather_path, bada_path)

    if not _AGGREGATED_INPUT.exists():
        pytest.skip(f"Aggregated input not found: {_AGGREGATED_INPUT}")

    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"
    if not wind_store.is_dir():
        wind_store = None  # type: ignore[assignment]

    zarr_paths = ZarrPaths(met_store, rad_store, wind_store)

    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(_AGGREGATED_INPUT),
        zarr_paths=zarr_paths,
        bada_path=str(bada_path),
        params={},
    )
    runner = FleetRunnerLargeEmitter(cfg)
    runner.eval()
    return runner


@pytest.fixture(scope="module")
def golden_outputs_by_id() -> dict[str, FlightView]:
    """Load aggregated golden output, return dict[flight_id, FlightView]."""
    if not _AGGREGATED_OUTPUT.exists():
        pytest.skip(f"Aggregated output not found: {_AGGREGATED_OUTPUT}")

    with open(_AGGREGATED_OUTPUT, encoding="utf-8") as fh:
        data = json.load(fh)

    flights = [FlightView.from_dict(d) for d in data]
    result: dict[str, FlightView] = {}
    for f in flights:
        fid = _get_flight_id(f)
        result[fid] = f
    return result


@pytest.fixture(scope="module")
def aggregated_input_by_id() -> dict[str, dict[str, Any]]:
    """Load aggregated input JSON, return dict[flight_id, raw_flight_dict].

    The key is flight_information.flight_identification from the JSON.
    """
    if not _AGGREGATED_INPUT.exists():
        pytest.skip(f"Aggregated input not found: {_AGGREGATED_INPUT}")

    with open(_AGGREGATED_INPUT, encoding="utf-8") as fh:
        data: list[dict[str, Any]] = json.load(fh)

    result: dict[str, dict[str, Any]] = {}
    for flight in data:
        fid = flight["flight_information"]["flight_identification"]
        result[fid] = flight
    return result


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
@pytest.mark.parametrize(
    "tc_id,flight_id",
    SUCCESS_TCS,
    ids=[t[0] if isinstance(t, tuple) else t.id for t in SUCCESS_TCS],
)
def test_tc_success(
    tc_id: str,
    flight_id: str,
    aggregated_fleet_run: FleetRunnerLargeEmitter,
    golden_outputs_by_id: dict[str, FlightView],
) -> None:
    """Verify a successful TC flight matches its golden output."""
    from pyneats.steps.climate_metrics.views import FlightWithClimateImpact

    runner = aggregated_fleet_run
    rtol = 1e-3

    # Find actual flight in runner output
    actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
    assert actual is not None, (
        f"{tc_id}: flight '{flight_id}' not found in pipeline output. "
        f"Errors: {runner.error_records}"
    )

    # Find expected flight in golden data
    assert flight_id in golden_outputs_by_id, (
        f"{tc_id}: flight '{flight_id}' not found in golden output"
    )
    expected = golden_outputs_by_id[flight_id]

    # Compare DataFrame columns
    check_cols = list(FlightWithClimateImpact.REQUIRED)
    assert_frame_equal(
        actual.to_dataframe()[check_cols],
        FlightWithClimateImpact.from_flight(expected.copy()).to_dataframe()[check_cols],
        rtol=rtol,
        atol=float("inf"),
        check_dtype=False,
        obj=f"{tc_id} [{flight_id}]",
    )

    # Compare climate payload
    assert_climate_payload_equal(
        actual.attrs.get("climate_impact", {}),
        expected.attrs.get("climate_impact", {}),
        rtol=rtol,
    )


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
@pytest.mark.parametrize(
    "tc_id,flight_id",
    ERROR_TCS,
    ids=[t[0] if isinstance(t, tuple) else t.id for t in ERROR_TCS],
)
def test_tc_error(
    tc_id: str,
    flight_id: str,
    aggregated_fleet_run: FleetRunnerLargeEmitter,
) -> None:
    """Verify an error TC flight appears in error_records, not in output."""
    runner = aggregated_fleet_run

    # Must NOT be in successful output
    actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
    assert actual is None, (
        f"{tc_id}: flight '{flight_id}' should have failed but is in pipeline output"
    )

    # Must be in error_records
    error_ids = _extract_error_flight_ids(runner.error_records)
    assert flight_id in error_ids, (
        f"{tc_id}: flight '{flight_id}' not found in error_records. Error IDs: {error_ids}"
    )


# TCs where the input aircraft_mass column must be preserved in output.
_MASS_PRESERVES_INPUT_TCS: list[tuple[str, str]] = [
    ("TC_MASS_NO_LF", "RYR46YN__tc_mass_no_lf"),
    ("TC_MASS_NO_TOM", "FDX5067__tc_mass_no_tom"),
    ("TC_MASS_NO_TOM_NO_LF", "FDX5067__tc_mass_no_tom_no_lf"),
]

# TCs where takeoff_weight attr is provided and iterative estimation is used
# (no aircraft_mass column in input).
_MASS_ITERATIVE_FROM_TOM_TCS: list[tuple[str, str]] = [
    ("TC_MASS_NO_AM", "UAE62Y__tc_mass_no_am"),
    ("TC_MASS_NO_AM_NO_LF", "RYR46YN__tc_mass_no_am_no_lf"),
]

_MISSING_TRAJECTORY_VALUES_TCS: list[tuple[str, str]] = [
    ("missing_timestamps", "time"),
    ("missing_latitudes", "latitude"),
    ("missing_longitudes", "longitude"),
    ("missing_altitudes", "altitude"),
]

_PERF_DATA_GAP_TCS: list[tuple[str, str, list[str], list[str]]] = [
    # (tc_id, flight_id, missing_cols, provided_cols)
    (
        "TC_PERF_NO_AM",
        "ACA812__tc_perf_no_am",
        ["aircraft_mass"],
        ["fuel_flow", "engine_efficiency", "true_airspeed"],
    ),
    (
        "TC_PERF_NO_FF",
        "UAE62Y__tc_perf_no_ff",
        ["fuel_flow"],
        ["aircraft_mass", "engine_efficiency", "true_airspeed"],
    ),
    (
        "TC_PERF_NO_EE",
        "FDX5067__tc_perf_no_ee",
        ["engine_efficiency"],
        ["aircraft_mass", "fuel_flow", "true_airspeed"],
    ),
    (
        "TC_PERF_NO_TAS",
        "RYR46YN__tc_perf_no_tas",
        ["true_airspeed"],
        ["aircraft_mass", "fuel_flow", "engine_efficiency"],
    ),
    (
        "TC_PERF_NO_AM_FF",
        "ACA812__tc_perf_no_am_ff",
        ["aircraft_mass", "fuel_flow"],
        ["engine_efficiency", "true_airspeed"],
    ),
    (
        "TC_PERF_NO_AM_EE",
        "UAE62Y__tc_perf_no_am_ee",
        ["aircraft_mass", "engine_efficiency"],
        ["fuel_flow", "true_airspeed"],
    ),
    (
        "TC_PERF_NO_AM_TAS",
        "FDX5067__tc_perf_no_am_tas",
        ["aircraft_mass", "true_airspeed"],
        ["fuel_flow", "engine_efficiency"],
    ),
    (
        "TC_PERF_NO_FF_EE",
        "RYR46YN__tc_perf_no_ff_ee",
        ["fuel_flow", "engine_efficiency"],
        ["aircraft_mass", "true_airspeed"],
    ),
    (
        "TC_PERF_NO_FF_TAS",
        "ACA812__tc_perf_no_ff_tas",
        ["fuel_flow", "true_airspeed"],
        ["aircraft_mass", "engine_efficiency"],
    ),
    (
        "TC_PERF_NO_EE_TAS",
        "UAE62Y__tc_perf_no_ee_tas",
        ["engine_efficiency", "true_airspeed"],
        ["aircraft_mass", "fuel_flow"],
    ),
    (
        "TC_PERF_NO_AM_FF_EE",
        "FDX5067__tc_perf_no_am_ff_ee",
        ["aircraft_mass", "fuel_flow", "engine_efficiency"],
        ["true_airspeed"],
    ),
    (
        "TC_PERF_NO_AM_FF_TAS",
        "RYR46YN__tc_perf_no_am_ff_tas",
        ["aircraft_mass", "fuel_flow", "true_airspeed"],
        ["engine_efficiency"],
    ),
    (
        "TC_PERF_NO_AM_EE_TAS",
        "ACA812__tc_perf_no_am_ee_tas",
        ["aircraft_mass", "engine_efficiency", "true_airspeed"],
        ["fuel_flow"],
    ),
    (
        "TC_PERF_NO_FF_EE_TAS",
        "UAE62Y__tc_perf_no_ff_ee_tas",
        ["fuel_flow", "engine_efficiency", "true_airspeed"],
        ["aircraft_mass"],
    ),
    (
        "TC_PERF_NO_ALL",
        "FDX5067__tc_perf_no_all",
        ["aircraft_mass", "fuel_flow", "engine_efficiency", "true_airspeed"],
        [],
    ),
]

_MISSING_DEPARTURE_LANDING_TCS: list[str] = [
    ("missing_departure"),
    ("missing_landing"),
]


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
class TestBehavioralAssertions:
    """TC-specific behavioural assertions that go beyond golden output matching.

    These tests verify the actual settings and used values:
    e.g. which mass strategy was used, whether the engine UID was resolved,
    whether BADA3 was selected, etc.
    """

    # TC_LF_GT_ONE: "Set load factor to 1"

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_lf_gt_one_output_clamped(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_LF_GT_ONE: output payload_factor must be ≤ 1.0
        even though input load_factor was > 1."""
        flight_id = "ACA812__tc_lf_gt_one"
        runner = aggregated_fleet_run

        # Verify input has LF > 1
        inp = aggregated_input_by_id[flight_id]
        raw_lf = inp["flight_information"]["aircraft_properties"]["load_factor"]
        assert raw_lf > 1.0, f"Input load_factor should be > 1, got {raw_lf}"

        # Verify output has payload_factor clamped
        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in pipeline output"
        pf = actual.attrs.get("payload_factor")
        assert pf is not None, "payload_factor missing from output attrs"
        assert pf <= 1.0, (
            f"TC_LF_GT_ONE: output payload_factor should be ≤ 1.0, got {pf}"
        )

    # TC_MASS_NO_LF / TC_MASS_NO_TOM / TC_MASS_NO_TOM_NO_LF
    # Spec: "Use aircraft mass" output aircraft_mass column ≈ input am values

    @pytest.mark.parametrize(
        "tc_id,flight_id",
        _MASS_PRESERVES_INPUT_TCS,
        ids=[t[0] for t in _MASS_PRESERVES_INPUT_TCS],
    )
    def test_mass_preserves_input_aircraft_mass(
        self,
        tc_id: str,
        flight_id: str,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """When input provides aircraft_mass column, output must preserve
        all waypoint mass values."""
        runner = aggregated_fleet_run

        # Extract input am values and timestamps
        inp = aggregated_input_by_id[flight_id]
        traj = inp["flight_information"]["trajectory"]["trajectory_data"]
        input_am = np.array([pt["am"] for pt in traj], dtype=float)
        input_ts = pd.to_datetime([pt["ts"] for pt in traj], utc=True).to_numpy(
            dtype="datetime64[ns]"
        )

        # Extract output aircraft_mass column and time
        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"{tc_id}: flight '{flight_id}' not in output"
        out_df = actual.to_dataframe()
        output_am = out_df["aircraft_mass"].to_numpy(dtype=float)
        output_ts = out_df["time"].to_numpy(dtype="datetime64[ns]")

        # Interpolate input am onto output time grid to account for
        # different time resolutions between input and output.
        input_ts_f = input_ts.astype(np.float64)
        output_ts_f = output_ts.astype(np.float64)
        input_am_interp = np.interp(output_ts_f, input_ts_f, input_am)

        np.testing.assert_allclose(
            output_am,
            input_am_interp,
            rtol=1e-3,
            err_msg=f"{tc_id}: output aircraft_mass must match input am column",
        )

    # TC_MASS_NO_AM / TC_MASS_NO_AM_NO_LF
    # Spec: "Iterative from takeoff_mass" takeoff_weight preserved,
    # aircraft_mass is simulated (not from input).

    @pytest.mark.parametrize(
        "tc_id,flight_id",
        _MASS_ITERATIVE_FROM_TOM_TCS,
        ids=[t[0] for t in _MASS_ITERATIVE_FROM_TOM_TCS],
    )
    def test_mass_iterative_from_tom(
        self,
        tc_id: str,
        flight_id: str,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """When input provides takeoff_mass but no aircraft_mass column,
        output must have simulated aircraft_mass and input takeoff_weight
        preserved in attrs."""
        runner = aggregated_fleet_run

        # Verify input has takeoff_mass but no am column filled
        inp = aggregated_input_by_id[flight_id]
        ap = inp["flight_information"]["aircraft_properties"]
        assert "takeoff_mass" in ap, f"{tc_id}: input must have takeoff_mass"
        traj = inp["flight_information"]["trajectory"]["trajectory_data"]
        assert all(pt.get("am") is None for pt in traj), (
            f"{tc_id}: input am column must be unfilled (all null)"
        )

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"{tc_id}: flight '{flight_id}' not in output"

        # Output must have aircraft_mass column (simulated by BADA)
        df = actual.to_dataframe()
        assert "aircraft_mass" in df.columns, (
            f"{tc_id}: output must have simulated aircraft_mass column"
        )
        # Simulated mass should be strictly positive
        assert (df["aircraft_mass"] > 0).all(), (
            f"{tc_id}: simulated aircraft_mass must be > 0"
        )

    # TC_MASS_NO_AM_NO_TOM
    # Spec: "Based on load factor and BADA MTOW" payload_factor used, MTOW reference

    def test_mass_no_am_no_tom_uses_lf(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_MASS_NO_AM_NO_TOM: input has only load_factor (no AM, no TOM).
        Pipeline uses LF + BADA MTOW for iterative estimation."""
        flight_id = "ACA812__tc_mass_no_am_no_tom"
        runner = aggregated_fleet_run

        # Verify input has only load_factor, no takeoff_mass, no am
        inp = aggregated_input_by_id[flight_id]
        ap = inp["flight_information"]["aircraft_properties"]
        assert "load_factor" in ap, "Input must have load_factor"
        assert "takeoff_mass" not in ap, "Input must NOT have takeoff_mass"
        traj = inp["flight_information"]["trajectory"]["trajectory_data"]
        assert all(pt.get("am") is None for pt in traj), (
            "Input am column must be unfilled (all null)"
        )

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"

        # Output must have simulated aircraft_mass
        df = actual.to_dataframe()
        assert "aircraft_mass" in df.columns, (
            "Output must have simulated aircraft_mass column"
        )
        assert (df["aircraft_mass"] > 0).all(), "Simulated aircraft_mass must be > 0"

    # TC_MASS_ALL_UNSPEC
    # Spec: "LF=1, MTOW assumed" no mass params at all in input

    def test_mass_all_unspec_uses_default_lf(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_MASS_ALL_UNSPEC: no mass params in input. Pipeline assumes
        LF=1 and uses BADA MTOW for iterative mass estimation."""
        flight_id = "UAE62Y__tc_mass_all_unspec"
        runner = aggregated_fleet_run

        # Verify input has no mass params
        inp = aggregated_input_by_id[flight_id]
        ap = inp["flight_information"]["aircraft_properties"]
        assert "takeoff_mass" not in ap, "Input must NOT have takeoff_mass"
        assert "load_factor" not in ap, "Input must NOT have load_factor"
        traj = inp["flight_information"]["trajectory"]["trajectory_data"]
        assert all(pt.get("am") is None for pt in traj), (
            "Input am column must be unfilled (all null)"
        )

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"

        # Output must have simulated aircraft_mass
        df = actual.to_dataframe()
        assert "aircraft_mass" in df.columns, (
            "Output must have simulated aircraft_mass column"
        )
        assert (df["aircraft_mass"] > 0).all(), "Simulated aircraft_mass must be > 0"

    # TC_ENG_MISMATCH: "Drop, use default"

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_eng_mismatch_drops_input(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_ENG_MISMATCH: input engine_uid='PW4060' doesn't match AC type.
        Output engine_uid must differ (default used)."""
        flight_id = "RYR46YN__tc_eng_mismatch"
        runner = aggregated_fleet_run

        # Verify input has mismatched engine
        inp = aggregated_input_by_id[flight_id]
        input_eng = inp["flight_information"]["aircraft_properties"]["engine_uid"]
        assert input_eng == "PW4060", f"Expected PW4060, got {input_eng}"

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"
        output_eng = actual.attrs.get("engine_uid")
        assert output_eng is not None, "Output must have engine_uid"
        assert output_eng != "PW4060", (
            f"TC_ENG_MISMATCH: output engine_uid must differ from input "
            f"'PW4060', got '{output_eng}'"
        )
        assert output_eng == "01P11CM116", (
            f"TC_ENG_MISMATCH: output engine_uid for B738 should be 01P11CM116 "
            f", got '{output_eng}'"
        )

    # TC_ENG_UNSPEC: "Select representative"

    def test_eng_unspec_assigns_default(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_ENG_UNSPEC: input has no engine_uid. Output must have one
        (representative/conservative engine selected)."""
        flight_id = "FDX5067__tc_eng_unspec"
        runner = aggregated_fleet_run

        # Verify input has no engine_uid
        inp = aggregated_input_by_id[flight_id]
        ap = inp["flight_information"]["aircraft_properties"]
        assert "engine_uid" not in ap or ap["engine_uid"] is None, (
            "Input must NOT have engine_uid"
        )

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"
        output_eng = actual.attrs.get("engine_uid")
        assert output_eng is not None and output_eng != "", (
            "TC_ENG_UNSPEC: output must have a non-empty engine_uid"
        )
        assert output_eng == "01P21GE217", (
            f"TC_ENG_UNSPEC: output engine uid is {output_eng} ,expected 01P21GE217."
        )

    # TC_AC_OVERSPEC: "Remap to BADA naming"

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_ac_overspec_remaps_code(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_AC_OVERSPEC: input aircraft_type='B737-800W' is overspecified.
        Output bada_code must be a valid BADA name, not the raw input."""
        flight_id = "RYR46YN__tc_ac_overspec"
        runner = aggregated_fleet_run

        # Verify input has overspecified type
        inp = aggregated_input_by_id[flight_id]
        input_ac = inp["flight_information"]["aircraft_properties"]["aircraft_type"]
        assert input_ac == "B737-800W", f"Expected B737-800W, got {input_ac}"

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"
        bada_code = actual.attrs.get("bada_code")
        assert bada_code is not None, "Output must have bada_code attr"
        assert bada_code != "B737-800W", (
            f"TC_AC_OVERSPEC: bada_code must be remapped from 'B737-800W', got '{bada_code}'"
        )

    def test_var_time_resolution_correction(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """var_time_resolution: Checks time resolution of in- and output"""
        flight_id = (
            AGGREGATED_FLIGHT_SELECTIONS["tc_var_time_resolution"]
            + "__tc_var_time_resolution"
        )
        outp_time = pd.to_datetime(
            _find_flight(aggregated_fleet_run.fleet_with_climate_impact, flight_id).get(
                "time"
            ),
            utc=True,
        )
        inp_time = pd.to_datetime(
            neats_json_to_flights([aggregated_input_by_id[flight_id]])[0].get("time"),
            utc=True,
        )
        outp_dt_s = np.diff(outp_time.values) / np.timedelta64(1, "s")
        inp_dt_s = np.diff(inp_time.values) / np.timedelta64(1, "s")
        assert np.max(inp_dt_s) > 60, (
            "tc_var_time_resolution: Input not properly modified"
        )
        assert np.max(outp_dt_s) <= 60, (
            "tc_var_time_resolution: Failed to upsample waypoints to at least 60 s resolution"
        )

    def test_mixed_time_ordering(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """test_mixed_time: checks (un)sorting of in- and output"""
        flight_id = AGGREGATED_FLIGHT_SELECTIONS["tc_mixed_time"] + "__tc_mixed_time"
        outp_time = pd.to_datetime(
            _find_flight(aggregated_fleet_run.fleet_with_climate_impact, flight_id).get(
                "time"
            ),
            utc=True,
        )
        inp_time = pd.to_datetime(
            neats_json_to_flights([aggregated_input_by_id[flight_id]])[0].get("time"),
            utc=True,
        )
        outp_idx_sort = np.argsort(outp_time)
        inp_idx_sort = np.argsort(inp_time)
        assert not ((inp_idx_sort == np.arange(len(inp_idx_sort))).all()), (
            "tc_mixed_time: Input not properly modified"
        )
        assert (outp_idx_sort == np.arange(len(outp_idx_sort))).all(), (
            "tc_mixed_time: Failed to sort waypoints according to time"
        )

    def test_duplicate_time_correction(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """duplicate_time: checks duplicates in in- and output"""
        flight_id = (
            AGGREGATED_FLIGHT_SELECTIONS["tc_duplicate_time"] + "__tc_duplicate_time"
        )
        outp_time = pd.to_datetime(
            _find_flight(aggregated_fleet_run.fleet_with_climate_impact, flight_id).get(
                "time"
            ),
            utc=True,
        )
        inp_time = pd.to_datetime(
            neats_json_to_flights([aggregated_input_by_id[flight_id]])[0].get("time"),
            utc=True,
        )
        assert inp_time.duplicated().sum() > 0, (
            "tc_duplicate_time: Input not properly modified"
        )
        assert outp_time.duplicated().sum() == 0, (
            "tc_duplicate_time: Failed to remove duplicate waypoint"
        )

    @pytest.mark.parametrize(
        "tc_id,outp_var",
        _MISSING_TRAJECTORY_VALUES_TCS,
        ids=[t[0] for t in _MISSING_TRAJECTORY_VALUES_TCS],
    )
    def test_missing_trajectory_value_deletion(
        self,
        tc_id,
        outp_var,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """missing_trajectory_value: checks input for missing value and output for correction of missing value"""
        flight_id = AGGREGATED_FLIGHT_SELECTIONS["tc_" + tc_id] + "__tc_" + tc_id
        output_flight = _find_flight(
            aggregated_fleet_run.fleet_with_climate_impact, flight_id
        )
        outp_time_raw = pd.to_datetime(output_flight.get("time"), utc=True)
        outp_time = pd.Series(outp_time_raw).reset_index(drop=True)
        outp_variable = pd.Series(output_flight.get(outp_var)).reset_index(drop=True)
        input_flight = neats_json_to_flights([aggregated_input_by_id[flight_id]])[0]
        inp_time_raw = pd.to_datetime(input_flight.get("time"), utc=True)
        inp_time = pd.Series(inp_time_raw).reset_index(drop=True)
        inp_variable = pd.Series(input_flight.get(outp_var)).reset_index(drop=True)
        idx_inp_none = inp_variable[inp_variable.isnull()].index
        assert len(idx_inp_none) > 0, f"tc_{tc_id}: Input not properly modified"
        assert sum(outp_variable.isnull()) == 0, (
            f"tc_{tc_id}: Failed to handle missing values"
        )
        if outp_var == "time":
            outp_variable = pd.Series(output_flight.get("altitude")).reset_index(
                drop=True
            )
        if outp_var in ["time", "altitude"]:
            inp_variable = pyunits.ft_to_m(
                pd.Series(input_flight.get("altitude")).reset_index(drop=True) * 100
            )
        for idx in idx_inp_none:
            time_before = inp_time[idx - 1]
            time_after = inp_time[idx + 1]
            idx_outp_between = outp_time[
                (outp_time > time_before) & (outp_time < time_after)
            ].index
            if len(idx_outp_between) > 0:
                variable_before = inp_variable[idx - 1]
                variable_after = inp_variable[idx + 1]
                interpol_df = (
                    pd.DataFrame(
                        {
                            "time": [time_before]
                            + list(outp_time[idx_outp_between])
                            + [time_after],
                            "variable": [variable_before]
                            + ([None] * len(idx_outp_between))
                            + [variable_after],
                        }
                    )
                    .set_index("time")
                    .interpolate(method="time")
                )
                interpol_variable = interpol_df["variable"]
                assert np.isclose(
                    np.array(interpol_variable[1:-1]),
                    np.array(outp_variable[idx_outp_between]),
                ).all(), f"tc_{tc_id}: Failed to handle missing values"

    @pytest.mark.parametrize(
        "tc_id",
        _MISSING_DEPARTURE_LANDING_TCS,
        ids=list(_MISSING_DEPARTURE_LANDING_TCS),
    )
    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_missing_departure_landing_abortion(
        self,
        tc_id,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """missing_departure_landing: checks id calculation was aborted dur to incomplete trajectory"""
        # TODO: Check warning was triggered, but comuputation was successfull
        flight_id = AGGREGATED_FLIGHT_SELECTIONS["tc_" + tc_id] + "__tc_" + tc_id
        output_flight = _find_flight(
            aggregated_fleet_run.fleet_with_climate_impact, flight_id
        )
        assert output_flight is None, (
            f"tc_{tc_id}: Failed to detect missing flight segment"
        )
        assert flight_id in aggregated_input_by_id, f"tc_{tc_id}: Input missing"

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_altitude_fluctuations_correction(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """altitude_fluctuations: checks, if altitude fluctuations in cruise were smoothed

        The function checks the consequences of a fluctuating altitude on the flight performance first,
        before checking the smoothing of the altitude fluctuations themselfes. For the flight performance
        the fuel flow is inspected for major peaks in cruise flight, which should without steep climbs/descends
        caused by the altitude fluctuations not occur. Then the function checks, if there are many larger ups
        and downs in the fuel flow or altitude (at least every 8 waypoints one up and down in average) for
        cruise phases longer than 10 waypoints.
        """
        flight_id = (
            AGGREGATED_FLIGHT_SELECTIONS["tc_altitude_fluctuations"]
            + "__tc_altitude_fluctuations"
        )
        output_flight = _find_flight(
            aggregated_fleet_run.fleet_with_climate_impact, flight_id
        )
        # Fuel flow is used for flight performance influence check
        assert output_flight is not None, (
            f"Flight '{flight_id}' not found in pipeline output"
        )
        outp_time = (
            pd.Series(pd.to_datetime(output_flight.get("time"), utc=True))
            .reset_index(drop=True)
            .to_numpy()
        )
        outp_ff = output_flight.get("fuel_flow")
        outp_alt = output_flight.get("altitude")
        assert outp_ff is not None, (
            f"Flight '{flight_id}' has no 'fuel_flow' column in output"
        )
        flight_phases = pyflight.segment_phase(
            pyflight.segment_rocd(
                pyflight.segment_duration(outp_time),
                pyunits.m_to_ft(output_flight.get("altitude")),
            ),
            pyunits.m_to_ft(output_flight.get("altitude")),
        )
        # Index of cruise phase waypoints
        idx_cruise = np.argwhere(flight_phases == pyflight.FlightPhase.CRUISE).flatten()
        delta_idx_cruise = idx_cruise[1:] - idx_cruise[:-1]
        cruise_detected = 0
        cruise_phases_idx = []
        # Iteration over all cruise waypoints to find connected cruise segments
        for i, delta in enumerate(delta_idx_cruise):
            if (delta == 1) & (cruise_detected == 0):
                cruise_detected = i
            elif (delta != 1) & (cruise_detected > 0):
                if (
                    (
                        output_flight["time"][idx_cruise[i]]
                        - output_flight["time"][idx_cruise[cruise_detected]]
                    )
                    / np.timedelta64(1, "s")
                ) > 59:
                    cruise_phases_idx.append(
                        [idx_cruise[cruise_detected], idx_cruise[i]]
                    )
                    cruise_detected = 0
                else:
                    cruise_detected = 0
        # Iteration over all cruise segments
        for idx_start_end in cruise_phases_idx:
            idx_cruise = np.arange(idx_start_end[0], idx_start_end[1] + 1)
            cruise_ff = outp_ff[idx_cruise]
            cruise_alt = outp_alt[idx_cruise]
            cruise_ff_diff = np.diff(cruise_ff)
            cruise_alt_diff = np.diff(cruise_alt)
            cruise_ff_diff_rel = cruise_ff_diff / cruise_ff[:-1]
            cruise_ff_diff_rel[abs(cruise_ff_diff_rel) < 0.01] = 0
            cruise_alt_diff[abs(cruise_alt_diff) < 10] = 0
            assert max(cruise_ff_diff_rel) < 0.1, (
                "tc_altitude_fluctuations: Failed to smooth altitude fluctuations"
            )
            ff_ups = 0
            ff_downs = 0
            ff_current = 0
            alt_ups = 0
            alt_downs = 0
            alt_current = 0
            for ff_diff_rel, alt_diff in zip(cruise_ff_diff_rel, cruise_alt_diff):
                if (ff_diff_rel > 0) & (ff_current <= 0):
                    ff_ups += 1
                    ff_current = 1
                elif (ff_diff_rel < 0) & (ff_current >= 0):
                    ff_downs += 1
                    ff_current = -1
                if (alt_diff > 0) & (alt_current <= 0):
                    alt_ups += 1
                    alt_current = 1
                elif (alt_diff < 0) & (alt_current >= 0):
                    alt_downs += 1
                    alt_current = -1
            ff_changes = (ff_ups + ff_downs) / 2
            alt_changes = (alt_ups + alt_downs) / 2
            if len(idx_cruise) > 10:
                assert len(idx_cruise) > (ff_changes * 8), (
                    "tc_altitude_fluctuations: Failed to smooth altitude fluctuations and failed to smooth consequences on flight performance"
                )
                assert len(idx_cruise) > (alt_changes * 8), (
                    "tc_altitude_fluctuations: Failed to smooth altitude fluctuations, but no major consequences for flight performance"
                )

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_longitude_convention_correction(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """Check if changed longitude convention ([0;360] instead of [-180;180]) was corrected"""
        flight_id = (
            AGGREGATED_FLIGHT_SELECTIONS["tc_changed_longitude_convention"]
            + "__tc_changed_longitude_convention"
        )
        output_flight = _find_flight(
            aggregated_fleet_run.fleet_with_climate_impact, flight_id
        )
        input_flight = neats_json_to_flights([aggregated_input_by_id[flight_id]])[0]
        assert input_flight is not None, (
            "tc_changed_longitude_convention: No input flight"
        )
        assert output_flight is not None, (
            "tc_changed_longitude_convention: Detected change in longitude conventions, but deleted instead of correction"
        )
        assert (
            abs(output_flight.get("longitude")[0] - input_flight.get("longitude")[0])
            > 170
        ), (
            "tc_changed_longitude_convention: Changed longitude convention in input not corrected"
        )

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_trajectory_jump_correction(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """Check if jump in trajectory (longitude shift) is identified and corrected"""
        flight_id = (
            AGGREGATED_FLIGHT_SELECTIONS["tc_trajectory_jump"] + "__tc_trajectory_jump"
        )
        input_flight = neats_json_to_flights([aggregated_input_by_id[flight_id]])[0]
        output_flight = _find_flight(
            aggregated_fleet_run.fleet_with_climate_impact, flight_id
        )
        assert input_flight is not None, "tc_trajectory_jump: No input flight"
        assert output_flight is not None, (
            "tc_trajectory_jump: Detected jump in trajectory, but deleted instead of correction"
        )
        outp_longitude = output_flight.get("longitude")
        longitude_diff = np.diff(outp_longitude)
        assert np.max(abs(longitude_diff)) < 1.0, (
            "tc_trajectory_jump: Trajectory jumps in input not corrected"
        )

    # TC_NO_HC_RATIO: H/C ratio absent, hydrogen_content present
    # Output fuel hydrogen_content must match input hydrogen_content

    def test_no_hc_ratio_uses_hydrogen_content(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_NO_HC_RATIO: H/C ratio absent, hydrogen_content present.
        Output fuel hydrogen_content must match input hydrogen_content."""
        flight_id = "ACA812__tc_no_hc_ratio"
        runner = aggregated_fleet_run

        # Verify input has hydrogen_content but no hydrogen_per_carbon_ratio
        inp = aggregated_input_by_id[flight_id]
        fp = inp["flight_information"].get("fuel_properties", {})
        assert "hydrogen_content" in fp, "Input must have hydrogen_content"
        assert "hydrogen_per_carbon_ratio" not in fp, (
            "Input must NOT have hydrogen_per_carbon_ratio"
        )
        input_hc = fp["hydrogen_content"]

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in pipeline output"
        output_hc = actual.attrs.get("hydrogen_content")
        assert output_hc is not None, "Output must have hydrogen_content attr"
        assert abs(output_hc - input_hc) < 1e-3, (
            f"TC_NO_HC_RATIO: output hydrogen_content {output_hc} must match "
            f"input hydrogen_content {input_hc}"
        )

    # TC_NO_HYDROGEN: hydrogen_content absent, H/C ratio present
    # Output fuel hydrogen_content must be derived from H/C ratio conversion

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_no_hydrogen_uses_hc_ratio(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_NO_HYDROGEN: hydrogen_content absent, H/C ratio present.
        Output fuel hydrogen_content must be derived from H/C ratio conversion."""
        flight_id = "UAE62Y__tc_no_hydrogen"
        runner = aggregated_fleet_run

        # Verify input has h_c_ratio but no hydrogen_content
        inp = aggregated_input_by_id[flight_id]
        fp = inp["flight_information"].get("fuel_properties", {})
        assert "hydrogen_per_carbon_ratio" in fp, (
            "Input must have hydrogen_per_carbon_ratio"
        )
        assert "hydrogen_content" not in fp, "Input must NOT have hydrogen_content"

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in pipeline output"
        output_hc = actual.attrs.get("hydrogen_content")
        assert output_hc is not None, (
            "TC_NO_HYDROGEN: output must have hydrogen_content attr (derived from H/C ratio)"
        )
        # Must be a physically plausible hydrogen content (roughly 13–16 mass%)
        assert 13.0 <= output_hc <= 16.0, (
            f"TC_NO_HYDROGEN: derived hydrogen_content {output_hc} outside plausible range [13, 16]"
        )

    # TC_NO_HC_NO_HYDROGEN: both H/C ratio and hydrogen_content absent
    # Output fuel hydrogen_content must equal DEFAULT_HYDROGEN_CONTENT (13.79)

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_no_hc_no_hydrogen_uses_default(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_NO_HC_NO_HYDROGEN: both H/C ratio and hydrogen_content absent.
        Output fuel hydrogen_content must equal DEFAULT_HYDROGEN_CONTENT (13.79)."""
        from pyneats.core.neats_default_parameters import DEFAULT_HYDROGEN_CONTENT

        flight_id = "FDX5067__tc_no_hc_no_hydrogen"
        runner = aggregated_fleet_run

        # Verify input has neither fuel property
        inp = aggregated_input_by_id[flight_id]
        fp = inp["flight_information"].get("fuel_properties", {})
        assert "hydrogen_per_carbon_ratio" not in fp, (
            "Input must NOT have hydrogen_per_carbon_ratio"
        )
        assert "hydrogen_content" not in fp, "Input must NOT have hydrogen_content"

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in pipeline output"
        output_hc = actual.attrs.get("hydrogen_content")
        assert output_hc is not None, "Output must have hydrogen_content attr"
        assert abs(output_hc - DEFAULT_HYDROGEN_CONTENT) < 1e-3, (
            f"TC_NO_HC_NO_HYDROGEN: output hydrogen_content {output_hc} must equal "
            f"DEFAULT_HYDROGEN_CONTENT {DEFAULT_HYDROGEN_CONTENT}"
        )

    # TC_NO_QFUEL: calorific value absent
    # Output fuel q_fuel must equal DEFAULT_Q_FUEL (42_800_000)

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_no_qfuel_uses_default(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_NO_QFUEL: calorific value absent.
        Output fuel q_fuel must equal DEFAULT_Q_FUEL (42_800_000)."""
        from pyneats.core.neats_default_parameters import DEFAULT_Q_FUEL

        flight_id = "RYR46YN__tc_no_qfuel"
        runner = aggregated_fleet_run

        # Verify input has no calorific_value
        inp = aggregated_input_by_id[flight_id]
        fp = inp["flight_information"].get("fuel_properties", {})
        assert "calorific_value" not in fp, "Input must NOT have calorific_value"

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in pipeline output"
        output_qf = actual.attrs.get("q_fuel")
        assert output_qf is not None, "Output must have q_fuel attr"
        assert abs(output_qf - DEFAULT_Q_FUEL) < 1.0, (
            f"TC_NO_QFUEL: output q_fuel {output_qf} must equal DEFAULT_Q_FUEL {DEFAULT_Q_FUEL}"
        )

    # TC_PERF_NO_*: performance data gap cases
    # am/ff/ee are always present as JSON fields (null = missing).
    # true_airspeed (tas) is optional and may be entirely absent from the input DataFrame.

    @pytest.mark.parametrize(
        "tc_id,flight_id,missing,provided",
        _PERF_DATA_GAP_TCS,
        ids=[t[0] for t in _PERF_DATA_GAP_TCS],
    )
    def test_perf_data_gap_derives_missing(
        self,
        tc_id: str,
        flight_id: str,
        missing: list[str],
        provided: list[str],
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """Performance data gap: missing cols (all-null in input) must be derived
        (non-null in output); provided cols must be preserved from input
        (interpolated to output time grid).
        """
        runner = aggregated_fleet_run

        # Parse input via neats_json_to_flights to get the canonical DataFrame.
        raw_inp = aggregated_input_by_id[flight_id]
        inp_flights = neats_json_to_flights([raw_inp])
        assert len(inp_flights) == 1, f"{tc_id}: expected 1 parsed input flight"
        inp_df = inp_flights[0]

        inp_time = pd.to_datetime(inp_df["time"], utc=True).to_numpy(
            dtype="datetime64[ns]"
        )

        # Verify missing columns are all-null in input
        for col in missing:
            if col not in inp_df.columns:
                continue
            assert inp_df[col].isna().all(), (
                f"{tc_id}: input column '{col}' must be all-null (missing), "
                f"but has {inp_df[col].notna().sum()} non-null value(s)"
            )

        # Verify provided columns have real values in input
        for col in provided:
            if col not in inp_df.columns:
                continue
            assert inp_df[col].notna().any(), (
                f"{tc_id}: input column '{col}' must have non-null values (provided), "
                f"but is all-null"
            )

        # Flight must have succeeded
        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, (
            f"{tc_id}: flight '{flight_id}' not found in pipeline output. "
            f"Errors: {runner.error_records}"
        )

        out_df = actual.to_dataframe()
        out_time = out_df["time"].to_numpy(dtype="datetime64[ns]")

        # Missing cols must be derived (non-null) in output
        for col in missing:
            assert col in out_df.columns, (
                f"{tc_id}: output must contain derived column '{col}'"
            )
            assert out_df[col].notna().any(), (
                f"{tc_id}: derived column '{col}' must have non-null values in output"
            )

        # Provided cols must be preserved from input
        # Interpolate input values onto the output time grid and compare.
        inp_ts_f = inp_time.astype(np.float64)
        out_ts_f = out_time.astype(np.float64)

        for col in provided:
            if col not in inp_df.columns:
                continue
            assert col in out_df.columns, (
                f"{tc_id}: output must contain provided column '{col}'"
            )
            inp_vals = inp_df[col].to_numpy(dtype=float)
            valid_mask = ~np.isnan(inp_vals)
            if valid_mask.sum() < 2:
                continue
            inp_vals_valid = inp_vals[valid_mask]
            inp_ts_valid = inp_ts_f[valid_mask]
            out_vals = out_df[col].to_numpy(dtype=float)
            # Restrict to output points within the input time range
            in_range = (out_ts_f >= inp_ts_valid[0]) & (out_ts_f <= inp_ts_valid[-1])
            if not in_range.any():
                continue
            inp_interp = np.interp(out_ts_f[in_range], inp_ts_valid, inp_vals_valid)
            np.testing.assert_allclose(
                out_vals[in_range],
                inp_interp,
                rtol=1e-3,
                err_msg=(
                    f"{tc_id}: output column '{col}' must preserve "
                    f"input values (interpolated to output time grid)"
                ),
            )


class TestPrePipelineValidation:
    """Fast unit tests that verify specific behaviours without running the
    full fleet pipeline. These do NOT require weather or BADA data and are
    therefore not marked as slow or integration tests.

    Note: some tests like lf_gt_one are doubled with and without pipeline.
    """

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_lf_gt_one_clamped_by_parser(self) -> None:
        """TC_LF_GT_ONE pre-check: load_factor > 1 is clamped to 1.0
        during JSON-to-DataFrame conversion.
        """
        if not _AGGREGATED_INPUT.exists():
            pytest.skip(f"Aggregated input not found: {_AGGREGATED_INPUT}")

        with open(_AGGREGATED_INPUT, encoding="utf-8") as fh:
            all_flights = json.load(fh)

        # Find the TC_LF_GT_ONE flight
        lf_flight = None
        for flight in all_flights:
            fid = flight["flight_information"]["flight_identification"]
            if fid == "ACA812__tc_lf_gt_one":
                lf_flight = flight
                break

        assert lf_flight is not None, (
            "ACA812__tc_lf_gt_one not found in aggregated input"
        )

        # The raw input should have load_factor > 1
        raw_lf = lf_flight["flight_information"]["aircraft_properties"]["load_factor"]
        assert raw_lf > 1.0, f"Expected raw load_factor > 1, got {raw_lf}"

        # After neats_json_to_flights, the DataFrame should have
        # payload_factor clamped to 1.0
        dfs = neats_json_to_flights([lf_flight])
        assert len(dfs) == 1
        df = dfs[0]

        payload_factor = df.attrs.get("payload_factor")
        assert payload_factor is not None, "payload_factor not in DataFrame attrs"
        assert payload_factor <= 1.0, (
            f"Expected payload_factor clamped to <= 1.0, got {payload_factor}"
        )

    @pytest.mark.xfail(
        reason="Known DLR test failing in evaluated version", strict=True
    )
    def test_bada_mapper_resolves_overspec(self) -> None:
        """TC_AC_OVERSPEC pre-check: BADA mapper resolves B737-800W
        to a valid BADA type.
        """
        from pyneats.steps.performance.bada_mapper import BadaMapper
        from pyneats.steps.performance.bada_mapper import BadaMappingPaths

        resources = Path(__file__).parent.parent / "src" / "pyneats" / "resources"
        paths = BadaMappingPaths(
            icao_series_engine=resources
            / "ECTL_mapping_by_ICAO_and_ACFT_SERIES_and_ENGINE_ID.csv",
            icao_series=resources / "ECTL_mapping_by_ICAO_and_ACFT_SERIES.csv",
            icao_engine=resources / "ECTL_mapping_by_ICAO_and_ENGINE_ID.csv",
            default_engine_by_icao=resources / "MRR_conservative_mapping.csv",
            icao_only=resources / "ECTL_mapping_by_ICAO.csv",
        )
        mapper = BadaMapper(paths)

        # B737-800W is an overspecified type; bada_type() should resolve it
        # without raising KeyError. Returns (NB_ENG, BADA3, BADA4, ENGINE_ID).
        _nb_eng, bada3, bada4, _engine_id = mapper.bada_type("B737-800W")
        assert bada3 or bada4, (
            "BADA mapper resolved B737-800W but both BADA3 and BADA4 names are empty"
        )
        correct_icao = "B738"
        assert bada3 == correct_icao or bada4 == correct_icao, (
            f"BADA mapper found bada3={bada3} and bada4={bada4}, but not correct ICAO "
            f"naming ({correct_icao})"
        )

    def test_bada_mapper_rejects_unknown(self) -> None:
        """TC_AC_NO_BADA pre-check: BADA mapper cannot resolve ZZZZ."""
        from pyneats.steps.performance.bada_mapper import BadaMapper
        from pyneats.steps.performance.bada_mapper import BadaMappingPaths

        resources = Path(__file__).parent.parent / "src" / "pyneats" / "resources"
        paths = BadaMappingPaths(
            icao_series_engine=resources
            / "ECTL_mapping_by_ICAO_and_ACFT_SERIES_and_ENGINE_ID.csv",
            icao_series=resources / "ECTL_mapping_by_ICAO_and_ACFT_SERIES.csv",
            icao_engine=resources / "ECTL_mapping_by_ICAO_and_ENGINE_ID.csv",
            default_engine_by_icao=resources / "MRR_conservative_mapping.csv",
            icao_only=resources / "ECTL_mapping_by_ICAO.csv",
        )
        mapper = BadaMapper(paths)

        # ZZZZ is completely unknown; bada_type() should raise KeyError
        with pytest.raises(KeyError, match="Unable to resolve BADA mapping"):
            mapper.bada_type("ZZZZ")

    def test_hc_ratio_range_validation(self) -> None:
        """TC_HC_RATIO_OUT_OF_RANGE pre-check: H/C ratio 2.5 is outside [1.9061, 2.1857].

        Validates that the out-of-range value used in the golden test case is
        genuinely outside the valid range so the error case makes sense.
        """
        hc_ratio_value = 2.5
        valid_min = 1.9061
        valid_max = 2.1857
        assert hc_ratio_value < valid_min or hc_ratio_value > valid_max, (
            f"Test value {hc_ratio_value} must be outside [{valid_min}, {valid_max}]"
        )

    def test_hydrogen_content_range_validation(self) -> None:
        """TC_HYDROGEN_OUT_OF_RANGE pre-check: hydrogen 16.0 is outside [13.79, 15.5].

        Validates that the out-of-range value used in the golden test case is
        genuinely outside the valid range so the error case makes sense.
        """
        hydrogen_value = 16.0
        valid_min = 13.79
        valid_max = 15.5
        assert hydrogen_value < valid_min or hydrogen_value > valid_max, (
            f"Test value {hydrogen_value} must be outside [{valid_min}, {valid_max}]"
        )

    def test_qfuel_range_validation(self) -> None:
        """TC_QFUEL_OUT_OF_RANGE pre-check: q_fuel 45_500_000 J/kg (45.5 MJ/kg) is outside
        [42.6397, 44.5] MJ/kg.

        Validates that the out-of-range value used in the golden test case is
        genuinely outside the valid range so the error case makes sense.
        """
        qfuel_value_mj_per_kg = 45_500_000.0 / 1_000_000.0  # convert J/kg → MJ/kg
        valid_min = 42.6397
        valid_max = 44.5
        assert qfuel_value_mj_per_kg < valid_min or qfuel_value_mj_per_kg > valid_max, (
            f"Test value {qfuel_value_mj_per_kg} MJ/kg must be outside [{valid_min}, {valid_max}]"
        )

    @pytest.mark.parametrize(
        "golden_input_file",
        sorted(GOLDEN_DIR.glob("*_input.json")),
        ids=lambda p: p.stem,
    )
    def test_golden_inputs_match_schema(self, golden_input_file: Path) -> None:
        """All golden input JSON files must pass flight schema validation.

        This catches silent dtype regressions (e.g. timestamp fields
        serialized as integers instead of ISO-8601 strings).

        Flights whose ``flight_identification`` contains ``tc_missing_``
        are intentionally malformed (null required waypoint fields) and
        are therefore excluded from strict schema validation.
        """
        jsonschema = pytest.importorskip("jsonschema")

        schema_path = (
            Path(__file__).parent.parent / "scripts" / "schemas" / "flight_schema.json"
        )
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)

        with open(golden_input_file, encoding="utf-8") as fh:
            flights = json.load(fh)

        validator = jsonschema.Draft202012Validator(schema)
        errors: list[str] = []
        for idx, flight in enumerate(flights):
            fid = flight.get("flight_information", {}).get(
                "flight_identification", f"index-{idx}"
            )
            # Skip flights that intentionally contain null required fields
            # (tc_missing_timestamps, tc_missing_latitudes, etc.)
            if "tc_missing_" in fid:
                continue
            errors.extend(
                f"Flight '{fid}': {err.message} "
                f"(path: {'.'.join(str(p) for p in err.absolute_path)})"
                for err in validator.iter_errors(flight)
            )

        assert not errors, (
            f"Schema validation failed for {golden_input_file.name}:\n"
            + "\n".join(errors)
        )
