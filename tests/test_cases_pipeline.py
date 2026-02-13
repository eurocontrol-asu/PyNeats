"""Comprehensive pytest test suite implementing test cases.

All TC tests use the aggregated golden data:
    - tests/data/golden/fleet_5_flights_aggregated_input.json
    - tests/data/golden/fleet_5_flights_aggregated_output.json

A single :class:`FleetRunnerLargeEmitter` run (module-scoped fixture) processes
all flights at once. Individual tests then assert per-flight results by
flight_id, comparing against the golden output or checking error records.

Success test cases (TC) flight must appear in pipeline output:
   TC_AC_OVERSPEC
   TC_AC_NO_BADA4
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

Error test cases flight must appear in error_records (abort evaluation):
   TC_AC_NO_BADA
   TC_MASS_BELOW_OEW
   TC_MASS_NOT_DECREASING
   TC_MASS_EXCEEDS_MTOW
   TC_TOM_EXCEEDS_MTOW

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
   test_eng_unknown_resolves_different    TC_ENG_UNKNOWN: predecessor/successor
   test_eng_mismatch_drops_input          TC_ENG_MISMATCH: drop, use default
   test_eng_unspec_assigns_default        TC_ENG_UNSPEC: select representative
   test_ac_no_bada4_uses_bada3            TC_AC_NO_BADA4: BADA3 fallback
   test_ac_overspec_remaps_code           TC_AC_OVERSPEC: remap to BADA naming

Fast pre-pipeline unit tests (no weather/BADA needed):
   test_lf_gt_one_clamped_by_parser
   test_bada_mapper_resolves_overspec
   test_bada_mapper_rejects_unknown
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from pyneats.core.views import FlightView
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.weather.weather_store import ZarrPaths
from tests.conftest import assert_climate_payload_equal

GOLDEN_DIR = Path(__file__).parent / "data" / "golden"
_BASE = "fleet_5_flights"
_AGGREGATED_INPUT = GOLDEN_DIR / f"{_BASE}_aggregated_input.json"
_AGGREGATED_OUTPUT = GOLDEN_DIR / f"{_BASE}_aggregated_output.json"


# Success TCs flight must appear in fleet_with_climate_impact.
SUCCESS_TCS: list[tuple[str, str]] = [
    ("TC_AC_OVERSPEC", "RYR46YN__tc_ac_overspec"),
    ("TC_AC_NO_BADA4", "ACA812__tc_ac_no_bada4"),
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
]

# Error TCs flight must appear in error_records, NOT in output.
ERROR_TCS: list[tuple[str, str]] = [
    ("TC_AC_NO_BADA", "UAE62Y__tc_ac_no_bada"),
    ("TC_MASS_BELOW_OEW", "ACA812__tc_mass_below_oew"),
    ("TC_MASS_NOT_DECREASING", "UAE62Y__tc_mass_not_decreasing"),
    ("TC_MASS_EXCEEDS_MTOW", "FDX5067__tc_mass_exceeds_mtow"),
    ("TC_TOM_EXCEEDS_MTOW", "RYR46YN__tc_tom_exceeds_mtow"),
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
    ids=[t[0] for t in SUCCESS_TCS],
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
    ids=[t[0] for t in ERROR_TCS],
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
        assert pf <= 1.0, f"TC_LF_GT_ONE: output payload_factor should be ≤ 1.0, got {pf}"

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
        assert (df["aircraft_mass"] > 0).all(), f"{tc_id}: simulated aircraft_mass must be > 0"

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
        assert "aircraft_mass" in df.columns, "Output must have simulated aircraft_mass column"
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
        assert "aircraft_mass" in df.columns, "Output must have simulated aircraft_mass column"
        assert (df["aircraft_mass"] > 0).all(), "Simulated aircraft_mass must be > 0"

    # TC_ENG_UNKNOWN: "Use predecessor/successor"

    def test_eng_unknown_resolves_different(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
        aggregated_input_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """TC_ENG_UNKNOWN: input engine_uid='CFM56-FAKE' is unknown.
        Output engine_uid must differ (predecessor/successor used)."""
        flight_id = "ACA812__tc_eng_unknown"
        runner = aggregated_fleet_run

        # Verify input has the fake engine
        inp = aggregated_input_by_id[flight_id]
        input_eng = inp["flight_information"]["aircraft_properties"]["engine_uid"]
        assert input_eng == "CFM56-FAKE", f"Expected CFM56-FAKE, got {input_eng}"

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"
        output_eng = actual.attrs.get("engine_uid")
        assert output_eng is not None, "Output must have engine_uid"
        assert output_eng != "CFM56-FAKE", (
            f"TC_ENG_UNKNOWN: output engine_uid must differ from input "
            f"'CFM56-FAKE', got '{output_eng}'"
        )

    # TC_ENG_MISMATCH: "Drop, use default"

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
        assert "engine_uid" not in ap or ap["engine_uid"] is None, "Input must NOT have engine_uid"

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"
        output_eng = actual.attrs.get("engine_uid")
        assert output_eng is not None and output_eng != "", (
            "TC_ENG_UNSPEC: output must have a non-empty engine_uid"
        )

    # TC_AC_NO_BADA4: "Use BADA 3 aircraft"

    def test_ac_no_bada4_uses_bada3(
        self,
        aggregated_fleet_run: FleetRunnerLargeEmitter,
    ) -> None:
        """TC_AC_NO_BADA4: AC type (AT72) only in BADA3. Output must show
        bada_version='BADA3'."""
        flight_id = "ACA812__tc_ac_no_bada4"
        runner = aggregated_fleet_run

        actual = _find_flight(runner.fleet_with_climate_impact, flight_id)
        assert actual is not None, f"Flight '{flight_id}' not in output"
        bada_ver = actual.attrs.get("bada_version")
        assert bada_ver == "BADA3", (
            f"TC_AC_NO_BADA4: expected bada_version='BADA3', got '{bada_ver}'"
        )

    # TC_AC_OVERSPEC: "Remap to BADA naming"

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


class TestPrePipelineValidation:
    """Fast unit tests that verify specific behaviours without running the
    full fleet pipeline. These do NOT require weather or BADA data and are
    therefore not marked as slow or integration tests.

    Note: some tests like lf_gt_one are doubled with and without pipeline.
    """

    def test_lf_gt_one_clamped_by_parser(self) -> None:
        """TC_LF_GT_ONE pre-check: load_factor > 1 is clamped to 1.0
        during JSON-to-DataFrame conversion.
        """
        from pyneats.steps.parsing.neats_io import neats_json_to_flights

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

        assert lf_flight is not None, "ACA812__tc_lf_gt_one not found in aggregated input"

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

    def test_bada_mapper_resolves_overspec(self) -> None:
        """TC_AC_OVERSPEC pre-check: BADA mapper resolves B737-800W
        to a valid BADA type.
        """
        from pyneats.steps.performance.bada_mapper import BadaMapper, BadaMappingPaths

        resources = Path(__file__).parent.parent / "src" / "pyneats" / "resources"
        paths = BadaMappingPaths(
            icao_series_engine=resources / "ECTL_mapping_by_ICAO_and_ACFT_SERIES_and_ENGINE_ID.csv",
            icao_series=resources / "ECTL_mapping_by_ICAO_and_ACFT_SERIES.csv",
            icao_engine=resources / "ECTL_mapping_by_ICAO_and_ENGINE_ID.csv",
            default_engine_by_icao=resources / "MRR_conservative_mapping.csv",
            icao_only=resources / "ECTL_mapping_by_ICAO.csv",
        )
        mapper = BadaMapper(paths)

        # B737-800W is an overspecified type; bada_type() should resolve it
        # without raising KeyError. Returns (NB_ENG, BADA3, BADA4, ENGINE_ID).
        nb_eng, bada3, bada4, engine_id = mapper.bada_type("B737-800W")
        assert bada3 or bada4, (
            "BADA mapper resolved B737-800W but both BADA3 and BADA4 names are empty"
        )

    def test_bada_mapper_rejects_unknown(self) -> None:
        """TC_AC_NO_BADA pre-check: BADA mapper cannot resolve ZZZZ."""
        from pyneats.steps.performance.bada_mapper import BadaMapper, BadaMappingPaths

        resources = Path(__file__).parent.parent / "src" / "pyneats" / "resources"
        paths = BadaMappingPaths(
            icao_series_engine=resources / "ECTL_mapping_by_ICAO_and_ACFT_SERIES_and_ENGINE_ID.csv",
            icao_series=resources / "ECTL_mapping_by_ICAO_and_ACFT_SERIES.csv",
            icao_engine=resources / "ECTL_mapping_by_ICAO_and_ENGINE_ID.csv",
            default_engine_by_icao=resources / "MRR_conservative_mapping.csv",
            icao_only=resources / "ECTL_mapping_by_ICAO.csv",
        )
        mapper = BadaMapper(paths)

        # ZZZZ is completely unknown; bada_type() should raise KeyError
        with pytest.raises(KeyError, match="Unable to resolve BADA mapping"):
            mapper.bada_type("ZZZZ")
