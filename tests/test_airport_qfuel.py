"""Tests for airport-specific q_fuel fallback in NeatsTrajectoryParser.

Covers:
1. _load_airport_q_fuel(None) → {}
2. _load_airport_q_fuel(csv_path) → correct dict with uppercase keys
3. _load_airport_q_fuel(json_path) → correct dict with uppercase keys
4. _load_airport_q_fuel(bad_path) → {} + warning logged (no exception)
5. Parser uses airport value when operator did NOT provide q_fuel
6. Operator-provided q_fuel takes precedence over airport mapping
7. Unknown airport → q_fuel stays None → NEATSFuel uses DEFAULT_Q_FUEL
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from pyneats.core.neats_default_parameters import DEFAULT_Q_FUEL
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.neats_parser import _load_airport_q_fuel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AIRPORT_Q_FUEL_MAP = {
    "EGLL": 43_000_000.0,
    "LFPG": 44_000_000.0,
}

REQUIRED_ATTRS = {
    "flight_id": "FL001",
    "aircraft_type": "A320",
    "departure_airport": "EGLL",
    "arrival_airport": "LFPG",
    "model_type": "BADA4",
    "aobt": "2023-01-01 10:00:00",
}


def _make_csv(tmp_path: Path, mapping: dict[str, float]) -> Path:
    """Write a CSV file with columns 'airport' and 'q_fuel'."""
    p = tmp_path / "airport_qfuel.csv"
    lines = ["airport,q_fuel"] + [f"{k},{v}" for k, v in mapping.items()]
    p.write_text("\n".join(lines))
    return p


def _make_json(tmp_path: Path, mapping: dict[str, float]) -> Path:
    """Write a JSON file with airport→q_fuel mapping."""
    p = tmp_path / "airport_qfuel.json"
    p.write_text(json.dumps(mapping))
    return p


def _make_flight_df(
    departure_airport: str = "EGLL", q_fuel: float | None = None
) -> pd.DataFrame:
    """Build a minimal trajectory DataFrame accepted by NeatsTrajectoryParser."""
    data = {
        "latitude": [51.5, 51.6],
        "longitude": [-0.1, 0.0],
        "altitude": [100, 200],  # FL (will be converted to metres)
        "time": ["2023-01-01 10:00:00", "2023-01-01 10:05:00"],
    }
    df = pd.DataFrame(data)
    attrs: dict = {**REQUIRED_ATTRS, "departure_airport": departure_airport}
    if q_fuel is not None:
        attrs["q_fuel"] = q_fuel
    df.attrs = attrs
    return df


# ---------------------------------------------------------------------------
# 1. _load_airport_q_fuel(None) → {}
# ---------------------------------------------------------------------------


def test_load_airport_q_fuel_none():
    assert _load_airport_q_fuel(None) == {}


# ---------------------------------------------------------------------------
# 2. CSV loading
# ---------------------------------------------------------------------------


def test_load_airport_q_fuel_csv(tmp_path):
    csv_path = _make_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    result = _load_airport_q_fuel(str(csv_path))
    assert result == AIRPORT_Q_FUEL_MAP
    # Keys must be uppercase
    for k in result:
        assert k == k.upper()


def test_load_airport_q_fuel_csv_lowercase_keys(tmp_path):
    """CSV with lowercase airport codes should be normalised to uppercase."""
    csv_path = _make_csv(tmp_path, {"egll": 43_000_000.0, "lfpg": 44_000_000.0})
    result = _load_airport_q_fuel(str(csv_path))
    assert "EGLL" in result
    assert "LFPG" in result
    assert "egll" not in result


# ---------------------------------------------------------------------------
# 3. JSON loading
# ---------------------------------------------------------------------------


def test_load_airport_q_fuel_json(tmp_path):
    json_path = _make_json(tmp_path, AIRPORT_Q_FUEL_MAP)
    result = _load_airport_q_fuel(str(json_path))
    assert result == AIRPORT_Q_FUEL_MAP
    for k in result:
        assert k == k.upper()


def test_load_airport_q_fuel_json_lowercase_keys(tmp_path):
    """JSON with lowercase airport codes should be normalised to uppercase."""
    json_path = _make_json(tmp_path, {"egll": 43_000_000.0})
    result = _load_airport_q_fuel(str(json_path))
    assert "EGLL" in result
    assert "egll" not in result


# ---------------------------------------------------------------------------
# 4. Bad path → {} + warning (no exception)
# ---------------------------------------------------------------------------


def test_load_airport_q_fuel_missing_file_logs_warning(tmp_path, caplog):
    bad_path = str(tmp_path / "does_not_exist.csv")
    with caplog.at_level(logging.WARNING, logger="pyneats.steps.parsing.neats_parser"):
        result = _load_airport_q_fuel(bad_path)
    assert result == {}
    assert any(
        "Failed to load airport q_fuel mapping" in r.message for r in caplog.records
    )


def test_load_airport_q_fuel_malformed_csv_logs_warning(tmp_path, caplog):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("airport,wrong_column\nEGLL,not_a_number\n")
    with caplog.at_level(logging.WARNING, logger="pyneats.steps.parsing.neats_parser"):
        result = _load_airport_q_fuel(str(bad_csv))
    # Either KeyError (missing 'q_fuel' column) or ValueError (cast); both → {}
    assert result == {}
    assert any(
        "Failed to load airport q_fuel mapping" in r.message for r in caplog.records
    )


def test_load_airport_q_fuel_malformed_json_logs_warning(tmp_path, caplog):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{invalid json")
    with caplog.at_level(logging.WARNING, logger="pyneats.steps.parsing.neats_parser"):
        result = _load_airport_q_fuel(str(bad_json))
    assert result == {}
    assert any(
        "Failed to load airport q_fuel mapping" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# 5. Parser uses airport value when operator did NOT provide q_fuel
# ---------------------------------------------------------------------------


def test_parser_uses_airport_q_fuel_when_no_operator_value(tmp_path):
    csv_path = _make_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    parser = NeatsTrajectoryParser(airport_qfuel_path=str(csv_path))

    df = _make_flight_df(departure_airport="EGLL")  # no q_fuel in attrs
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == AIRPORT_Q_FUEL_MAP["EGLL"]


# ---------------------------------------------------------------------------
# 6. Operator-provided q_fuel takes precedence over airport mapping
# ---------------------------------------------------------------------------


def test_operator_q_fuel_takes_precedence_over_airport_mapping(tmp_path):
    csv_path = _make_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    parser = NeatsTrajectoryParser(airport_qfuel_path=str(csv_path))

    operator_q_fuel = 40_000_000.0
    df = _make_flight_df(departure_airport="EGLL", q_fuel=operator_q_fuel)
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == operator_q_fuel
    # Must NOT use the airport value
    assert flight.fuel.q_fuel != AIRPORT_Q_FUEL_MAP["EGLL"]


# ---------------------------------------------------------------------------
# 7. Unknown airport → NEATSFuel uses DEFAULT_Q_FUEL
# ---------------------------------------------------------------------------


def test_unknown_airport_falls_back_to_default_q_fuel(tmp_path):
    csv_path = _make_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    parser = NeatsTrajectoryParser(airport_qfuel_path=str(csv_path))

    df = _make_flight_df(departure_airport="XXXX")  # not in mapping, no q_fuel
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == DEFAULT_Q_FUEL


def test_no_mapping_file_falls_back_to_default_q_fuel():
    """When no mapping file is provided at all, DEFAULT_Q_FUEL is used."""
    parser = NeatsTrajectoryParser()

    df = _make_flight_df(departure_airport="EGLL")  # no q_fuel in attrs
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == DEFAULT_Q_FUEL
