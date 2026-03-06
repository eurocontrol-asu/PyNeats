"""Tests for airport-specific fuel-property fallback in NeatsTrajectoryParser.

Covers:
1. _load_airport_fuel_props(None) → {}
2. _load_airport_fuel_props(csv_path) — semicolon CSV, European commas → correct dict
3. _load_airport_fuel_props(json_path) → correct dict (q_fuel-only and multi-property)
4. _load_airport_fuel_props(bad_path) → {} + warning logged (no exception)
5. Parser uses airport values when operator did NOT provide fuel properties
6. Operator-provided values take precedence over airport mapping
7. Unknown airport → fuel stays at NEATSFuel defaults
8. Multi-property: all available airport props are applied when absent from operator data
9. Partial operator override: operator supplies q_fuel, airport fills h_c_ratio
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from pyneats.core.neats_default_parameters import DEFAULT_Q_FUEL
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.neats_parser import _load_airport_fuel_props


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


def _make_semicolon_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a semicolon-delimited CSV with European decimal commas."""
    p = tmp_path / "airport_fuel.csv"
    if not rows:
        p.write_text("Airport;q_fuel\n")
        return p
    headers = list(rows[0].keys())
    lines = [";".join(headers)]
    lines.extend(
        ";".join("" if v is None else str(v) for v in row.values()) for row in rows
    )
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _make_simple_csv(tmp_path: Path, mapping: dict[str, float]) -> Path:
    """Write a legacy comma-delimited CSV with columns 'airport' and 'q_fuel'."""
    p = tmp_path / "airport_qfuel.csv"
    lines = ["airport,q_fuel"] + [f"{k},{v}" for k, v in mapping.items()]
    p.write_text("\n".join(lines))
    return p


def _make_json(tmp_path: Path, mapping: dict) -> Path:
    """Write a JSON file."""
    p = tmp_path / "airport_fuel.json"
    p.write_text(json.dumps(mapping))
    return p


