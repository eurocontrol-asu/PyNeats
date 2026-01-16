"""Test parsing and interpolation steps."""

import pytest
from pandas.testing import assert_frame_equal

from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.interpolation import PyContrailsInterpolator
from pyneats.steps.parsing.views import Flight4D

from .fixtures.nm_traffic import nm_input, nm_output


@pytest.mark.integration
def test_interpolation(nm_input, nm_output, flight_idx):  # noqa: F811
    """Test parsing and interpolation for individual flights.

    Takes raw NM JSON input, parses it, interpolates, and compares
    with expected Flight4D columns from golden output.
    """
    parser = NeatsTrajectoryParser()
    interpolator = PyContrailsInterpolator()

    rtol = 1e-3  # 0.1% relative tolerance
    atol = 1e-2  # Absolute tolerance
    check_cols = list(Flight4D.REQUIRED)

    # Get input and expected output for this flight
    raw_flight = nm_input[flight_idx]

    expected_flight = nm_output[flight_idx]
    flight_id = expected_flight.attrs.get("flight_id", f"flight_{flight_idx}")
    expected_output = Flight4D.from_flight(expected_flight.copy()).to_dataframe()

    # Convert JSON to DataFrame
    dataframes = neats_json_to_flights([raw_flight])
    assert len(dataframes) == 1, f"neats_json_to_flights should return 1 DataFrame"
    df = dataframes[0]

    # Parse DataFrame to Flight4D
    parsed_flight_4d = parser(df)

    # Interpolate
    interpolated_flight = interpolator(parsed_flight_4d).to_dataframe()

    # Assert that output matches expected
    assert_frame_equal(
        interpolated_flight[check_cols],
        expected_output[check_cols],
        rtol=rtol,
        atol=atol,
        check_dtype=False,
        obj=f"Flight {flight_idx} [{flight_id}] (interpolation)",
    )

