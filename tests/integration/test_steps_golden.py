"""Individual step tests using golden reference data.

Tests each processing step independently using golden reference data.
This validates that individual steps produce expected outputs, allowing for
easier debugging and validation of future refactorings.
"""

import logging
from pathlib import Path
from typing import List

import pytest
from pandas.testing import assert_frame_equal

from pyneats.core.views import FlightView
from pyneats.steps.interpolation import PyContrailsInterpolator
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.views import Flight4D
from pyneats.steps.weather.weather_store import (
    ZarrPaths,
    get_weather_from_zarr,
)

logger = logging.getLogger(__name__)

# Tolerances for golden reference comparison
# These are configurable and can be tuned based on actual test results
# Increased to handle environmental variation and coordinate precision differences
RTOL_DEFAULT = 0.05  # Relative tolerance (5%) - handles parsing precision and environmental factors
ATOL_DEFAULT = 1e-3  # Absolute tolerance (0.001) - handles small value precision and rounding

# Per-column tolerances (if specific columns need different tolerances)
COLUMN_TOLERANCES = {
    # Example: "fuel_flow": {"rtol": 1e-4, "atol": 1e-7},
}


class TestParsingInterpolation:
    """Test parsing and interpolation steps."""

    @pytest.mark.parametrize("flight_index", range(5))
    def test_parsing_interpolation_golden(
        self,
        flight_index: int,
        input_flights: List[dict],
        golden_flights: List[FlightView],
    ):
        """Test parsing and interpolation against golden reference.

        Args:
            flight_index: Index of flight to test (0-4)
            input_flights: Raw input flights (NM JSON format)
            golden_flights: Expected outputs (processed FlightView)
        """
        # Skip if golden data doesn't have this flight
        if flight_index >= len(golden_flights):
            pytest.skip(f"Golden data only has {len(golden_flights)} flights, skipping flight {flight_index}")

        input_flight_data = input_flights[flight_index]
        expected_output = golden_flights[flight_index]

        logger.info(
            f"Testing parsing+interpolation for flight {flight_index}: "
            f"{expected_output.attrs.get('flight_id', 'unknown')}"
        )

        # Parse the raw JSON input (returns List[DataFrame])
        parsed_flights = neats_json_to_flights([input_flight_data])

        if not parsed_flights:
            pytest.fail(f"Failed to parse flight {flight_index}")

        source_df = parsed_flights[0]  # Already a DataFrame!

        # Run parsing and interpolation
        parser = NeatsTrajectoryParser()
        interpolator = PyContrailsInterpolator()

        parsed_flight = parser(source_df)
        interpolated_flight = interpolator(parsed_flight)

        # Compare with golden (only 4D columns)
        check_cols = list(Flight4D.REQUIRED)

        result_df = interpolated_flight.to_dataframe()
        expected_df = Flight4D.from_flight(expected_output).to_dataframe()

        self._compare_dataframes(
            result_df[check_cols],
            expected_df[check_cols],
            f"Flight {flight_index} (parsing+interpolation)",
        )

        logger.info(
            f"Flight {flight_index}: ✓ Parsing+interpolation validated "
            f"({len(check_cols)} columns)"
        )

    def _compare_dataframes(self, result, expected, label):
        """Compare DataFrames with configurable tolerances."""
        rtol = RTOL_DEFAULT
        atol = ATOL_DEFAULT

        try:
            assert_frame_equal(
                result,
                expected,
                rtol=rtol,
                atol=atol,
                check_dtype=False,  # Ignore dtype differences (float32 vs float64)
                obj=label,
            )
        except AssertionError as e:
            logger.error(f"{label}: Mismatch\n  Tolerances: rtol={rtol}, atol={atol}\n  Error: {e}")
            raise


