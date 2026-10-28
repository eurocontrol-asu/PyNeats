"""The golden climate payload comparison catches NaN and inf values.

``assert_climate_payload_equal`` compares the flight totals of the golden tests
(fuel burn, CO2, CO2eq per species and horizon) with a relative tolerance. Any
comparison with NaN is False, so a NaN actual value passed both the relative
check and the check against an expected 0.
"""

from __future__ import annotations

import math

import pytest

from tests.conftest import assert_climate_payload_equal


NAN = math.nan
INF = math.inf


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (NAN, 3759.0),  # NaN total where a number is expected
        (NAN, 0.0),  # NaN where 0 is expected
        (INF, 3759.0),
        (-INF, 0.0),
        (3759.0, NAN),
        (3759.0, INF),
        (INF, NAN),
        (INF, -INF),
        (3759.0 * 1.01, 3759.0),  # outside rtol 1e-3
        (0.01, 0.0),  # outside atol 1e-3
    ],
)
def test_mismatch_fails(actual: float, expected: float) -> None:
    with pytest.raises(AssertionError, match="fuel_burn_kg"):
        assert_climate_payload_equal(
            {"fuel_burn_kg": actual}, {"fuel_burn_kg": expected}
        )


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (NAN, NAN),
        (INF, INF),
        (-INF, -INF),
        (3759.0, 3759.0),
        (3759.0 * (1 + 5e-4), 3759.0),  # inside rtol 1e-3
        (5e-4, 0.0),  # inside atol 1e-3
    ],
)
def test_match_passes(actual: float, expected: float) -> None:
    assert_climate_payload_equal({"fuel_burn_kg": actual}, {"fuel_burn_kg": expected})


def test_nan_in_nested_payload_fails() -> None:
    expected = {"EAGWP": {"CO2": [1.5, 2.5]}, "fuel_burn_kg": 3759.0}
    actual = {"EAGWP": {"CO2": [1.5, NAN]}, "fuel_burn_kg": 3759.0}
    with pytest.raises(AssertionError, match=r"EAGWP\.CO2\[1\]"):
        assert_climate_payload_equal(actual, expected)
