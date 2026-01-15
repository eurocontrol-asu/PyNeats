# ruff: noqa: F401
import pytest
from pyneats.steps.performance.bada_model import BADAPerformanceModel, BADAPerformanceModelParams
from pyneats.steps.performance.views import FlightWithWeather, FlightWithPerformance
from pandas.testing import assert_frame_equal
from tqdm import tqdm
from pathlib import Path
from typing import List
from pyneats.core.views import FlightView


def test_mass_decision_tree(golden_flights: List[FlightView], bada3_path, bada4_path):
    """Test BADA mass decision tree logic with different input configurations.

    This test validates that the BADA performance model correctly handles different
    scenarios for aircraft mass calculation based on available data.
    """
    if bada3_path is None and bada4_path is None:
        pytest.skip("BADA data not available")

    rtol = 1e-3
    atol = 1e-8
    check_cols = list(FlightWithPerformance.REQUIRED)

    # Setup BADA parameters
    bada_root = str(bada4_path.parent) if bada4_path else str(bada3_path.parent)
    params = BADAPerformanceModelParams(
        bada4_root_path=bada_root,
        bada3_root_path=bada_root,
    )

    for flight in tqdm(golden_flights, desc="processing test flight ..."):
        # Create expected output for the mass decision tree check
        expected_output = FlightWithPerformance.from_flight(flight.copy()).to_dataframe()

        # Create input
        input = FlightWithWeather.from_flight(flight.copy())

        # Get original aircraft mass, fuel flow and engine efficiency
        aircraft_mass = input.data.pop("aircraft_mass")
        fuel_flow = input.data.pop("fuel_flow")
        engine_efficiency = input.data.pop("engine_efficiency")

        # Initialise the step to test
        step = BADAPerformanceModel(params)

        # With no information (just like the original flight was run)
        output = step(input).to_dataframe()  # type: ignore

        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="Original",
        )

        # Set payload factor
        input.attrs["payload_factor"] = step.params.payload_factor  # type: ignore

        output = step(input).to_dataframe()
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="FlightWithPayloadFactor",
        )

        # Set takeoff weight
        input.attrs["takeoff_weight"] = aircraft_mass[0]
        output = step(input).to_dataframe()
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="FlightWithTakeOfWeight",
        )

        # Set aircraft mass along the trajectory
        input["aircraft_mass"] = aircraft_mass
        output = step(input).to_dataframe()
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="FlightWithAircraftMass",
        )

        # Set fuel flow
        input["fuel_flow"] = fuel_flow
        output = step(input).to_dataframe()
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="FlightWithFuelFlow",
        )

        # Set engine efficiency
        input["engine_efficiency"] = engine_efficiency
        output = step(input).to_dataframe()
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="FlightWithEngineEfficiency",
        )
