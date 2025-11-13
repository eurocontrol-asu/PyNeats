# ruff: noqa: F401
import pytest
from tqdm import tqdm
from pandas.testing import assert_frame_equal
from pyneats.steps.emissions.pycontrails_emissions import (
    FlightWithEmissions,
    FlightWithPerformance,
    PyContrailsEmissionParams,
    PyContrailsEmissionModel,
)
from .fixtures.nm_traffic import nm_output


def test_emissions(nm_output):  # noqa: F811
    rtol = 1e-3
    atol = 1e-8
    check_cols = list(FlightWithEmissions.REQUIRED)

    # Define parameters
    params = PyContrailsEmissionParams()

    # For all flights in test
    for flight in tqdm(nm_output, desc="processing test flight ..."):
        # Expected output
        expected_output = FlightWithEmissions.from_flight(flight.copy()).to_dataframe()

        # Create step
        step = PyContrailsEmissionModel(params)

        # Create input
        input = FlightWithPerformance.from_flight(flight.copy())

        # Run step
        output = step(input).to_dataframe()  # type: ignore

        # Assert that input matches output
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="Original",
        )
