"""Trajectory ``ts`` parsing in ``neats_json_to_flights`` (units audit item D2).

``ts`` is an RFC 3339 date-time. Its UTC offset must be applied, not
dropped, and every schema-valid form must be accepted. These tests need
neither BADA nor weather data.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pyneats.core.steps_registry import build
from pyneats.steps.parsing import TrajectoryParser
from pyneats.steps.parsing.neats_io import _ts_to_utc_string
from pyneats.steps.parsing.neats_io import neats_json_to_flights


def _flight(ts_values: list[str | None], flight_id: str = "TEST01") -> dict:
    """Minimal NEATS JSON flight at cruise level, one point per ``ts``."""
    return {
        "flight_information": {
            "flight_identification": flight_id,
            "departure_airport": "LFPG",
            "arrival_airport": "EDDF",
            "departure_date_time": "2025-11-02T10:00:00+0000",
            "aircraft_properties": {"aircraft_type": "A320"},
            "trajectory": {
                "trajectory_data": [
                    {"ts": ts, "lat": 49.0 + 0.1 * k, "lon": 2.5 + 0.1 * k, "fl": 350}
                    for k, ts in enumerate(ts_values)
                ]
            },
        }
    }


# ---------------------------------------------------------------------------
# _ts_to_utc_string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ts",
    [
        "2025-11-02T10:02:00+0000",
        "2025-11-02T10:02:00Z",
        "2025-11-02T10:02:00+00:00",
        "2025-11-02T10:02:00-00:00",
        "2025-11-02t10:02:00z",
        "2025-11-02 10:02:00Z",
    ],
)
def test_utc_forms_give_the_same_string(ts: str) -> None:
    assert _ts_to_utc_string(ts) == "2025-11-02 10:02:00"


@pytest.mark.parametrize(
    ("ts", "expected"),
    [
        ("2025-11-02T12:02:00+02:00", "2025-11-02 10:02:00"),
        ("2025-11-02T12:02:00+0200", "2025-11-02 10:02:00"),
        ("2025-11-02T04:32:00-05:30", "2025-11-02 10:02:00"),
        # Offsets that cross midnight, a month end and a year end.
        ("2025-11-02T01:00:00+02:00", "2025-11-01 23:00:00"),
        ("2025-10-31T23:30:00-01:00", "2025-11-01 00:30:00"),
        ("2026-01-01T00:15:00+01:00", "2025-12-31 23:15:00"),
    ],
)
def test_offset_is_applied(ts: str, expected: str) -> None:
    assert _ts_to_utc_string(ts) == expected


@pytest.mark.parametrize(
    "ts",
    [
        "2025-11-02T10:02:00.5Z",
        "2025-11-02T10:02:00.999999+0000",
        "2025-11-02T10:02:00.1234567890+00:00",
    ],
)
def test_fractional_seconds_are_truncated(ts: str) -> None:
    assert _ts_to_utc_string(ts) == "2025-11-02 10:02:00"


@pytest.mark.parametrize(
    ("ts", "expected"),
    [
        ("2025-11-02T10:02:00", "2025-11-02 10:02:00"),
        ("2025-11-02 10:02:00.5", "2025-11-02 10:02:00"),
    ],
)
def test_missing_offset_is_read_as_utc(ts: str, expected: str) -> None:
    assert _ts_to_utc_string(ts) == expected


@pytest.mark.parametrize(
    ("ts", "expected"),
    [
        ("2025-11-02T12:02:00.5+02:00", "2025-11-02 10:02:00"),
        ("2025-11-02 12:02:00+02:00", "2025-11-02 10:02:00"),
        # Only the seconds field loses its fraction: an offset with seconds
        # and a fraction is applied in full, then truncated (09:01:29.5).
        ("2025-11-02T10:02:00+01:00:30.5", "2025-11-02 09:01:29"),
    ],
)
def test_fraction_and_offset_combined(ts: str, expected: str) -> None:
    assert _ts_to_utc_string(ts) == expected


@pytest.mark.parametrize(
    "ts",
    [
        "garbage",
        "",
        "2025-13-02T10:02:00Z",
        "2025-11-02T25:02:00Z",
        "2025-02-29T10:02:00Z",
        "2025-07-09T23:59:60Z",  # leap second: not supported
        "2025-11-02T10:02:00." + chr(0xFF15) + "Z",  # non-ASCII digit in fraction
    ],
)
def test_invalid_date_time_raises(ts: str) -> None:
    with pytest.raises(ValueError, match="not a valid RFC 3339 date-time"):
        _ts_to_utc_string(ts)


@pytest.mark.parametrize("ts", [1752055200, 1.5, b"2025-11-02T10:02:00Z"])
def test_non_string_raises(ts: object) -> None:
    with pytest.raises(ValueError, match="is not a string"):
        _ts_to_utc_string(ts)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "ts", ["9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+00:01"]
)
def test_out_of_range_after_conversion_raises(ts: str) -> None:
    with pytest.raises(ValueError, match="outside years 1 to 9999"):
        _ts_to_utc_string(ts)


# ---------------------------------------------------------------------------
# neats_json_to_flights
# ---------------------------------------------------------------------------


def test_json_offsets_reach_the_time_column() -> None:
    ts_values = [
        "2025-11-02T12:00:00+02:00",
        "2025-11-02T10:01:00Z",
        "2025-11-02T10:02:00",
        None,
    ]
    (df,) = neats_json_to_flights([_flight(ts_values)])
    assert df["time"].tolist() == [
        "2025-11-02 10:00:00",
        "2025-11-02 10:01:00",
        "2025-11-02 10:02:00",
        None,
    ]


@pytest.mark.parametrize("bad", ["garbage", 1752055200])
def test_invalid_ts_error_names_flight_and_point(bad: object) -> None:
    ts_values = ["2025-11-02T10:00:00Z", bad]
    with pytest.raises(ValueError, match=r"flight 'BAD01', trajectory point 1: "):
        neats_json_to_flights([_flight(ts_values, "BAD01")])  # type: ignore[arg-type]


def test_offset_and_utc_inputs_parse_to_identical_times() -> None:
    """End to end through NeatsTrajectoryParser: a +02:00 trajectory and the
    same instants written in UTC give identical parsed times."""
    utc = [f"2025-11-02T10:{m:02d}:00Z" for m in range(0, 30, 5)]
    local = [f"2025-11-02T12:{m:02d}:00+02:00" for m in range(0, 30, 5)]
    (df_utc, df_local) = neats_json_to_flights(
        [_flight(utc, "UTC01"), _flight(local, "LOC01")]
    )
    parser = build(TrajectoryParser, "neats")
    t_utc = pd.Series(parser(df_utc)["time"])
    t_local = pd.Series(parser(df_local)["time"])
    assert t_utc.tolist() == t_local.tolist()
    assert t_utc.iloc[0] == pd.Timestamp("2025-11-02 10:00:00")
