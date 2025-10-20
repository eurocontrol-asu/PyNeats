from __future__ import annotations
from typing import Mapping, Any
import pytest
from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.views import FlightWithWeather, FlightWithPerformance
import numpy as np


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
def test_pyneats_mass_runs_for_flight(test_inputs: Any, flight_case: Any):
    """
    - Runs pipeline for one flight
    - Basic sanity checks
    - Numeric regression: sums of ['fuel_flow','fuel_burn','ef'] vs expectations (if provided)
    """
    # Find the flight
    flight = [
        f
        for f in test_inputs["expectations"]
        if f.attrs.get("model_type") == test_inputs["model_type"]
        and f.attrs.get("flight_id") == str(flight_case["flight_id"])
        and f.attrs.get("departure_airport") == str(flight_case["adep"])
        and f.attrs.get("arrival_airport") == str(flight_case["ades"])
        and f.attrs.get("registration") == str(flight_case["registration"])
    ]

    if not flight:
        key = _composite_key(test_inputs["model_type"], flight_case)
        pytest.skip(
            f"No expectations for {key}; provide with --expect to enable numeric regression."
        )
    elif len(flight) > 1:
        key = _composite_key(test_inputs["model_type"], flight_case)
        pytest.skip(
            f"More than one result found for {key}; provide with just one result."
        )

    flight = flight[0]
    expected_output = FlightWithPerformance.from_flight(flight.copy())
    input = FlightWithWeather.from_flight(flight.copy())

    aircraft_mass = input.data.pop("aircraft_mass")
    fuel_flow = input.data.pop("fuel_flow")
    engine_efficiency = input.data.pop("engine_efficiency")

    # Get tolerances
    rtol = float(test_inputs["rtol"])
    atol = float(test_inputs["atol"])

    def assert_run(
        output,
        expected_output,
        columns,
        rtol=1.0e-3,
        atol=1.0e-8,
        run_info="",
    ):
        for c in columns:
            assert np.allclose(
                output[c],
                expected_output[c],
                equal_nan=True,
                atol=atol,
                rtol=rtol,
            ), f"{c} != expected {c} (rtol={rtol}, atol={atol}). Run info: {run_info}"

    # Initialise the step to test
    step = BADAPerformanceModel(None)

    columns = [
        "aircraft_mass",
        "fuel_flow",
        "engine_efficiency",
    ]

    # Remove all
    output = step.run(input)  # type: ignore
    assert_run(
        output,
        expected_output,
        columns=columns,
        rtol=rtol,
        atol=atol,
        run_info="removing all",
    )

    # Set payload factor
    input.attrs["payload_factor"] = step.params.payload_factor  # type: ignore
    output = step.run(input)  # type: ignore
    assert_run(
        output,
        expected_output,
        columns=columns,
        rtol=rtol,
        atol=atol,
        run_info="setting payload factor",
    )

    # Set takeoff weight
    input.attrs["takeoff_weight"] = aircraft_mass[0]
    output = step.run(input)  # type: ignore
    assert_run(
        output,
        expected_output,
        columns=columns,
        rtol=rtol,
        atol=atol,
        run_info="setting takeoff_weight",
    )

    # Set aircraft mass along the trajectory
    input["aircraft_mass"] = aircraft_mass
    output = step.run(input)  # type: ignore
    assert_run(
        output,
        expected_output,
        columns=columns,
        rtol=rtol,
        atol=atol,
        run_info="setting aircraft_mass",
    )

    # Set fuel flow
    input["fuel_flow"] = fuel_flow
    output = step.run(input)  # type: ignore
    assert_run(
        output,
        expected_output,
        columns=columns,
        rtol=rtol,
        atol=atol,
        run_info="setting fuel_flow",
    )

    # Set engine efficiency
    input["engine_efficiency"] = engine_efficiency
    output = step.run(input)  # type: ignore
    assert_run(
        output,
        expected_output,
        columns=columns,
        rtol=rtol,
        atol=atol,
        run_info="setting engine_efficiency",
    )
