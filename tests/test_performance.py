# ruff: noqa: F401
import pytest
from pyneats.steps.performance.bada_model import BADAPerformanceModel, BADAPerformanceModelParams
from pyneats.steps.performance.views import FlightWithWeather, FlightWithPerformance
from pandas.testing import assert_frame_equal
from .fixtures.nm_traffic import nm_output
from tqdm import tqdm
from pathlib import Path


@pytest.mark.integration
@pytest.mark.requires_bada
@pytest.mark.slow
def test_performance(nm_output, flight_idx, bada_root_path):  # noqa: F811
    """Test BADA performance model with various configuration options.

    Tests performance computation with:
    - No initial information (baseline)
    - With payload factor
    - With takeoff weight
    - With aircraft mass trajectory
    - With fuel flow
    - With engine efficiency
    """
    if bada_root_path is None or not bada_root_path.exists():
        pytest.skip("BADA data not available, skipping test.")

    rtol = 1e-3
    atol = float("inf")
    check_cols = list(FlightWithPerformance.REQUIRED)

    # Setup BADA parameters
    params = BADAPerformanceModelParams(
        bada4_root_path=str(bada_root_path),
        bada3_root_path=str(bada_root_path),
    )

    # Get expected flight
    expected_flight = nm_output[flight_idx]
    expected_output = FlightWithPerformance.from_flight(expected_flight.copy()).to_dataframe()


    # Create input
    input = FlightWithWeather.from_flight(expected_flight.copy())

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
        obj=f"Flight {flight_idx} (performance - baseline)",
    )

    # Set payload factor
    input.attrs["payload_factor"] = step.params.payload_factor  # type: ignore

    output = step(input).to_dataframe()
    assert_frame_equal(
        output[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (performance - with payload_factor)",
    )

    # Set takeoff weight
    input.attrs["takeoff_weight"] = aircraft_mass[0]
    output = step(input).to_dataframe()
    assert_frame_equal(
        output[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (performance - with takeoff_weight)",
    )

    # Set aircraft mass along the trajectory
    input["aircraft_mass"] = aircraft_mass
    output = step(input).to_dataframe()
    assert_frame_equal(
        output[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (performance - with aircraft_mass)",
    )

    # Set fuel flow
    input["fuel_flow"] = fuel_flow
    output = step(input).to_dataframe()
    assert_frame_equal(
        output[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (performance - with fuel_flow)",
    )

    # Set engine efficiency
    input["engine_efficiency"] = engine_efficiency
    output = step(input).to_dataframe()
    assert_frame_equal(
        output[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (performance - with engine_efficiency)",
    )
