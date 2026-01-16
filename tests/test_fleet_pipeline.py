"""Test full fleet pipeline using FleetRunner."""

from pathlib import Path

import pytest
from pandas.testing import assert_frame_equal

from pyneats.runners.fleet import FleetRunner, FleetRunnerParams
from pyneats.steps.weather.weather_store import ZarrPaths

from .fixtures.nm_traffic import nm_output  # noqa: F401
from .fixtures.weather import weather  # noqa: F401


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_fleet_pipeline(nm_output, weather, weather_path, bada_root_path):  # noqa: F811
    """Test full FleetRunner pipeline with all 5 flights.

    Loads raw input from tests/data/input_flights_5.json, runs full FleetRunner
    pipeline, and compares fleet_with_climate_impact output with expected
    FlightWithClimateImpact results from golden data.
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

    rtol = 1e-3  # 0.1% relative tolerance (same as test_pipeline)
    atol = float("inf")  # Absolute tolerance (same as test_pipeline)
    check_cols = list(FlightWithClimateImpact.REQUIRED)

    # Setup input JSON path (all 5 flights)
    input_json_path = Path(__file__).parent / "data" / "input_flights_5.json"
    assert input_json_path.exists(), f"Input file not found: {input_json_path}"

    # Setup zarr paths from weather fixture
    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"
    if not wind_store.is_dir():
        wind_store = None  # optional

    zarr_paths = ZarrPaths(met_store, rad_store, wind_store)

    # Create FleetRunnerParams
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(input_json_path),
        zarr_paths=zarr_paths,
        bada_path=str(bada_root_path),
        params={},  # Use defaults
    )

    # Create and run FleetRunner
    runner = FleetRunner(cfg)
    runner.eval()

    # Verify we got results
    if runner.fleet_with_climate_impact is None:
        raise RuntimeError("No 'fleet_with_climate_impact' available on FleetRunner result")

    # Should have all 5 flights (or fewer if some failed)
    output_flights = runner.fleet_with_climate_impact
    assert len(output_flights) > 0, "FleetRunner produced no output flights"

    # Compare each output flight with expected golden data
    # Note: FleetRunner may have fewer flights if some failed, so match by index
    for i, output_flight in enumerate(output_flights):
        if i >= len(nm_output):
            break  # More outputs than expected (shouldn't happen)

        expected_flight = nm_output[i]
        expected_output = FlightWithClimateImpact.from_flight(expected_flight.copy()).to_dataframe()
        output_df = output_flight.to_dataframe()

        # Get flight_id for better error messages
        flight_id_list = output_flight.attrs.get("flight_id", [f"flight_{i}"])
        flight_id = flight_id_list[0] if isinstance(flight_id_list, list) else flight_id_list

        # Assert that output matches expected
        assert_frame_equal(
            output_df[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            check_dtype=False,
            obj=f"Fleet flight {i} [{flight_id}] (full fleet pipeline)",
        )

    # Verify we processed all expected flights
    assert len(output_flights) == len(nm_output), (
        f"FleetRunner produced {len(output_flights)} flights, expected {len(nm_output)}. "
        f"Check runner.error_records for failures: {runner.error_records}"
    )
