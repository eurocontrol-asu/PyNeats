"""Test full fleet pipeline using FleetRunner against golden reference data.

This module tests the FleetRunner pipeline by:
1. Loading input flights from golden test cases
2. Running the full fleet through the pipeline
3. Comparing results against expected golden outputs

Golden test cases are auto-discovered from tests/data/golden/.
Each case has a {case_name}_input.json and {case_name}_output.json pair.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pandas.testing import assert_frame_equal

from pyneats.core.views import FlightView
from pyneats.runners.fleet import FleetRunner, FleetRunnerParams
from pyneats.steps.weather.weather_store import ZarrPaths
from tests.conftest import assert_climate_payload_equal


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_fleet_runner_golden(
    golden_case: str,
    golden_input_path: Path,
    golden_output: list[FlightView],
    weather,
    weather_path,
    bada_root_path,
):
    """Test FleetRunner produces golden outputs for each case.

    Runs all flights in the golden case through FleetRunner and compares
    the outputs with expected results.
    """
    # Import here to avoid collection errors when pyBADA not installed
    from pyneats.steps.climate_functions.views import FlightWithClimateImpact

    # Skip if dependencies not available
    if weather is None:
        pytest.skip("Weather data not available")
    if bada_root_path is None or not bada_root_path.exists():
        pytest.skip("BADA data not available")
    if weather_path is None:
        pytest.skip("Weather path not available")

    # Test configuration
    rtol = 1e-3  # 0.1% relative tolerance
    atol = float("inf")  # No absolute tolerance limit
    check_cols = list(FlightWithClimateImpact.REQUIRED)

    # Setup Zarr paths
    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"
    if not wind_store.is_dir():
        wind_store = None

    zarr_paths = ZarrPaths(met_store, rad_store, wind_store)

    # Create FleetRunner configuration
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(golden_input_path),
        zarr_paths=zarr_paths,
        bada_path=str(bada_root_path),
        params={},
    )

    # Run FleetRunner
    runner = FleetRunner(cfg)
    runner.eval()

    # Verify we got results
    if runner.fleet_with_climate_impact is None:
        pytest.fail(f"Case '{golden_case}': FleetRunner produced no output")

    output_flights = runner.fleet_with_climate_impact

    # Check we got the expected number of flights
    assert len(output_flights) == len(golden_output), (
        f"Case '{golden_case}': FleetRunner produced {len(output_flights)} flights, "
        f"expected {len(golden_output)}. Errors: {runner.error_records}"
    )

    # Compare each output flight with expected
    for i, (output_flight, expected_flight) in enumerate(
        zip(output_flights, golden_output, strict=True)
    ):
        flight_id = output_flight.attrs.get("flight_id", f"flight_{i}")
        if isinstance(flight_id, list):
            flight_id = flight_id[0] if flight_id else f"flight_{i}"

        output = output_flight.to_dataframe()
        expected = FlightWithClimateImpact.from_flight(expected_flight.copy()).to_dataframe()

        assert_frame_equal(
            output[check_cols],
            expected[check_cols],
            rtol=rtol,
            atol=atol,
            check_dtype=False,
            obj=f"Case '{golden_case}', flight {i} [{flight_id}]",
        )

        # Compare climate_payload
        actual_payload = output_flight.attrs.get("climate_impact", {})
        expected_payload = expected_flight.attrs.get("climate_impact", {})
        assert_climate_payload_equal(
            actual_payload,
            expected_payload,
            rtol=rtol,
        )
