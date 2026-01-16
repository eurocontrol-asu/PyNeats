"""Test full pipeline using FlightRunner."""

import pytest
from pandas.testing import assert_frame_equal

from pyneats.runners.flight import FlightRunner, RunnerConfig
from pyneats.steps.parsing.neats_io import neats_json_to_flights

from .fixtures.nm_traffic import nm_input, nm_output  # noqa: F401
from .fixtures.weather import weather  # noqa: F401


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_pipeline(nm_input, nm_output, weather, bada_root_path, flight_idx):  # noqa: F811
    """Test full pipeline for individual flights.

    Parses raw input, runs full FlightRunner pipeline, and compares
    with expected FlightWithClimateImpact output from golden data.
    """
    # Import here to avoid collection errors when pyBADA not installed
    from pyneats.steps.climate_functions.views import FlightWithClimateImpact

    # Skip if weather not available
    if weather is None:
        pytest.skip(
            "Weather data not available. Use pytest --met-cache-dir=/path/to/data or set MET_CACHE_DIR"  # noqa: E501
        )

    # Skip if BADA not available
    if bada_root_path is None or not bada_root_path.exists():
        pytest.skip("BADA data not available")

    rtol = 1e-3  # 0.1% relative tolerance (same as main branch)
    atol = float("inf")  # Absolute tolerance (same as main branch)
    check_cols = list(FlightWithClimateImpact.REQUIRED)

    # Setup BADA parameters
    performance_params = {
        "bada4_root_path": str(bada_root_path),
        "bada3_root_path": str(bada_root_path),
    }

    cfg = RunnerConfig(params={"performance": performance_params})

    # Get input and expected output for this flight
    raw_flight = nm_input[flight_idx]
    expected_flight = nm_output[flight_idx]
    expected_output = FlightWithClimateImpact.from_flight(expected_flight.copy()).to_dataframe()

    # Convert JSON to DataFrame, then parse to Flight

    dataframes = neats_json_to_flights([raw_flight])
    assert len(dataframes) == 1, "neats_json_to_flights should return 1 DataFrame"

    df = dataframes[0]

    # Create flight runner
    pipeline = FlightRunner(weather, df, cfg=cfg)
    pipeline.eval()

    # Get output of pipeline
    if pipeline.flight_with_climate_impact is not None:
        output = pipeline.flight_with_climate_impact.to_dataframe()
    else:
        raise RuntimeError("No 'flight_with_climate_impact' available on FlightRunner result")

    # Assert that input matches output
    assert_frame_equal(
        output[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (full pipeline)",
    )