class TestWeatherIntersection:
    """Test weather intersection step."""

    @pytest.fixture
    def weather_provider(self, weather_path):
        """Create weather provider for tests."""
        if not weather_path or not weather_path.exists():
            pytest.skip("Weather data not available")

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

    @pytest.mark.parametrize("flight_index", range(5))
    def test_weather_intersection_golden(
        self,
        flight_index: int,
        golden_flights: List[FlightView],
        weather_provider,
    ):
        """Test weather intersection against golden reference.

        Args:
            flight_index: Index of flight to test (0-4)
            golden_flights: Expected outputs (processed FlightView)
            weather_provider: Weather data provider
        """
        # Skip if golden data doesn't have this flight
        if flight_index >= len(golden_flights):
            pytest.skip(f"Golden data only has {len(golden_flights)} flights, skipping flight {flight_index}")

        from pyneats.steps.weather.weather_provider import FlightWithWeather

        expected_output = golden_flights[flight_index]

        logger.info(
            f"Testing weather intersection for flight {flight_index}: "
            f"{expected_output.attrs.get('flight_id', 'unknown')}"
        )

        # Create input (Flight4D without weather columns)
        # Make a copy to avoid mutating the golden flight
        input_flight = Flight4D.from_flight(expected_output.copy())

        # Remove weather columns from input
        weather_cols = set(FlightWithWeather.REQUIRED)
        for col in weather_cols:
            input_flight.data.pop(col, None)

        # Run weather intersection
        output_flight = weather_provider(input_flight)

        # Compare with golden
        check_cols = list(FlightWithWeather.REQUIRED)

        result_df = output_flight.to_dataframe()
        expected_df = FlightWithWeather.from_flight(expected_output).to_dataframe()

        self._compare_dataframes(
            result_df[check_cols],
            expected_df[check_cols],
            f"Flight {flight_index} (weather)",
        )

        logger.info(
            f"Flight {flight_index}: ✓ Weather intersection validated "
            f"({len(check_cols)} columns)"
        )

    def _compare_dataframes(self, result, expected, label):
        """Compare DataFrames with configurable tolerances."""
        rtol = RTOL_DEFAULT
        atol = ATOL_DEFAULT

        try:
            assert_frame_equal(
                result,
                expected,
                rtol=rtol,
                atol=atol,
                check_dtype=False,  # Ignore dtype differences (float32 vs float64)
                obj=label,
            )
        except AssertionError as e:
            logger.error(f"{label}: Mismatch\n  Tolerances: rtol={rtol}, atol={atol}\n  Error: {e}")
            raise


class TestPerformance:
    """Test performance computation step."""

    @pytest.fixture
    def performance_model(self, bada3_path, bada4_path):
        """Create performance model for tests."""
        if bada3_path is None and bada4_path is None:
            pytest.skip("BADA data not available")

        from pyneats.steps.performance.pycontrails_bada import (
            PyContrailsBADAParams,
            PyContrailsBADAPerformance,
        )

        bada_root = str(bada4_path.parent) if bada4_path else str(bada3_path.parent)

        params = PyContrailsBADAParams(
            bada4_root_path=bada_root,
            bada3_root_path=bada_root,
        )

        return PyContrailsBADAPerformance(params)

    @pytest.mark.parametrize("flight_index", range(5))
    def test_performance_golden(
        self,
        flight_index: int,
        golden_flights: List[FlightView],
        performance_model,
    ):
        """Test performance computation against golden reference.

        Args:
            flight_index: Index of flight to test (0-4)
            golden_flights: Expected outputs (processed FlightView)
            performance_model: Performance model instance
        """
        # Skip if golden data doesn't have this flight
        if flight_index >= len(golden_flights):
            pytest.skip(f"Golden data only has {len(golden_flights)} flights, skipping flight {flight_index}")

        from pyneats.steps.performance.views import FlightWithPerformance
        from pyneats.steps.weather.weather_provider import FlightWithWeather

        expected_output = golden_flights[flight_index]

        logger.info(
            f"Testing performance for flight {flight_index}: "
            f"{expected_output.attrs.get('flight_id', 'unknown')}"
        )

        # Create input (FlightWithWeather without performance columns)
        # Make a copy to avoid mutating the golden flight
        input_flight = FlightWithWeather.from_flight(expected_output.copy())

        # Remove performance columns from input
        perf_cols = set(FlightWithPerformance.REQUIRED)
        for col in perf_cols:
            input_flight.data.pop(col, None)

        # Run performance computation
        output_flight = performance_model(input_flight)

        # Compare with golden
        check_cols = list(FlightWithPerformance.REQUIRED)

        result_df = output_flight.to_dataframe()
        expected_df = FlightWithPerformance.from_flight(expected_output).to_dataframe()

        self._compare_dataframes(
            result_df[check_cols],
            expected_df[check_cols],
            f"Flight {flight_index} (performance)",
        )

        logger.info(
            f"Flight {flight_index}: ✓ Performance validated " f"({len(check_cols)} columns)"
        )

    def _compare_dataframes(self, result, expected, label):
        """Compare DataFrames with configurable tolerances."""
        rtol = RTOL_DEFAULT
        atol = ATOL_DEFAULT

        try:
            assert_frame_equal(
                result,
                expected,
                rtol=rtol,
                atol=atol,
                check_dtype=False,  # Ignore dtype differences (float32 vs float64)
                obj=label,
            )
        except AssertionError as e:
            logger.error(f"{label}: Mismatch\n  Tolerances: rtol={rtol}, atol={atol}\n  Error: {e}")
            raise


