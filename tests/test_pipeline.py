"""Test full pipeline using FlightRunner against golden reference data.

This module tests the FlightRunner pipeline by:
1. Loading input flights from golden test cases
2. Running each flight through the full pipeline
3. Comparing results against expected golden outputs

Golden test cases are auto-discovered from tests/data/golden/.
Each case has a {case_name}_input.json and {case_name}_output.json pair.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pyneats.core.views import FlightView
from pyneats.runners.flight import RunnerConfig
from pyneats.runners.large_emitter import FlightRunnerLargeEmitter
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from tests.conftest import assert_climate_payload_equal
from tests.golden_compare import GOLDEN_RTOL
from tests.golden_compare import assert_matches_golden


# Test cases that require FleetRunner (heterogeneous column/attr handling)
FLEET_RUNNER_ONLY_CASES = frozenset({"mixed_columns", "mixed_attrs", "aggregated"})

# The golden outputs come from FleetRunner, which runs CoCiP on the whole fleet;
# FlightRunner runs it on one flight. With identical inputs, a contrail can end a
# few minutes apart in the two runs (audit I12). Measured on dev d993528, all 8
# FlightRunner cases against the FleetRunner goldens (2026-10-30):
# - every non-contrail column, attr and payload value: bit-identical, except
# - CoCiP state columns (G, width, iwc_1, rhi_1, f_surv, ...): at most 1.9e-6 of
#   the column maximum (rhi_1), up to 6e-4 relative at near-zero points.
#   Compared at GOLDEN_RTOL with a wider floor, FLIGHT_ATOL_FRACTION = 0.3:
#   the closest values use 0.28 of their tolerance (rh_critical_sac, ACA812,
#   q_fuel case; 3.5x margin; rhi_1 5.7x);
# - contrail evolution columns (CONTRAIL_COLUMN_ATOL): up to 28 % at single
#   points, contrail_age (integer ns) differs on 3 flights; the NaN pattern and
#   length are identical. Each is compared within a fraction of its column
#   maximum, about 3x the measured maximum difference (in brackets; the
#   closest uses 0.35 of its tolerance, rsr_mean);
# - contrail totals (contrails_ef_J, Contrails EAGWP/CO2eq): at most 1.87e-4
#   (FDX5067, q_fuel case). CONTRAIL_RTOL leaves a 5.3x margin and matches the
#   ~1e-3 that audit I12 saw on older code.
FLIGHT_ATOL_FRACTION = 0.3
CONTRAIL_RTOL = 1e-3
CONTRAIL_COLUMN_ATOL = {
    "ef": 2e-2,  # (6.4e-3, FDX5067 q_fuel)
    "contrail_age": 0.1,  # (3.1e-2, FDX5067 q_fuel)
    "olr_mean": 0.1,  # (2.2e-2, FDX5067 q_fuel)
    "rf_sw_mean": 0.1,  # (3.4e-2, FDX5067 q_fuel)
    "rf_lw_mean": 0.15,  # (4.5e-2, UAE62Y ref)
    "rsr_mean": 0.2,  # (6.9e-2, FDX5067 q_fuel)
    "rf_net_mean": 0.25,  # (7.7e-2, UAE62Y ref)
    "sdr_mean": 0.7,  # (2.2e-1, ACA812 ref)
}


def _as_fleet_record(record: dict[str, Any]) -> dict[str, Any]:
    """Put a FlightRunner record in the layout of the FleetRunner goldens.

    The two runners serialise two values differently:
    - ``wingspan``: a flight attribute in FlightRunner, a per-point column
      (float32, 34.1 -> 34.099998...) after the FleetRunner merge;
    - ``pycontrails_version``: a CoCiP attribute that the FleetRunner output
      does not carry.
    """
    record = dict(record)
    record.pop("pycontrails_version", None)
    wingspan = record.get("wingspan")
    if wingspan is not None and not isinstance(wingspan, list):
        record["wingspan"] = [wingspan] * len(record["time"])
    return record


def _split_contrails(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (payload without contrail values, contrail values only)."""
    rest = copy.deepcopy(payload)
    info = rest.get("flight_information", {})
    contrails = {"contrails_ef_J": info.pop("contrails_ef_J", None)}
    metrics = rest.get("climate_metrics", [])
    contrails["climate_metrics"] = [
        m for m in metrics if m.get("species") == "Contrails"
    ]
    rest["climate_metrics"] = [m for m in metrics if m.get("species") != "Contrails"]
    return rest, contrails


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_flight_runner_golden(
    golden_case: str,
    golden_input: list[dict[str, Any]],
    golden_output: list[FlightView],
    golden_output_path: Path,
    weather,
    bada_path,
):
    """Test FlightRunner produces golden outputs for each case.

    Runs each flight in the golden case through FlightRunner and compares the
    output with its golden record (``tests/golden_compare.py``) at
    ``GOLDEN_RTOL``, except the contrail columns and totals (see
    ``CONTRAIL_COLUMN_ATOL`` and ``CONTRAIL_RTOL``).

    Note: Cases with heterogeneous inputs (mixed_columns, mixed_attrs) are
    skipped as they require FleetRunner's column/attr harmonization.
    """
    # Skip FleetRunner-only test cases
    if any(case_suffix in golden_case for case_suffix in FLEET_RUNNER_ONLY_CASES):
        pytest.skip(f"'{golden_case}' requires FleetRunner (heterogeneous inputs)")

    # Skip if dependencies not available
    if weather is None:
        pytest.skip("Weather data not available")
    if bada_path is None or not bada_path.exists():
        pytest.skip("BADA data not available")

    # Setup BADA parameters
    performance_params = {
        "bada4_root_path": str(bada_path),
        "bada3_root_path": str(bada_path),
    }
    cfg = RunnerConfig(params={"performance": performance_params})

    # Convert input JSON to DataFrames
    dataframes = neats_json_to_flights(golden_input)
    assert len(dataframes) == len(golden_output), (
        f"Case '{golden_case}': input has {len(dataframes)} flights, "
        f"but output has {len(golden_output)} flights"
    )
    with open(golden_output_path, encoding="utf-8") as fh:
        golden_records = json.load(fh)

    # Test each flight
    for i, (df, expected_flight, expected_record) in enumerate(
        zip(dataframes, golden_output, golden_records, strict=True)
    ):
        flight_id = expected_flight.attrs.get("flight_id", f"flight_{i}")
        if isinstance(flight_id, list):
            flight_id = flight_id[0] if flight_id else f"flight_{i}"
        label = f"Case '{golden_case}', flight {i} [{flight_id}]"

        # Run pipeline
        pipeline = FlightRunnerLargeEmitter(weather, df, cfg=cfg)
        pipeline.eval()

        # Get output
        if pipeline.flight_with_climate_impact is None:
            pytest.fail(f"{label}: pipeline produced no output")

        # Columns and attrs; the climate payload is split below
        actual_record = _as_fleet_record(pipeline.flight_with_climate_impact.to_dict())
        assert_matches_golden(
            actual_record,
            expected_record,
            rtol=GOLDEN_RTOL,
            atol_fraction=FLIGHT_ATOL_FRACTION,
            loose=CONTRAIL_COLUMN_ATOL,
            skip={"climate_impact"},
            label=label,
        )

        # Compare climate_payload
        actual_rest, actual_contrails = _split_contrails(
            actual_record["climate_impact"]
        )
        expected_rest, expected_contrails = _split_contrails(
            expected_record["climate_impact"]
        )
        assert_climate_payload_equal(actual_rest, expected_rest, rtol=GOLDEN_RTOL)
        assert_climate_payload_equal(
            actual_contrails, expected_contrails, rtol=CONTRAIL_RTOL
        )
