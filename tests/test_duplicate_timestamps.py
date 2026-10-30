"""Of the points with the same time, the parser keeps the first in input order.

The parser sorts the points by time and drops the points with a duplicate
time. The sort was ``sort_values("time")``, which is a quicksort and is not
stable, so which point of a same-time group was kept was not defined (in 24
NM sample flights the first 2 to 18 points have the same time). The sort is
now stable: the first point in input order is kept. The number of dropped
points is logged at DEBUG level.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pytest

from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser


ATTRS = {
    "flight_id": "FL001",
    "aircraft_type": "A320",
    "departure_airport": "EGLL",
    "arrival_airport": "LFPG",
    "model_type": "BADA4",
    "aobt": "2023-01-01 10:00:00",
}

N_TIMES = 40
SEEDS = range(50)


def _points_with_pairs() -> pd.DataFrame:
    """Points at N_TIMES minutes; each time has two points (ids 2k and 2k+1).

    The latitude of a point is its id, so the kept point shows which one won.
    """
    rows = []
    for k in range(N_TIMES):
        t = pd.Timestamp("2023-01-01 10:00:00") + pd.Timedelta(minutes=k)
        for j in range(2):
            pid = 2 * k + j
            rows.append(
                {
                    "latitude": float(pid) * 0.01,
                    "longitude": 0.0,
                    "altitude": 350,
                    "time": t.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    return pd.DataFrame(rows)


def _parse(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    df.attrs = dict(ATTRS)
    return NeatsTrajectoryParser().run(df).dataframe


def _first_in_input_order(df: pd.DataFrame) -> np.ndarray:
    """Latitude of the first point of each time, in input order, sorted by time."""
    first = df.drop_duplicates(subset="time", keep="first")
    return first.sort_values("time", kind="stable")["latitude"].to_numpy()


@pytest.mark.parametrize("seed", SEEDS)
def test_shuffled_points_keep_first_in_input_order(seed: int) -> None:
    df = _points_with_pairs()
    rng = np.random.default_rng(seed)
    df = df.iloc[rng.permutation(len(df))].reset_index(drop=True)

    out = _parse(df)

    assert len(out) == N_TIMES
    np.testing.assert_array_equal(out["latitude"].to_numpy(), _first_in_input_order(df))


def test_sorted_pairs_keep_first_point() -> None:
    """Input already in time order: point 2k is kept, never point 2k+1."""
    out = _parse(_points_with_pairs())

    np.testing.assert_array_equal(
        out["latitude"].to_numpy(), np.arange(0, 2 * N_TIMES, 2) * 0.01
    )


def test_reversed_pairs_keep_first_in_input_order() -> None:
    """Input in reverse order: point 2k+1 now comes first, so it is kept."""
    df = _points_with_pairs().iloc[::-1]

    out = _parse(df)

    np.testing.assert_array_equal(
        out["latitude"].to_numpy(), np.arange(1, 2 * N_TIMES, 2) * 0.01
    )


def test_point_with_missing_value_is_not_the_one_kept() -> None:
    """A point dropped for a missing value does not count as the first."""
    df = _points_with_pairs()
    df.loc[0, "altitude"] = np.nan

    out = _parse(df)

    assert out["latitude"].iloc[0] == pytest.approx(0.01)
    assert len(out) == N_TIMES


def test_dropped_duplicates_logged_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        _parse(_points_with_pairs())

    msgs = [r for r in caplog.records if "duplicate time" in r.getMessage()]
    assert len(msgs) == 1
    assert msgs[0].levelno == logging.DEBUG
    assert f"Dropped {N_TIMES} point(s)" in msgs[0].getMessage()


def test_no_duplicates_no_log(caplog: pytest.LogCaptureFixture) -> None:
    df = _points_with_pairs().drop_duplicates(subset="time")
    with caplog.at_level(logging.DEBUG):
        out = _parse(df)

    assert len(out) == N_TIMES
    assert not [r for r in caplog.records if "duplicate time" in r.getMessage()]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def _json_flight(points: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "flight_information": {
            "flight_identification": "FL001",
            "departure_date_time": "2025-07-09T10:00:00Z",
            "departure_airport": "EGLL",
            "arrival_airport": "LFPG",
            "aircraft_properties": {"aircraft_type": "A320"},
            "trajectory": {"trajectory_data": points},
        }
    }


@pytest.mark.parametrize("seed", range(10))
def test_json_same_second_points_keep_first(seed: int) -> None:
    """Fractional seconds are cut, so points in the same second collapse;
    the first in input order is kept (JSON input, NM layout)."""
    base = pd.Timestamp("2025-07-09T10:00:00")
    points = []
    for k in range(N_TIMES):
        t = base + pd.Timedelta(minutes=k)
        for j, frac in enumerate((".2", ".7")):
            points.append(
                {
                    "ts": t.strftime("%Y-%m-%dT%H:%M:%S") + frac + "Z",
                    "lat": (2 * k + j) * 0.01,
                    "lon": 0.0,
                    "fl": 350,
                }
            )
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(points))
    points = [points[i] for i in order]

    (df,) = neats_json_to_flights([_json_flight(points)])
    out = NeatsTrajectoryParser().run(df).dataframe

    expected = []
    seen: set[int] = set()
    for p in points:
        minute = round(p["lat"] / 0.01) // 2
        if minute not in seen:
            seen.add(minute)
            expected.append((minute, p["lat"]))
    expected.sort()
    np.testing.assert_allclose(out["latitude"].to_numpy(), [e[1] for e in expected])
