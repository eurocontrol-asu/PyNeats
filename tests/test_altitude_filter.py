"""Tests for the altitude filter in NeatsTrajectoryParser.

Covers:
1. Default filter (FL15) keeps normal flight points
2. Custom min_altitude_fl filters low-altitude points
3. All points filtered out → TrajectoryParserStepError
4. Filter bound is inclusive (exactly min_altitude_fl is kept)
5. Single point surviving the filter → valid Flight4D
"""

from __future__ import annotations

import pandas as pd
import pytest

from pyneats.core.neats_default_parameters import DEFAULT_MIN_ALTITUDE_FL
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.protocol import TrajectoryParserStepError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_ATTRS: dict[str, str] = {
    "flight_id": "FL001",
    "aircraft_type": "A320",
    "departure_airport": "EGLL",
    "arrival_airport": "LFPG",
    "model_type": "BADA4",
    "aobt": "2023-01-01 10:00:00",
}


def _make_flight_df(altitudes: list[float]) -> pd.DataFrame:
    """Build a trajectory DataFrame with the given FL altitudes."""
    n = len(altitudes)
    times = [f"2023-01-01 10:{i:02d}:00" for i in range(n)]
    data = {
        "latitude": [51.5 + i * 0.1 for i in range(n)],
        "longitude": [-0.1 + i * 0.1 for i in range(n)],
        "altitude": altitudes,
        "time": times,
    }
    df = pd.DataFrame(data)
    df.attrs = {**REQUIRED_ATTRS}
    return df


# ---------------------------------------------------------------------------
# 1. Default filter (FL15) keeps normal flight points
# ---------------------------------------------------------------------------


def test_no_filter_default_keeps_all_normal_points() -> None:
    """With default min_altitude_fl=15, typical cruise FLs are kept."""
    parser = NeatsTrajectoryParser()
    df = _make_flight_df([100, 200, 350])  # all well above FL15
    flight = parser.run(df)
    assert len(flight) == 3


# ---------------------------------------------------------------------------
# 2. Custom min_altitude_fl filters low-altitude points
# ---------------------------------------------------------------------------


def test_min_altitude_filter() -> None:
    """Points below min_altitude_fl are removed."""
    parser = NeatsTrajectoryParser(min_altitude_fl=200)
    df = _make_flight_df([100, 200, 350])
    flight = parser.run(df)
    assert len(flight) == 2


# ---------------------------------------------------------------------------
# 3. All points filtered out → TrajectoryParserStepError
# ---------------------------------------------------------------------------


def test_all_filtered_out_raises() -> None:
    """If every point is below min_altitude_fl, an error is raised."""
    parser = NeatsTrajectoryParser(min_altitude_fl=500)
    df = _make_flight_df([100, 200])
    with pytest.raises(TrajectoryParserStepError, match="altitude filter"):
        parser.run(df)


# ---------------------------------------------------------------------------
# 4. Filter bound is inclusive
# ---------------------------------------------------------------------------


def test_filter_inclusive_bound() -> None:
    """A point exactly at min_altitude_fl is kept."""
    parser = NeatsTrajectoryParser(min_altitude_fl=200)
    df = _make_flight_df([100, 200, 300])
    flight = parser.run(df)
    assert len(flight) == 2  # FL 200 and 300 kept


# ---------------------------------------------------------------------------
# 5. Single point surviving → valid Flight4D
# ---------------------------------------------------------------------------


def test_single_point_survives() -> None:
    """A single surviving point produces a valid Flight4D."""
    parser = NeatsTrajectoryParser(min_altitude_fl=300)
    df = _make_flight_df([100, 350])
    flight = parser.run(df)
    assert len(flight) == 1


# ---------------------------------------------------------------------------
# 6. Disabled filter (None) keeps all points
# ---------------------------------------------------------------------------


def test_disabled_filter_keeps_all() -> None:
    """Setting min_altitude_fl=None disables the filter entirely."""
    parser = NeatsTrajectoryParser(min_altitude_fl=None)
    df = _make_flight_df([5, 10, 100])  # points below default FL15
    flight = parser.run(df)
    assert len(flight) == 3


# ---------------------------------------------------------------------------
# 7. Default constant value
# ---------------------------------------------------------------------------


def test_default_min_altitude_is_fl15() -> None:
    """The default is FL15 as defined in neats_default_parameters."""
    assert DEFAULT_MIN_ALTITUDE_FL == 15
    parser = NeatsTrajectoryParser()
    assert parser.params.min_altitude_fl == 15
