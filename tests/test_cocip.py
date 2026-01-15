"""Test CoCiP (contrails) computation step."""

import pytest
from pandas.testing import assert_frame_equal

from pyneats.steps.climate_functions.cocip import (
    FlightWithEmissions,
    FlightWithContrailsImpact,
    CoCiPModel,
    ContrailsParams,
)

from .fixtures.nm_traffic import nm_output
from .fixtures.weather import weather


@pytest.mark.parametrize("flight_idx", range(5))
def test_cocip(nm_output, weather, flight_idx):  # noqa: F811
    """Test CoCiP (contrails) computation for individual flights.

    Uses golden output as input (has emissions data), runs CoCiP step,
    and compares with expected contrails columns.
    """
    # Skip if weather not available
    if weather is None:
        pytest.skip(
            "Weather data not available. Use pytest --met-cache-dir=/path/to/data or set MET_CACHE_DIR"
        )

    rtol = 1e-3  # 0.1% relative tolerance (same as main branch)
    atol = 1e-8  # Absolute tolerance (same as main branch)
    check_cols = list(FlightWithContrailsImpact.REQUIRED)

    # Columns produced by CoCiP (remove from input)
    drop_cols = [
        "ef",
        "contrail_age",
        "sdr_mean",
        "rsr_mean",
        "olr_mean",
        "rf_sw_mean",
        "rf_lw_mean",
        "rf_net_mean",
    ]

    # Get expected flight
    expected_flight = nm_output[flight_idx]
    expected_output = FlightWithContrailsImpact.from_flight(expected_flight.copy()).to_dataframe()

    # Create input (FlightWithEmissions from golden, remove CoCiP outputs)
    input_flight = FlightWithEmissions.from_flight(expected_flight.copy())
    for col in drop_cols:
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
        obj=f"Flight {flight_idx}",
    )
