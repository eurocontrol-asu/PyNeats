"""Test full fleet pipeline using FleetRunner against golden reference data.

This module tests the FleetRunner pipeline by:
1. Loading input flights from golden test cases
2. Running the full fleet through the pipeline
3. Comparing results against expected golden outputs

Golden test cases are auto-discovered from tests/data/golden/.
Each case has a {case_name}_input.json and {case_name}_output.json pair.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyneats.core.views import FlightView
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.weather.weather_store import ZarrPaths
from tests.golden_compare import GOLDEN_RTOL
from tests.golden_compare import assert_matches_golden


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_fleet_runner_golden(
    golden_case: str,
    golden_input_path: Path,
    golden_output_path: Path,
    golden_output: list[FlightView],
    weather,
    weather_path,
    bada_path,
):
    """Test FleetRunner produces golden outputs for each case.

    Runs all flights in the golden case through FleetRunner and compares
    each output flight (``FlightView.to_dict``) with its golden record:
    the same keys, every per-point column and flight-level attribute at
    ``GOLDEN_RTOL``, and the climate payload (``tests/golden_compare.py``).
    """
    # Skip if dependencies not available
    if weather is None:
        pytest.skip("Weather data not available")
    if bada_path is None or not bada_path.exists():
        pytest.skip("BADA data not available")
    if weather_path is None:
        pytest.skip("Weather path not available")

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
        bada_path=str(bada_path),
        params={},
    )

    # Run FleetRunner
    runner = FleetRunnerLargeEmitter(cfg)
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

    # Compare each output flight with its golden record (same JSON layout)
    with open(golden_output_path, encoding="utf-8") as fh:
        golden_records = json.load(fh)
    for i, (output_flight, expected_record) in enumerate(
        zip(output_flights, golden_records, strict=True)
    ):
        flight_id = output_flight.attrs.get("flight_id", f"flight_{i}")
        if isinstance(flight_id, list):
            flight_id = flight_id[0] if flight_id else f"flight_{i}"

        assert_matches_golden(
            output_flight.to_dict(),
            expected_record,
            rtol=GOLDEN_RTOL,
            label=f"Case '{golden_case}', flight {i} [{flight_id}]",
        )