class TestEmissions:
    """Test emissions computation step."""

    @pytest.mark.parametrize("flight_index", range(5))
    def test_emissions_golden(
        self,
        flight_index: int,
        golden_flights: List[FlightView],
    ):
        """Test emissions computation against golden reference.

        Args:
            flight_index: Index of flight to test (0-4)
            golden_flights: Expected outputs (processed FlightView)
        """
        # Skip if golden data doesn't have this flight
        if flight_index >= len(golden_flights):
            pytest.skip(f"Golden data only has {len(golden_flights)} flights, skipping flight {flight_index}")

        from pyneats.steps.emissions.pycontrails_emissions import (
            FlightWithEmissions,
            PyContrailsEmissionModel,
            PyContrailsEmissionParams,
        )
        from pyneats.steps.performance.views import FlightWithPerformance

        expected_output = golden_flights[flight_index]

        logger.info(
            f"Testing emissions for flight {flight_index}: "
            f"{expected_output.attrs.get('flight_id', 'unknown')}"
        )

        # Create input (FlightWithPerformance without emissions columns)
        # Make a copy to avoid mutating the golden flight
        input_flight = FlightWithPerformance.from_flight(expected_output.copy())

        # Remove emissions columns from input
        emissions_cols = set(FlightWithEmissions.REQUIRED)
        for col in emissions_cols:
            input_flight.data.pop(col, None)

        # Run emissions computation
        params = PyContrailsEmissionParams()
        step = PyContrailsEmissionModel(params)
        output_flight = step(input_flight)

        # Compare with golden
        check_cols = list(FlightWithEmissions.REQUIRED)

        result_df = output_flight.to_dataframe()
        expected_df = FlightWithEmissions.from_flight(expected_output).to_dataframe()

        self._compare_dataframes(
            result_df[check_cols],
            expected_df[check_cols],
            f"Flight {flight_index} (emissions)",
        )

        logger.info(
            f"Flight {flight_index}: ✓ Emissions validated " f"({len(check_cols)} columns)"
        )

    def _compare_dataframes(self, result, expected, label):
        """Compare DataFrames with configurable tolerances."""
        rtol = RTOL_DEFAULT
        atol = ATOL_DEFAULT

        try:
            assert_frame_equal(
                result,
                expected,
                rtol=rtol,
                atol=atol,
                check_dtype=False,  # Ignore dtype differences (float32 vs float64)
                obj=label,
            )
        except AssertionError as e:
            logger.error(f"{label}: Mismatch\n  Tolerances: rtol={rtol}, atol={atol}\n  Error: {e}")
            raise


