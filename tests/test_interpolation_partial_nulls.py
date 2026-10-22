"""Empty values in AO columns are skipped when resampling (audit D4).

Before: a NaN at one AO point made every 1-min sample between its two
neighbours NaN, so those minutes had no fuel flow (or mass, efficiency, TAS)
and dropped out of the totals. Now the empty value is skipped, as if that point
had not been sent: samples are interpolated between the nearest valid values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pyneats.core.steps_registry import build
from pyneats.steps.interpolation import TrajectoryInterpolator
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser


ATTRS = {
    "flight_id": "FL001",
    "aircraft_type": "A320",
    "departure_airport": "EGLL",
    "arrival_airport": "LFPG",
    "model_type": "NM",
    "aobt": "2023-01-01 10:00:00",
}


def _resample(**columns: list[float]) -> pd.DataFrame:
    # Three AO points 10 min apart at FL300, resampled to 1 min.
    df = pd.DataFrame(
        {
            "latitude": [50.0, 50.5, 51.0],
            "longitude": [0.0, 0.5, 1.0],
            "altitude": [300, 300, 300],
            "time": [
                "2023-01-01 10:00:00",
                "2023-01-01 10:10:00",
                "2023-01-01 10:20:00",
            ],
            **columns,
        }
    )
    df.attrs = dict(ATTRS)
    flight = NeatsTrajectoryParser().run(df)
    out = build(TrajectoryInterpolator, "pycontrails")(flight).dataframe
    return out.set_index("time")


def test_interior_empty_value_is_interpolated_between_neighbours() -> None:
    out = _resample(fuel_flow=[1.0, np.nan, 3.0])
    ff = out["fuel_flow"]
    assert not ff.isna().any()
    # Straight line from 1.0 (10:00) to 3.0 (10:20): 2.0 at 10:10, 1.5 at 10:05.
    assert ff.loc["2023-01-01 10:10:00"] == pytest.approx(2.0)
    assert ff.loc["2023-01-01 10:05:00"] == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("values", "first", "last"),
    [([np.nan, 2.0, 3.0], 2.0, 3.0), ([1.0, 2.0, np.nan], 1.0, 2.0)],
    ids=["leading", "trailing"],
)
def test_edge_empty_value_takes_nearest_valid_value(
    values: list[float], first: float, last: float
) -> None:
    ff = _resample(fuel_flow=values)["fuel_flow"]
    assert not ff.isna().any()
    assert ff.iloc[0] == pytest.approx(first)
    assert ff.iloc[-1] == pytest.approx(last)


def test_each_column_uses_its_own_valid_points() -> None:
    out = _resample(
        fuel_flow=[1.0, np.nan, 3.0],
        engine_efficiency=[0.30, 0.32, np.nan],
        aircraft_mass=[70_000.0, 69_400.0, 68_800.0],
    )
    for col in ("fuel_flow", "engine_efficiency", "aircraft_mass"):
        assert not out[col].isna().any(), col
    assert out["aircraft_mass"].loc["2023-01-01 10:10:00"] == pytest.approx(69_400.0)


def test_complete_column_is_unchanged_by_the_fix() -> None:
    ff = _resample(fuel_flow=[1.0, 2.0, 3.0])["fuel_flow"]
    t = (ff.index - ff.index[0]).total_seconds().to_numpy()
    np.testing.assert_allclose(ff.to_numpy(), 1.0 + t / 600.0)


def test_column_without_any_valid_value_is_dropped() -> None:
    # Treated as not provided, so the performance step computes it from BADA.
    out = _resample(
        fuel_flow=[np.nan, np.nan, np.nan], engine_efficiency=[0.3, 0.3, 0.3]
    )
    assert "fuel_flow" not in out.columns
    assert "engine_efficiency" in out.columns
