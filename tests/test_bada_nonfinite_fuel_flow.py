"""A non-finite BADA fuel flow counts as a BADA failure at that point (audit I13).

``_single_pass_performance`` replaces a point where BADA fails (raises, or gives
a fuel flow above ``ff_outlier_threshold`` or below 0) by the values of the
previous point, and fails the attempt after ``max_consecutive_failures`` such
points in a row. A NaN fuel flow passed both comparisons, so it was accepted:
it became the "previous" value, and the mass integrated from a take-off mass
was NaN for the rest of the flight, so all later fuel was lost.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError


SEGMENT_S = 60.0
FUEL_FLOW = 1.0  # kg/s, BADA fuel flow at a finite TAS
THRUST = 50_000.0  # N
TOW = 70_000.0  # kg
MAX_CONSECUTIVE_FAILURES = 5


class _FakeAdapter:
    """BADA stand-in: fuel flow ``FUEL_FLOW`` at a finite TAS, NaN otherwise.

    BADA4 gives NaN fuel flow and thrust at a NaN TAS without raising.
    """

    def thrust_fuel_segment(
        self,
        mass: float,
        altitude_m: float,
        tas_mps: float,
        rocd_mps: float,
        accel_mps2: float,
        delta_tau: float,
    ) -> tuple[float, float, str, str]:
        if not np.isfinite(tas_mps):
            return float("nan"), float("nan"), "Cruise", "TOTAL"
        return FUEL_FLOW, THRUST, "Cruise", "TOTAL"


def _make_model() -> MagicMock:
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    model.params = MagicMock()
    model.params.max_consecutive_failures = MAX_CONSECUTIVE_FAILURES
    model.params.ff_outlier_threshold = 100.0
    model._single_pass_performance = (
        BADAPerformanceModel._single_pass_performance.__get__(model)
    )
    return model


def _make_df(tas: list[float]) -> pd.DataFrame:
    n = len(tas)
    return pd.DataFrame(
        {
            "altitude": [10_000.0] * n,
            "true_airspeed": tas,
            "rocd": [0.0] * n,
            "acceleration": [0.0] * n,
            "delta_tau": [0.0] * n,
            "segment_duration": [SEGMENT_S] * (n - 1) + [float("nan")],
        }
    )


def _run(tas: list[float], initial_mass: float | None = TOW) -> Any:
    df = _make_df(tas)
    if initial_mass is None:
        df["aircraft_mass"] = TOW
    return _make_model()._single_pass_performance(
        _FakeAdapter(), df, initial_mass, q_fuel_used=1.0, default_q_fuel=1.0
    )


def test_interior_nan_fuel_flow_takes_previous_point() -> None:
    nan = float("nan")
    perf = _run([230.0, 230.0, nan, nan, 230.0, 230.0, 230.0])

    assert perf["fuel_flow"] == [FUEL_FLOW] * 7
    assert perf["thrust"] == [THRUST] * 7
    # The mass stays finite and decreases by FUEL_FLOW x 60 s per segment.
    expected = [TOW - FUEL_FLOW * SEGMENT_S * i for i in range(7)]
    np.testing.assert_allclose(perf["mass"], expected)


def test_nan_last_point_takes_previous_point() -> None:
    # On the computed-TAS path the last point has no TAS (forward segment).
    perf = _run([230.0, 230.0, 230.0, float("nan")])

    assert perf["fuel_flow"] == [FUEL_FLOW] * 4
    assert np.isfinite(perf["mass"]).all()


def test_nan_fuel_flow_with_aircraft_mass_column() -> None:
    perf = _run([230.0, float("nan"), 230.0], initial_mass=None)

    assert perf["fuel_flow"] == [FUEL_FLOW] * 3
    assert perf["mass"] == [TOW] * 3


def test_nan_fuel_flow_at_first_point_fails_the_attempt() -> None:
    with pytest.raises(PerformanceStepError, match="very first") as exc:
        _run([float("nan"), 230.0, 230.0])
    assert exc.value.retryable


def test_too_many_consecutive_nan_fuel_flows_fail_the_attempt() -> None:
    tas = [230.0] + [float("nan")] * (MAX_CONSECUTIVE_FAILURES + 1) + [230.0]
    with pytest.raises(PerformanceStepError, match="consecutive") as exc:
        _run(tas)
    assert exc.value.retryable


def test_max_consecutive_nan_fuel_flows_are_accepted() -> None:
    tas = [230.0] + [float("nan")] * MAX_CONSECUTIVE_FAILURES + [230.0]
    perf = _run(tas)

    assert perf["fuel_flow"] == [FUEL_FLOW] * len(tas)
    assert np.isfinite(perf["mass"]).all()