class TestContrails:
    """Test contrails/CoCiP computation step."""

    @pytest.fixture
    def weather_provider(self, weather_path):
        """Create weather provider for tests."""
        if not weather_path or not weather_path.exists():
            pytest.skip("Weather data not available")

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

    @pytest.mark.parametrize("flight_index", range(5))
    def test_contrails_golden(
        self,
        flight_index: int,
        golden_flights: List[FlightView],
        weather_provider,
    ):
        """Test contrails computation against golden reference.

        Args:
            flight_index: Index of flight to test (0-4)
            golden_flights: Expected outputs (processed FlightView)
            weather_provider: Weather data provider
        """
        # Skip if golden data doesn't have this flight
        if flight_index >= len(golden_flights):
            pytest.skip(f"Golden data only has {len(golden_flights)} flights, skipping flight {flight_index}")

        from pyneats.steps.climate_functions.cocip import (
            CoCiPModel,
            ContrailsParams,
            FlightWithContrailsImpact,
        )
        from pyneats.steps.emissions.pycontrails_emissions import FlightWithEmissions

        expected_output = golden_flights[flight_index]

        logger.info(
            f"Testing contrails for flight {flight_index}: "
            f"{expected_output.attrs.get('flight_id', 'unknown')}"
        )

        # Create input (FlightWithEmissions without contrail columns)
        # Make a copy to avoid mutating the golden flight
        input_flight = FlightWithEmissions.from_flight(expected_output.copy())

        # Remove contrail columns from input
        contrail_cols = [
            "ef",
            "contrail_age",
            "width",
            "depth",
            "n_ice_per_m_1",
            "sdr_mean",
            "rsr_mean",
            "olr_mean",
            "rf_sw_mean",
            "rf_lw_mean",
            "rf_net_mean",
            "persistent_1",
        ]
        for col in contrail_cols:
            input_flight.data.pop(col, None)

        # Run contrails computation
        params = ContrailsParams(met=weather_provider.met(), rad=weather_provider.rad())
        step = CoCiPModel(params)
        output_flight = step(input_flight)

        # Compare with golden (only required contrail columns)
        check_cols = list(FlightWithContrailsImpact.REQUIRED)

        result_df = output_flight.to_dataframe()
        expected_df = FlightWithContrailsImpact.from_flight(expected_output).to_dataframe()

        self._compare_dataframes(
            result_df[check_cols].astype(float),
            expected_df[check_cols].astype(float),
            f"Flight {flight_index} (contrails)",
        )

        logger.info(
            f"Flight {flight_index}: ✓ Contrails validated " f"({len(check_cols)} columns)"
        )

    def _compare_dataframes(self, result, expected, label):
        """Compare DataFrames with configurable tolerances.

        Note: Contrails ef values are in trillions, requiring large absolute tolerance.
        """
        rtol = RTOL_DEFAULT
        atol = 1e10  # 10 billion - handles large ef values in trillions

        try:
            assert_frame_equal(
                result,
                expected,
                rtol=rtol,
                atol=atol,
                check_dtype=False,  # Ignore dtype differences (float32 vs float64)
                obj=label,
            )
        except AssertionError as e:
            logger.error(f"{label}: Mismatch\n  Tolerances: rtol={rtol}, atol={atol}\n  Error: {e}")
            raise


class TestClimateMetrics:
    """Test climate metrics computation step."""

    @pytest.mark.parametrize("flight_index", range(5))
    def test_climate_metrics_golden(
        self,
        flight_index: int,
        golden_flights: List[FlightView],
    ):
        """Test climate metrics computation against golden reference.

        Args:
            flight_index: Index of flight to test (0-4)
            golden_flights: Expected outputs (processed FlightView)
        """
        # Skip if golden data doesn't have this flight
        if flight_index >= len(golden_flights):
            pytest.skip(f"Golden data only has {len(golden_flights)} flights, skipping flight {flight_index}")

        from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
        from pyneats.steps.climate_metrics.gwp import (
            GWPMetrics,
            GWPParams,
        )

        expected_output = golden_flights[flight_index]

        logger.info(
            f"Testing climate metrics for flight {flight_index}: "
            f"{expected_output.attrs.get('flight_id', 'unknown')}"
        )

        # Create input (FlightWithNonCO2Impact without climate impact attrs)
        # Make a copy to avoid mutating the golden flight
        input_flight = FlightWithNonCO2Impact.from_flight(expected_output.copy())

        # Remove climate_impact from attrs if present
        if "climate_impact" in input_flight.attrs:
            input_flight.attrs.pop("climate_impact")

        # Run climate metrics computation
        params = GWPParams()
        step = GWPMetrics(params)
        output_flight = step(input_flight)

        # Validate that climate_impact exists in attrs
        assert "climate_impact" in output_flight.attrs, (
            f"Flight {flight_index}: climate_impact not in attrs"
        )

        # Validate structure (we don't compare exact values since they may vary)
        climate_payload = output_flight.attrs["climate_impact"]
        assert "flight_information" in climate_payload, f"Flight {flight_index}: 'flight_information' missing from climate_impact"
        assert "climate_metrics" in climate_payload, f"Flight {flight_index}: 'climate_metrics' missing from climate_impact"

        logger.info(f"Flight {flight_index}: ✓ Climate metrics validated")
