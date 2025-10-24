# ruff: noqa: F401
import pytest
from pyneats.steps.parsing.nm_parser import NMTrajectoryParser
from pyneats.steps.interpolation import PyContrailsInterpolator
from pyneats.steps.parsing.views import Flight4D
from tqdm import tqdm
from pandas.testing import assert_frame_equal
from .fixtures.nm_traffic import nm_input, nm_output


def test_parsing_and_interpolation(nm_input, nm_output):  # noqa: F811
    parser = NMTrajectoryParser()
    interpolator = PyContrailsInterpolator()

    rtol = 1e-3
    atol = 1e-8
    check_cols = list(Flight4D.REQUIRED)

    for df, flight in tqdm(zip(nm_input, nm_output), desc="processing test flight ..."):
        expected_output = Flight4D.from_flight(flight.copy()).to_dataframe()

        parsed_flight_4d = parser(df)
        interpolated_flight = interpolator(parsed_flight_4d).to_dataframe()

        assert_frame_equal(
            interpolated_flight[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="FlightWithPayloadFactor",
        )
