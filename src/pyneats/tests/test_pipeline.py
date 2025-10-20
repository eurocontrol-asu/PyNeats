from __future__ import annotations
import numpy as np
from typing import Mapping, Any
import pytest

from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr
from pyneats.runners.flight import (
    FlightRunner,
)  # adjust import path if your project differs


def _composite_key(model_type: str, flight_case: Mapping[str, Any]) -> str:
    return "|".join(
        [
            str(model_type).upper(),
            str(flight_case["flight_id"]),
            str(flight_case["adep"]),
            str(flight_case["ades"]),
            str(flight_case["registration"]),
        ]
    )


@pytest.mark.characterization
def test_pyneats_pipeline_runs_for_flight(test_inputs: Any, flight_case: Any):
    """
    - Runs pipeline for one flight
    - Basic sanity checks
    - Numeric regression: sums of ['fuel_flow','fuel_burn','ef'] vs expectations (if provided)
    """
    df_flight = flight_case["df"]
    zarr_paths = test_inputs["zarr_paths"]
    t0, t1 = test_inputs["t0"], test_inputs["t1"]
    read_chunks = test_inputs["read_chunks"]

    # --- Weather ---
    zp = ZarrPaths(
        zarr_paths["met_store"],
        zarr_paths["rad_store"],
        zarr_paths["wind_store"],  # may be None
    )

    weather = get_weather_from_zarr(zp, t0=t0, t1=t1, chunks=read_chunks)
    assert weather is not None, "Weather failed to load"

    # --- PyNeats FlightRunner ---
    neats_flight = FlightRunner(weather, df_flight)
    neats_flight.eval()  # your API

    # --- Numeric regression on sums ---
    # Make sure your object exposes the frame as you indicated:
    # neats_flight.flight_with_contrails.to_dataframe()[['fuel_flow','fuel_burn','ef']].sum()
    if not hasattr(neats_flight, "flight_with_contrails"):
        pytest.skip(
            "No 'flight_with_contrails' available on FlightRunner result; skipping regression sums."
        )

    if neats_flight.flight_with_contrails is not None:
        df_out = neats_flight.flight_with_contrails.to_dataframe()
    else:
        pytest.skip(
            "No 'flight_with_contrails' available on FlightRunner result; skipping regression sums."
        )

    required_cols = [
        "fuel_flow",
        "fuel_burn",
        "ef",
    ]
    missing = [c for c in required_cols if c not in df_out.columns]

    if missing:
        pytest.skip(
            f"Missing expected columns {missing} in output; skipping regression sums."
        )

    sums = df_out[required_cols].sum()
    fuel_flow_sum = float(sums["fuel_flow"])
    fuel_burn_sum = float(sums["fuel_burn"])
    ef_sum = float(sums["ef"])

    # Find the flight
    flight_expected = [
        f
        for f in test_inputs["expectations"]
        if f.attrs.get("model_type") == test_inputs["model_type"]
        and f.attrs.get("flight_id") == str(flight_case["flight_id"])
        and f.attrs.get("departure_airport") == str(flight_case["adep"])
        and f.attrs.get("arrival_airport") == str(flight_case["ades"])
        and f.attrs.get("registration") == str(flight_case["registration"])
    ]

    if not flight_expected:
        key = _composite_key(test_inputs["model_type"], flight_case)
        pytest.skip(
            f"No expectations for {key}; provide with --expect to enable numeric regression."
        )
    elif len(flight_expected) > 1:
        key = _composite_key(test_inputs["model_type"], flight_case)
        pytest.skip(
            f"More than one result found for {key}; provide with just one result."
        )

    flight_expected = flight_expected[0]

    # Get dataframe and expected sums
    df_expected = flight_expected.dataframe
    sums_expected = df_expected[required_cols].sum()
    fuel_flow_sum_expected = float(sums_expected["fuel_flow"])
    fuel_burn_sum_expected = float(sums_expected["fuel_burn"])
    ef_sum_expected = float(sums_expected["ef"])

    rtol = float(test_inputs["rtol"])
    atol = float(test_inputs["atol"])

    # Compare using numpy allclose
    assert (
        np.isfinite(fuel_flow_sum)
        and np.isfinite(fuel_burn_sum)
        and np.isfinite(ef_sum)
    ), "Non-finite sums"

    assert np.isclose(
        fuel_flow_sum,
        fuel_flow_sum_expected,
        rtol=rtol,
        atol=atol,
    ), (
        f"fuel_flow_sum {fuel_flow_sum} != expected {fuel_flow_sum_expected} (rtol={rtol}, atol={atol})"
    )

    assert np.isclose(
        fuel_burn_sum,
        fuel_burn_sum_expected,
        rtol=rtol,
        atol=atol,
    ), (
        f"fuel_burn_sum {fuel_burn_sum} != expected {fuel_burn_sum_expected} (rtol={rtol}, atol={atol})"
    )

    assert np.isclose(
        ef_sum,
        ef_sum_expected,
        rtol=rtol,
        atol=atol,
    ), f"ef_sum {ef_sum} != expected {ef_sum_expected} (rtol={rtol}, atol={atol})"