def _make_flight_df(
    departure_airport: str = "EGLL",
    **fuel_attrs,
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
    attrs.update({k: v for k, v in fuel_attrs.items() if v is not None})
    df.attrs = attrs
    return df


# ---------------------------------------------------------------------------
# 1. _load_airport_fuel_props(None) → {}
# ---------------------------------------------------------------------------


def test_load_airport_fuel_props_none():
    assert _load_airport_fuel_props(None) == {}


# ---------------------------------------------------------------------------
# 2. CSV loading (semicolon, European decimal commas)
# ---------------------------------------------------------------------------


def test_load_airport_fuel_props_semicolon_csv(tmp_path):
    rows = [
        {
            "Airport": "EGLL",
            "aromatics_content": "19,1",
            "h_c_ratio": "",
            "naphthalene": "0,36",
            "sulphur_content": "0,07",
            "q_fuel": "43000000",
        },
        {
            "Airport": "lfpg",
            "aromatics_content": "18,3",
            "h_c_ratio": "",
            "naphthalene": "0,51",
            "sulphur_content": "0,04",
            "q_fuel": "44000000",
        },
    ]
    csv_path = _make_semicolon_csv(tmp_path, rows)
    result = _load_airport_fuel_props(str(csv_path))

    assert "EGLL" in result
    assert "LFPG" in result  # lowercase normalised
    assert result["EGLL"]["q_fuel"] == 43_000_000.0
    assert result["EGLL"]["aromatic_content"] == 19.1
    assert result["EGLL"]["sulphur_content"] == 0.07
    assert result["EGLL"]["naphtalene"] == 0.36
    # empty h_c_ratio must be absent (not filled with NaN)
    assert "h_c_ratio" not in result["EGLL"]
    # Keys must be uppercase
    for k in result:
        assert k == k.upper()


def test_load_airport_fuel_props_legacy_csv(tmp_path):
    """Legacy comma-delimited q_fuel-only CSV is still accepted."""
    csv_path = _make_simple_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    result = _load_airport_fuel_props(str(csv_path))
    assert result["EGLL"]["q_fuel"] == 43_000_000.0
    assert result["LFPG"]["q_fuel"] == 44_000_000.0


def test_load_airport_fuel_props_csv_lowercase_keys(tmp_path):
    """Lowercase airport codes in CSV are normalised to uppercase."""
    csv_path = _make_simple_csv(tmp_path, {"egll": 43_000_000.0})
    result = _load_airport_fuel_props(str(csv_path))
    assert "EGLL" in result
    assert "egll" not in result


# ---------------------------------------------------------------------------
# 3. JSON loading
# ---------------------------------------------------------------------------


def test_load_airport_fuel_props_json_qfuel_only(tmp_path):
    """JSON with {airport: float} → treated as q_fuel-only."""
    json_path = _make_json(tmp_path, AIRPORT_Q_FUEL_MAP)
    result = _load_airport_fuel_props(str(json_path))
    assert result["EGLL"]["q_fuel"] == 43_000_000.0
    assert result["LFPG"]["q_fuel"] == 44_000_000.0


def test_load_airport_fuel_props_json_multi_property(tmp_path):
    """JSON with {airport: {col: value}} → multi-property."""
    payload = {
        "EGLL": {"q_fuel": 43_000_000.0, "h_c_ratio": 2.0},
        "lfpg": {"aromatics_content": 18.5},
    }
    json_path = _make_json(tmp_path, payload)
    result = _load_airport_fuel_props(str(json_path))
    assert result["EGLL"]["q_fuel"] == 43_000_000.0
    assert result["EGLL"]["h_c_ratio"] == 2.0
    assert result["LFPG"]["aromatic_content"] == 18.5


def test_load_airport_fuel_props_json_lowercase_keys(tmp_path):
    json_path = _make_json(tmp_path, {"egll": 43_000_000.0})
    result = _load_airport_fuel_props(str(json_path))
    assert "EGLL" in result
    assert "egll" not in result


# ---------------------------------------------------------------------------
# 4. Bad path → {} + warning (no exception)
# ---------------------------------------------------------------------------


def test_load_airport_fuel_props_missing_file_logs_warning(tmp_path, caplog):
    bad_path = str(tmp_path / "does_not_exist.csv")
    with caplog.at_level(logging.WARNING, logger="pyneats.steps.parsing.neats_parser"):
        result = _load_airport_fuel_props(bad_path)
    assert result == {}
    assert any(
        "Failed to load airport fuel properties" in r.message for r in caplog.records
    )


def test_load_airport_fuel_props_malformed_csv_logs_warning(tmp_path, caplog):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("wrong_column,other\nEGLL,not_a_number\n")
    with caplog.at_level(logging.WARNING, logger="pyneats.steps.parsing.neats_parser"):
        result = _load_airport_fuel_props(str(bad_csv))
    assert result == {}
    assert any(
        "Failed to load airport fuel properties" in r.message for r in caplog.records
    )


def test_load_airport_fuel_props_malformed_json_logs_warning(tmp_path, caplog):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{invalid json")
    with caplog.at_level(logging.WARNING, logger="pyneats.steps.parsing.neats_parser"):
        result = _load_airport_fuel_props(str(bad_json))
    assert result == {}
    assert any(
        "Failed to load airport fuel properties" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# 5. Parser uses airport value when operator did NOT provide fuel properties
# ---------------------------------------------------------------------------


def test_parser_uses_airport_q_fuel_when_no_operator_value(tmp_path):
    csv_path = _make_simple_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    parser = NeatsTrajectoryParser(airport_fuel_path=str(csv_path))

    df = _make_flight_df(departure_airport="EGLL")  # no q_fuel in attrs
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == AIRPORT_Q_FUEL_MAP["EGLL"]


# ---------------------------------------------------------------------------
# 6. Operator-provided values take precedence
# ---------------------------------------------------------------------------


def test_operator_q_fuel_takes_precedence_over_airport_mapping(tmp_path):
    csv_path = _make_simple_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    parser = NeatsTrajectoryParser(airport_fuel_path=str(csv_path))

    operator_q_fuel = 40_000_000.0
    df = _make_flight_df(departure_airport="EGLL", q_fuel=operator_q_fuel)
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == operator_q_fuel
    assert flight.fuel.q_fuel != AIRPORT_Q_FUEL_MAP["EGLL"]


# ---------------------------------------------------------------------------
# 7. Unknown airport → NEATSFuel uses DEFAULT_Q_FUEL
# ---------------------------------------------------------------------------


def test_unknown_airport_falls_back_to_default_q_fuel(tmp_path):
    csv_path = _make_simple_csv(tmp_path, AIRPORT_Q_FUEL_MAP)
    parser = NeatsTrajectoryParser(airport_fuel_path=str(csv_path))

    df = _make_flight_df(departure_airport="XXXX")  # not in mapping
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == DEFAULT_Q_FUEL


def test_no_mapping_file_falls_back_to_default_q_fuel():
    parser = NeatsTrajectoryParser()

    df = _make_flight_df(departure_airport="EGLL")
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == DEFAULT_Q_FUEL


# ---------------------------------------------------------------------------
# 8. Multi-property: all available airport props are applied
# ---------------------------------------------------------------------------


def test_parser_applies_all_available_airport_fuel_props(tmp_path):
    rows = [
        {
            "Airport": "EGLL",
            "aromatics_content": "19,1",
            "h_c_ratio": "2,0",
            "naphthalene": "0,36",
            "sulphur_content": "0,07",
            "q_fuel": "43000000",
        }
    ]
    csv_path = _make_semicolon_csv(tmp_path, rows)
    parser = NeatsTrajectoryParser(airport_fuel_path=str(csv_path))

    df = _make_flight_df(departure_airport="EGLL")  # no fuel attrs from operator
    flight = parser.run(df)

    assert flight.fuel is not None
    assert flight.fuel.q_fuel == 43_000_000.0
    # h_c_ratio is consumed by NEATSFuel to compute hydrogen_content, but preserved in attrs
    assert flight.attrs.get("h_c_ratio") == 2.0


# ---------------------------------------------------------------------------
# 9. Partial operator override: operator supplies q_fuel, airport fills h_c_ratio
# ---------------------------------------------------------------------------


def test_operator_partial_override_airport_fills_gaps(tmp_path):
    rows = [
        {
            "Airport": "EGLL",
            "aromatics_content": "",
            "h_c_ratio": "2,0",
            "naphthalene": "",
            "sulphur_content": "",
            "q_fuel": "43000000",
        }
    ]
    csv_path = _make_semicolon_csv(tmp_path, rows)
    parser = NeatsTrajectoryParser(airport_fuel_path=str(csv_path))

    operator_q_fuel = 40_000_000.0
    df = _make_flight_df(departure_airport="EGLL", q_fuel=operator_q_fuel)
    flight = parser.run(df)

    # Operator q_fuel must win
    assert flight.fuel is not None
    assert flight.fuel.q_fuel == operator_q_fuel
    # Airport h_c_ratio must be applied (operator did not supply it); stored in attrs
    assert flight.attrs.get("h_c_ratio") == 2.0
