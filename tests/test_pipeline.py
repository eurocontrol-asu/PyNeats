# ruff: noqa: F401
import pytest
from tqdm import tqdm
from pandas.testing import assert_frame_equal
from pyneats.steps.climate_functions.views import FlightWithContrailsImpact
from pyneats.steps.performance.views import FlightWithPerformance
from pyneats.runners.flight import FlightRunner
from .fixtures.nm_traffic import nm_input, nm_output
from .fixtures.weather import weather


def test_pipeline(nm_input, nm_output, weather):  # noqa: F811
    rtol = 1e-3
    atol = 1e-8
    check_cols = list(FlightWithContrailsImpact.REQUIRED) + list(
        FlightWithPerformance.REQUIRED
    )

    # Let us check performance and contrails columns
    for df, flight in tqdm(zip(nm_input, nm_output), desc="processing test flight ..."):
        # Expected output
        expected_output = FlightWithContrailsImpact.from_flight(
            flight.copy()
        ).to_dataframe()

        # Create flight runner
        pipeline = FlightRunner(weather, df)
        pipeline.eval()

        if pipeline.flight_with_contrails is not None:
            output = pipeline.flight_with_contrails.to_dataframe()
        else:
            raise RuntimeError(
                "No 'flight_with_contrails' available on FlightRunner result"
            )

        # Assert that input matches output for arr required cols of FlightWithContrailsImpact
        assert_frame_equal(
            output[check_cols],
            expected_output[check_cols],
            rtol=rtol,
            atol=atol,
            obj="FlightWithContrailsImpact",
        )
