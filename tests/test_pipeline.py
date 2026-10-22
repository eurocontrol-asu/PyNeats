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
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from pyneats.core.views import FlightView
from pyneats.runners.flight import RunnerConfig
from pyneats.runners.large_emitter import FlightRunnerLargeEmitter
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from tests.conftest import assert_climate_payload_equal


# Test cases that require FleetRunner (heterogeneous column/attr handling)
FLEET_RUNNER_ONLY_CASES = frozenset({"mixed_columns", "mixed_attrs", "aggregated"})

# The golden outputs come from FleetRunner, which runs CoCiP on the whole fleet;
# FlightRunner runs it on one flight. With identical inputs, a contrail can end a
# few minutes apart in the two runs (audit I12), so contrail-based values get a
# looser tolerance here. Everything else keeps 1e-3.
CONTRAIL_RTOL = 5e-3


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
    weather,
    bada_path,
):
    """Test FlightRunner produces golden outputs for each case.

    Runs each flight in the golden case through FlightRunner and compares
    the output with expected results.

    Note: Cases with heterogeneous inputs (mixed_columns, mixed_attrs) are
    skipped as they require FleetRunner's column/attr harmonization.
    """
    # Skip FleetRunner-only test cases
    if any(case_suffix in golden_case for case_suffix in FLEET_RUNNER_ONLY_CASES):
        pytest.skip(f"'{golden_case}' requires FleetRunner (heterogeneous inputs)")
    # Import here to avoid collection errors when pyBADA not installed
    from pyneats.steps.climate_metrics.views import FlightWithClimateImpact

    # Skip if dependencies not available
    if weather is None:
        pytest.skip("Weather data not available")
    if bada_path is None or not bada_path.exists():
        pytest.skip("BADA data not available")

    # Test configuration
    rtol = 1e-3  # 0.1% relative tolerance
    atol = float("inf")  # No absolute tolerance limit
    check_cols = list(FlightWithClimateImpact.REQUIRED)

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

    # Test each flight
    for i, (df, expected_flight) in enumerate(
        zip(dataframes, golden_output, strict=True)
    ):
        flight_id = expected_flight.attrs.get("flight_id", f"flight_{i}")
        if isinstance(flight_id, list):
            flight_id = flight_id[0] if flight_id else f"flight_{i}"

        # Run pipeline
        pipeline = FlightRunnerLargeEmitter(weather, df, cfg=cfg)
        pipeline.eval()

        # Get output
        if pipeline.flight_with_climate_impact is None:
            pytest.fail(
                f"Case '{golden_case}', flight {i} [{flight_id}]: pipeline produced no output"
            )

        output = pipeline.flight_with_climate_impact.to_dataframe()
        expected = FlightWithClimateImpact.from_flight(
            expected_flight.copy()
        ).to_dataframe()

        # Compare dataframe columns
        assert_frame_equal(
            output[check_cols],
            expected[check_cols],
            rtol=rtol,
            atol=atol,
            check_dtype=False,
            obj=f"Case '{golden_case}', flight {i} [{flight_id}]",
        )

        # Compare climate_payload
        actual_payload = pipeline.flight_with_climate_impact.attrs.get(
            "climate_impact", {}
        )
        expected_payload = expected_flight.attrs.get("climate_impact", {})
        actual_rest, actual_contrails = _split_contrails(actual_payload)
        expected_rest, expected_contrails = _split_contrails(expected_payload)
        assert_climate_payload_equal(actual_rest, expected_rest, rtol=rtol)
        assert_climate_payload_equal(
            actual_contrails, expected_contrails, rtol=CONTRAIL_RTOL
        )
