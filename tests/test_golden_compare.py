"""Unit tests of the golden comparison helper (``tests/golden_compare.py``).

The golden tests that use the helper need weather data and do not run in CI.
These synthetic records pin its behaviour so that CI catches a change to it.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.golden_compare import GOLDEN_RTOL
from tests.golden_compare import assert_matches_golden


def _record() -> dict[str, Any]:
    return {
        "flight_id": "TEST1",
        "n_engine": 2,
        "time": [0, 60, 120, 180],
        "fuel_flow": [1.2, 0.9, 0.8, 0.8],
        "acceleration": [0.5, 0.0, -0.01, 0.002],
        "co2": [3.79, 2.84, float("nan"), 2.53],
        "phase": ["climb", "climb", "cruise", "cruise"],
        "total_co2": 1234.5,
        "climate_impact": {
            "climate_metrics": [
                {
                    "species": "CO2",
                    "value": [{"horizon": 20, "CO2eq_kg": 1234.5}],
                }
            ]
        },
    }


def test_identical_record_passes() -> None:
    assert_matches_golden(_record(), _record())


def test_change_inside_rtol_passes() -> None:
    actual = _record()
    actual["fuel_flow"] = [v * (1 + GOLDEN_RTOL / 2) for v in actual["fuel_flow"]]
    assert_matches_golden(actual, _record())


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda r: r["fuel_flow"].__setitem__(1, 0.9 * (1 + 2 * GOLDEN_RTOL)),
            id="one-point-above-rtol",
        ),
        pytest.param(
            lambda r: r.__setitem__("fuel_flow", [1.2, 1.2, 0.9, 0.8]),
            id="shift-by-one-point",
        ),
        pytest.param(lambda r: r["co2"].__setitem__(0, float("nan")), id="new-nan"),
        pytest.param(lambda r: r["co2"].__setitem__(2, 2.6), id="nan-filled"),
        pytest.param(lambda r: r["fuel_flow"].pop(), id="shorter-column"),
        pytest.param(lambda r: r.pop("acceleration"), id="missing-column"),
        pytest.param(lambda r: r.__setitem__("extra", [1, 2, 3, 4]), id="extra-column"),
        pytest.param(lambda r: r["time"].__setitem__(2, 121), id="integer-time"),
        pytest.param(lambda r: r["phase"].__setitem__(2, "climb"), id="string"),
        pytest.param(lambda r: r.__setitem__("n_engine", 4), id="n-engine"),
        pytest.param(
            lambda r: r.__setitem__("total_co2", 1234.5 * (1 + 2 * GOLDEN_RTOL)),
            id="total",
        ),
        pytest.param(
            lambda r: r["acceleration"].__setitem__(3, -0.002), id="small-sign-flip"
        ),
    ],
)
def test_real_change_fails(mutate: Any) -> None:
    actual = copy.deepcopy(_record())
    mutate(actual)
    with pytest.raises(AssertionError):
        assert_matches_golden(actual, _record())


def test_skip_ignores_values_but_not_presence() -> None:
    actual = _record()
    actual["fuel_flow"] = [9.9, 9.9, 9.9, 9.9]
    assert_matches_golden(actual, _record(), skip=("fuel_flow",))
    del actual["fuel_flow"]
    with pytest.raises(AssertionError):
        assert_matches_golden(actual, _record(), skip=("fuel_flow",))


def test_loose_column_keeps_nan_pattern() -> None:
    actual = _record()
    actual["co2"] = [3.8, 2.8, float("nan"), 2.5]
    assert_matches_golden(actual, _record(), loose={"co2": 0.02})
    actual["co2"][2] = 2.6
    with pytest.raises(AssertionError):
        assert_matches_golden(actual, _record(), loose={"co2": 0.02})


def test_failure_message_names_the_column() -> None:
    actual = _record()
    actual["fuel_flow"][1] = 2.0
    with pytest.raises(AssertionError, match="fuel_flow"):
        assert_matches_golden(actual, _record(), label="case")
