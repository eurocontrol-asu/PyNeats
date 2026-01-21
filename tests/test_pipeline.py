"""Test full pipeline using FlightRunner against golden reference data.

This module tests the FlightRunner pipeline by:
1. Loading input flights from golden test cases
2. Running each flight through the full pipeline
3. Comparing results against expected golden outputs

Golden test cases are auto-discovered from tests/data/golden/.
Each case has a {case_name}_input.json and {case_name}_output.json pair.
"""

from __future__ import annotations

from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from pyneats.core.views import FlightView
from pyneats.runners.flight import FlightRunner, RunnerConfig
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from tests.conftest import assert_climate_payload_equal

# Test cases that require FleetRunner (heterogeneous column/attr handling)
FLEET_RUNNER_ONLY_CASES = frozenset({"mixed_columns", "mixed_attrs"})


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
    from pyneats.steps.climate_functions.views import FlightWithClimateImpact

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
    for i, (df, expected_flight) in enumerate(zip(dataframes, golden_output, strict=True)):
        flight_id = expected_flight.attrs.get("flight_id", f"flight_{i}")
        if isinstance(flight_id, list):
            flight_id = flight_id[0] if flight_id else f"flight_{i}"

        # Run pipeline
        pipeline = FlightRunner(weather, df, cfg=cfg)
        pipeline.eval()

        # Get output
        if pipeline.flight_with_climate_impact is None:
            pytest.fail(
                f"Case '{golden_case}', flight {i} [{flight_id}]: pipeline produced no output"
            )

        output = pipeline.flight_with_climate_impact.to_dataframe()
        expected = FlightWithClimateImpact.from_flight(expected_flight.copy()).to_dataframe()

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
        actual_payload = pipeline.flight_with_climate_impact.attrs.get("climate_impact", {})
        expected_payload = expected_flight.attrs.get("climate_impact", {})
        assert_climate_payload_equal(
            actual_payload,
            expected_payload,
            rtol=rtol,
        )
