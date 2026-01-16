"""Test emissions computation step."""

import pytest
from pandas.testing import assert_frame_equal

from pyneats.steps.emissions.pycontrails_emissions import (
    FlightWithEmissions,
    FlightWithPerformance,
    PyContrailsEmissionParams,
    PyContrailsEmissionModel,
)

from .fixtures.nm_traffic import nm_output


@pytest.mark.integration
def test_emissions(nm_output, flight_idx):  # noqa: F811
    """Test emissions computation for individual flights.

    Uses golden output as input (has performance data), runs emissions
    step, and compares with expected emissions columns.
    """
    rtol = 1e-3  # 0.1% relative tolerance
    atol = 1e-8  # Absolute tolerance
    check_cols = list(FlightWithEmissions.REQUIRED)

    # Get expected flight
    expected_flight = nm_output[flight_idx]
    expected_output = FlightWithEmissions.from_flight(expected_flight.copy()).to_dataframe()

    # Create input (FlightWithPerformance from golden data)
    input_flight = FlightWithPerformance.from_flight(expected_flight.copy())

    # Create step and run
    params = PyContrailsEmissionParams()
    step = PyContrailsEmissionModel(params)
    output = step(input_flight).to_dataframe()

    # Assert that output matches expected
    assert_frame_equal(
        output[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (emissions)",
    )

