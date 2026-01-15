"""Golden reference tests for regression validation.

These tests ensure current implementation produces expected results by comparing
against golden reference data (input_flights_5.json → output_flights_5.json).

These tests will be critical for validating Phase 1+2 refactoring later
(comparing Fleet-only vs DataFrame implementations).
"""

import logging
from pathlib import Path
from typing import List

import pytest
from pandas.testing import assert_frame_equal

from pyneats.core.views import FlightView
from pyneats.steps.weather.weather_store import (
    ZarrPaths,
    get_weather_from_zarr,
)

logger = logging.getLogger(__name__)

# Tolerances for golden reference comparison
# These are configurable and can be tuned based on actual test results
RTOL_DEFAULT = 1e-5  # Relative tolerance (0.001%)
ATOL_DEFAULT = 1e-8  # Absolute tolerance

# Per-column tolerances (if specific columns need different tolerances)
COLUMN_TOLERANCES = {
    # Example: "fuel_flow": {"rtol": 1e-4, "atol": 1e-7},
}


class TestFlightRunnerGoldenReference:
    """Test FlightRunner against golden reference data."""

    @pytest.fixture
    def weather_provider(self, weather_path):
        """Create weather provider for tests."""
        if not weather_path or not weather_path.exists():
            pytest.skip("Weather data not available")

        from pyneats.steps.weather.weather_provider import WeatherProvider

        met_store = weather_path / "icon_met.zarr"
        rad_store = weather_path / "icon_rad.zarr"

        if not met_store.is_dir() or not rad_store.is_dir():
            pytest.skip("Weather zarr stores not available")

        zarr_paths = ZarrPaths(
            met_store=str(met_store),
            rad_store=str(rad_store),
        )

        # Load weather data (returns WeatherProvider directly)
        weather = get_weather_from_zarr(zarr_paths)

        return weather

    @pytest.fixture
    def runner_config(self, bada3_path, bada4_path):
        """Create runner configuration with BADA paths."""
        if bada3_path is None and bada4_path is None:
            pytest.skip("BADA data not available")

        from pyneats.runners.flight import RunnerConfig

        # Prefer BADA4, fall back to BADA3
        bada_root = str(bada4_path.parent) if bada4_path else str(bada3_path.parent)

        # Configure BADA paths
        performance_params = {
            "bada4_root_path": bada_root,
            "bada3_root_path": bada_root,
        }

        cfg = RunnerConfig(params={"performance": performance_params})

        return cfg

    @pytest.mark.parametrize("flight_index", range(5))
    def test_single_flight_golden_reference(
        self,
        flight_index: int,
        input_flights: List[dict],
        golden_flights: List[FlightView],
        weather_provider,
        runner_config,
    ):
        """Test single flight processing against golden reference.

        This test processes one flight at a time through FlightRunner
        and validates the output matches the golden reference data.

        Args:
            flight_index: Index of flight to test (0-4)
            input_flights: Raw input flights (NM JSON format)
            golden_flights: Expected outputs (processed FlightView)
            weather_provider: Weather data provider
            runner_config: Runner configuration with BADA paths
        """
        # Skip if golden data doesn't have this flight
        if flight_index >= len(golden_flights):
            pytest.skip(f"Golden data only has {len(golden_flights)} flights, skipping flight {flight_index}")

        # Get input and expected output
        from pyneats.runners.flight import FlightRunner
        from pyneats.steps.climate_functions.views import FlightWithClimateImpact
        from pyneats.steps.parsing.neats_io import neats_json_to_flights

        input_flight_data = input_flights[flight_index]
        expected_output = golden_flights[flight_index]

        logger.info(f"Testing flight {flight_index}: {expected_output.attrs.get('flight_id', 'unknown')}")

        # Parse input (returns List[DataFrame])
        parsed_flights = neats_json_to_flights([input_flight_data])

        if not parsed_flights:
            pytest.fail(f"Failed to parse flight {flight_index}")

        source_df = parsed_flights[0]  # Already a DataFrame!

        # Create and run pipeline
        runner = FlightRunner(
            weather=weather_provider,
            source=source_df,
            cfg=runner_config,
        )

        result_runner = runner.eval()

        # Get final output
        if result_runner.flight_with_climate_impact is None:
            pytest.fail(f"Flight {flight_index}: No climate impact result")

        result_flight = result_runner.flight_with_climate_impact

        # Validate result
        self._compare_flights(
            result_flight,
            FlightWithClimateImpact.from_flight(expected_output),
            flight_index,
        )

    def _compare_flights(
        self,
        result,
        expected,
        flight_index: int,
    ):
        """Compare result flight against expected golden output.

        Args:
            result: Computed flight result (FlightWithClimateImpact)
            expected: Golden reference flight (FlightWithClimateImpact)
            flight_index: Flight index (for error messages)
        """
        # Get columns to check (all columns from golden reference)
        result_df = result.to_dataframe()
        expected_df = expected.to_dataframe()

        # Get common columns (in case result has extra columns)
        common_cols = list(set(result_df.columns) & set(expected_df.columns))

        if not common_cols:
            pytest.fail(
                f"Flight {flight_index}: No common columns between result and expected.\n"
                f"Result columns: {list(result_df.columns)}\n"
                f"Expected columns: {list(expected_df.columns)}"
            )

        # Sort columns for consistent comparison
        common_cols = sorted(common_cols)

        logger.info(f"Flight {flight_index}: Comparing {len(common_cols)} columns")

        # Compare DataFrames
        for col in common_cols:
            # Get column-specific tolerances or use defaults
            tolerances = COLUMN_TOLERANCES.get(col, {})
            rtol = tolerances.get("rtol", RTOL_DEFAULT)
            atol = tolerances.get("atol", ATOL_DEFAULT)

            try:
                assert_frame_equal(
                    result_df[[col]],
                    expected_df[[col]],
                    rtol=rtol,
                    atol=atol,
                    obj=f"Flight {flight_index}, column '{col}'",
                )
            except AssertionError as e:
                logger.error(
                    f"Flight {flight_index}: Column '{col}' mismatch\n"
                    f"  Tolerances: rtol={rtol}, atol={atol}\n"
                    f"  Error: {e}"
                )
                raise

        logger.info(f"Flight {flight_index}: ✓ All {len(common_cols)} columns match")

    def test_all_flights_golden_reference(
        self,
        input_flights: List[dict],
        golden_flights: List[FlightView],
        weather_provider,
        runner_config,
    ):
        """Test all flights in sequence.

        This is a comprehensive test that processes all available flights and
        validates against golden reference data.
        """
        # Use minimum of input and golden flights
        num_flights = min(len(input_flights), len(golden_flights))

        if num_flights < len(input_flights):
            logger.warning(
                f"Only {num_flights} golden flights available, "
                f"but {len(input_flights)} input flights. Testing first {num_flights}."
            )

        logger.info(f"Testing {num_flights} flights against golden reference")

        for idx in range(num_flights):
            logger.info(f"Processing flight {idx + 1}/{num_flights}")

            self.test_single_flight_golden_reference(
                flight_index=idx,
                input_flights=input_flights,
                golden_flights=golden_flights,
                weather_provider=weather_provider,
                runner_config=runner_config,
            )

        logger.info(f"✓ All {num_flights} flights passed golden reference validation")


# Note: FleetRunner tests can be added later
# For now, focus on FlightRunner validation
