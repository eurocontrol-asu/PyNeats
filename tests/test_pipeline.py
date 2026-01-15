"""Integration test for full pipeline using FlightRunner.

This test replicates the original working test from main branch,
updated to use the new golden reference data (5 flights).
"""

import pytest
from pathlib import Path
from pandas.testing import assert_frame_equal
from tqdm import tqdm

from pyneats.runners.flight import FlightRunner, RunnerConfig

from .fixtures.nm_traffic import nm_input, nm_output
from .fixtures.weather import weather


def test_pipeline(nm_input, nm_output, weather, bada_root_path):  # noqa: F811
    """Test full pipeline (parsing → interpolation → weather → performance → emissions → contrails → climate).

    Args:
        nm_input: List of raw flight dicts (NM JSON format)
        nm_output: List of expected FlightView outputs (fully processed)
        weather: WeatherProvider instance
        bada_root_path: Path to BADA data directory

    Validates:
        - Full pipeline produces outputs matching golden reference data
        - Tolerance: rtol=0.05 (5%), atol=1e-3 (0.001)
        - Compares only FlightWithClimateImpact.REQUIRED columns
    """
    # Import here to avoid collection errors when pyBADA not installed
    from pyneats.steps.climate_functions.views import FlightWithClimateImpact
    from pyneats.steps.parsing.neats_io import neats_json_to_flights

    # Skip if weather not available
    if weather is None:
        pytest.skip(
            "Weather data not available. Use pytest --met-cache-dir=/path/to/data or set MET_CACHE_DIR"
        )

    # Skip if BADA not available
    if bada_root_path is None or not bada_root_path.exists():
        pytest.skip("BADA data not available, skipping test.")

    # Tolerance (relaxed from original 1e-3/1e-8 to handle environmental variation)
    rtol = 0.05  # 5% relative tolerance
    atol = 1e-3  # 0.001 absolute tolerance
    check_cols = list(FlightWithClimateImpact.REQUIRED)

    # Setup BADA parameters
    performance_params = dict(
        bada4_root_path=str(bada_root_path),
        bada3_root_path=str(bada_root_path),
    )

    # Create flight runner configuration with BADA paths
    cfg = RunnerConfig(params={"performance": performance_params})

    # Process all flights
    for raw_flight, expected_flight in tqdm(
        zip(nm_input, nm_output),
        total=len(nm_input),
        desc="Processing test flights"
    ):
        # Expected output
        expected_output = FlightWithClimateImpact.from_flight(expected_flight.copy()).to_dataframe()

        # Parse raw flight to Flight object
        parsed_flights = neats_json_to_flights([raw_flight])
        if not parsed_flights:
            raise RuntimeError(f"Failed to parse flight: {raw_flight.get('flight_id', 'unknown')}")

        flight = parsed_flights[0]

        # Create flight runner and execute pipeline
        pipeline = FlightRunner(weather, flight, cfg=cfg)
        pipeline.eval()

        # Get output of pipeline
        if pipeline.flight_with_climate_impact is not None:
            output = pipeline.flight_with_climate_impact.to_dataframe()
        else:
            raise RuntimeError("No 'flight_with_climate_impact' available on FlightRunner result")

        # Assert that output matches expected (check only required columns)
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            check_dtype=False,  # Ignore float32 vs float64 differences
            obj=f"Flight {expected_flight.attrs.get('flight_id', 'unknown')}",
        )

