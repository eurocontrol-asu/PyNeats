# ruff: noqa: F401
import pytest
from tqdm import tqdm
from pandas.testing import assert_frame_equal
from pyneats.steps.climate_functions.cocip import (
    FlightWithEmissions,
    FlightWithContrailsImpact,
    CoCiPModel,
    ContrailsParams,
)
from .fixtures.nm_traffic import nm_output
from .fixtures.weather import weather


def test_cocip(nm_output, weather):  # noqa: F811
    if weather is None:
        pytest.skip(
            """test_cocip not performed because weather data is not provided.
                Use pytest tests --met-cache-dir=/custom/path/to/data or set MET_CACHE_DIR environment variable"""
        )

    rtol = 1e-3
    atol = 1e-8
    check_cols = list(FlightWithContrailsImpact.REQUIRED)

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

    # Define parameters
    params = ContrailsParams(met=weather.met(), rad=weather.rad())

    # For all flights in test
    for flight in tqdm(nm_output, desc="processing test flight ..."):
        # Expected output
        expected_output = FlightWithContrailsImpact.from_flight(flight.copy()).to_dataframe()

        # Create step
        step = CoCiPModel(params)

        # Create input
        input = FlightWithEmissions.from_flight(flight.copy())

        for c in drop_cols:
            input.data.pop(c, None)

        # Run step
        output = step(input).to_dataframe()  # type: ignore

        # Assert that input matches output
        assert_frame_equal(
            output[check_cols].astype(float),
            expected_output[check_cols].astype(float),
            rtol=rtol,
            atol=atol,
            obj="Original",
        )
