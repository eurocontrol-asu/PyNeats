"""Test parsing and interpolation steps."""

import pytest
from pandas.testing import assert_frame_equal

from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.interpolation import PyContrailsInterpolator
from pyneats.steps.parsing.views import Flight4D

from .fixtures.nm_traffic import nm_input, nm_output


@pytest.mark.parametrize("flight_idx", range(5))
def test_parsing_and_interpolation(nm_input, nm_output, flight_idx):  # noqa: F811
    """Test parsing and interpolation for individual flights.

    Takes raw NM JSON input, parses it, interpolates, and compares
    with expected Flight4D columns from golden output.
    """
    rtol = 0.05  # 5% relative tolerance
    atol = 1e-3  # Absolute tolerance
    check_cols = list(Flight4D.REQUIRED)

    # Get input and expected output for this flight
    raw_flight = nm_input[flight_idx]
    expected_flight = nm_output[flight_idx]
    expected_output = Flight4D.from_flight(expected_flight.copy()).to_dataframe()

    # Parse raw JSON to Flight
    parsed_flights = neats_json_to_flights([raw_flight])
    assert len(parsed_flights) == 1, f"Parser should return exactly 1 flight, got {len(parsed_flights)}"

    # Interpolate
    interpolator = PyContrailsInterpolator()
    interpolated_flight = interpolator(parsed_flights[0]).to_dataframe()

    # Assert that output matches expected
    assert_frame_equal(
        interpolated_flight[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx}",
    )
