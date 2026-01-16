"""Test CoCiP (contrails) computation step."""

import pytest
from pandas.testing import assert_frame_equal

from pyneats.steps.climate_functions.cocip import (
    CoCiPModel,
    ContrailsParams,
    FlightWithContrailsImpact,
    FlightWithEmissions,
)


@pytest.mark.integration
@pytest.mark.requires_weather
def test_cocip(nm_output, weather, flight_idx):  # noqa: F811
    """Test CoCiP (contrails) computation for individual flights.

    Uses golden output as input (has emissions data), runs CoCiP step,
    and compares with expected contrails columns.
    """
    # Skip if weather not available
    if weather is None:
        pytest.skip(
            "Weather data not available. Use pytest --met-cache-dir=/path/to/data or set MET_CACHE_DIR" # noqa: E501
        )

    rtol = 1e-3  # 0.1% relative tolerance
    atol = float("inf")  # Only check relative tolerance
    check_cols = list(FlightWithContrailsImpact.REQUIRED)

    # Get expected flight
    expected_flight = nm_output[flight_idx]
    expected_output = FlightWithContrailsImpact.from_flight(expected_flight.copy()).to_dataframe()

    # Create input (FlightWithEmissions from golden, remove CoCiP outputs)
    input_flight = FlightWithEmissions.from_flight(expected_flight.copy())

    required_and_optional = (
        FlightWithEmissions._all_required() + FlightWithEmissions._all_optional()
    )
    for col in list(input_flight.data.keys()):
        if col not in required_and_optional:
            input_flight.data.pop(col, None)

    # Create step and run
    params = ContrailsParams(met=weather.met(), rad=weather.rad())
    step = CoCiPModel(params)
    output = step(input_flight).to_dataframe()

    # Assert that output matches expected
    assert_frame_equal(
        output[check_cols].astype(float),
        expected_output[check_cols].astype(float),
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} (contrails)",
    )

