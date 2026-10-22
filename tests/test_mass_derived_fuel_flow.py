"""Fuel flow derived from an AO aircraft_mass column (audit D3).

The fuel burned over segment i (t[i] -> t[i+1]) is mass[i] - mass[i+1]. The old
code used mass[i-1] - mass[i]: every value one point late, 0 at the first point,
the last segment's fuel lost, and the wrong duration when steps are uneven.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from pyneats.steps.performance.bada_model import BADAPerformanceModel


def _derive(df: pd.DataFrame) -> pd.DataFrame:
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    BADAPerformanceModel._derive_fuel_flow_from_mass_if_needed(model, df)
    return df


def test_each_point_gets_the_burn_of_its_own_segment() -> None:
    # Uneven steps (10, 10, 5 s): the burn of each segment over its own duration.
    df = pd.DataFrame(
        {
            "aircraft_mass": [1000.0, 990.0, 975.0, 970.0],
            "segment_duration": [10.0, 10.0, 5.0, np.nan],
        }
    )
    ff = _derive(df)["fuel_flow"].to_numpy()
    np.testing.assert_allclose(ff[:3], [1.0, 1.5, 1.0])
    assert np.isnan(ff[-1])  # no next mass


def test_total_burn_equals_mass_drop() -> None:
    mass = np.array([70_000.0, 69_890.0, 69_785.0, 69_700.0, 69_640.0])
    dt = np.array([60.0, 60.0, 60.0, 60.0, np.nan])
    df = _derive(pd.DataFrame({"aircraft_mass": mass, "segment_duration": dt}))
    burn = np.nansum(df["fuel_flow"].to_numpy() * dt)
    assert burn == pytest.approx(mass[0] - mass[-1], rel=1e-12)


def test_mass_increase_gives_zero_not_negative_flow() -> None:
    df = _derive(
        pd.DataFrame(
            {
                "aircraft_mass": [1000.0, 1001.0, 995.0],
                "segment_duration": [10.0, 10.0, np.nan],
            }
        )
    )
    np.testing.assert_allclose(df["fuel_flow"].to_numpy()[:2], [0.0, 0.6])


def test_provided_fuel_flow_is_kept() -> None:
    df = pd.DataFrame(
        {
            "aircraft_mass": [1000.0, 990.0],
            "segment_duration": [10.0, np.nan],
            "fuel_flow": [2.0, 2.0],
        }
    )
    np.testing.assert_allclose(_derive(df)["fuel_flow"].to_numpy(), [2.0, 2.0])
