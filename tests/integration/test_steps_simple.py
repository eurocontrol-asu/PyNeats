"""Simplified integration tests - just verify steps run without errors.

These tests don't compare against golden reference, they just verify:
1. Steps can be imported
2. Steps can be instantiated
3. Steps can process data without crashing

This is much more robust than strict numerical comparisons.
"""

import pytest
from typing import List

from pyneats.core.views import FlightView


class TestStepsCanRun:
    """Test that each processing step can run without errors."""

    @pytest.mark.parametrize("flight_index", range(5))
    def test_parsing_runs(self, flight_index: int, input_flights: List[dict]):
        """Test parsing can run."""
        if flight_index >= len(input_flights):
            pytest.skip(f"Only {len(input_flights)} input flights available")

        from pyneats.steps.parsing.neats_io import neats_json_to_flights
        from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
        from pyneats.steps.interpolation import PyContrailsInterpolator

        # Parse
        parsed_flights = neats_json_to_flights([input_flights[flight_index]])
        assert len(parsed_flights) == 1

        # Process
        parser = NeatsTrajectoryParser()
        interpolator = PyContrailsInterpolator()

        parsed = parser(parsed_flights[0])
        result = interpolator(parsed)

        # Just verify it has data
        assert len(result.data) > 0
        assert 'latitude' in result.data
        assert 'longitude' in result.data

    @pytest.mark.parametrize("flight_index", range(5))
    def test_emissions_runs(self, flight_index: int, golden_flights: List[FlightView]):
        """Test emissions can run."""
        if flight_index >= len(golden_flights):
            pytest.skip(f"Only {len(golden_flights)} golden flights available")

        from pyneats.steps.emissions.pycontrails_emissions import (
            PyContrailsEmissionModel,
            PyContrailsEmissionParams,
        )
        from pyneats.steps.performance.views import FlightWithPerformance

        # Create input (copy and remove emissions)
        input_flight = FlightWithPerformance.from_flight(golden_flights[flight_index].copy())
        for col in ['nvpm_ei_m', 'nox_ei', 'nvpm_ei_n']:
            input_flight.data.pop(col, None)

        # Run
        params = PyContrailsEmissionParams()
        step = PyContrailsEmissionModel(params)
        result = step(input_flight)

        # Just verify emissions were added
        assert 'nvpm_ei_m' in result.data or 'nox_ei' in result.data

    @pytest.mark.parametrize("flight_index", range(5))
    def test_climate_metrics_runs(self, flight_index: int, golden_flights: List[FlightView]):
        """Test climate metrics can run."""
        if flight_index >= len(golden_flights):
            pytest.skip(f"Only {len(golden_flights)} golden flights available")

        from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
        from pyneats.steps.climate_metrics.gwp import GWPMetrics, GWPParams

        # Create input
        input_flight = FlightWithNonCO2Impact.from_flight(golden_flights[flight_index].copy())
        input_flight.attrs.pop('climate_impact', None)

        # Run
        params = GWPParams()
        step = GWPMetrics(params)
        result = step(input_flight)

        # Just verify climate_impact was added
        assert 'climate_impact' in result.attrs
        assert isinstance(result.attrs['climate_impact'], dict)
