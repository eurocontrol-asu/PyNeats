"""Test fixtures for NM traffic data (input and output flights)."""

import json
from pathlib import Path

import pytest

from pyneats.core.views import FlightView


@pytest.fixture(scope="session")
def nm_input() -> list[dict]:
    """Load raw NM input flights (5 flights) from JSON.

    Returns:
        List of raw flight dictionaries (NM JSON format)

    Note:
        Session-scoped for performance - loaded once per test session.
    """
    traffic_path = Path(__file__).parent.parent / "data"

    if not traffic_path.is_dir():
        raise RuntimeError(f"Test traffic path directory does not exist: {traffic_path}")

    filepath = traffic_path / "input_flights_5.json"

    if not filepath.exists():
        raise FileNotFoundError(f"Input flights not found: {filepath}")

    with open(filepath, encoding="utf-8") as fh:
        data = json.load(fh)

    return data


@pytest.fixture(scope="session")
def nm_output() -> list[FlightView]:
    """Load expected NM output flights (5 flights with full pipeline results) from JSON.

    Returns:
        List of FlightView objects (fully processed with all columns)

    Note:
        Session-scoped for performance - loaded once per test session.
        Tests should use .copy() when modifying flight data to avoid side effects.
    """
    traffic_path = Path(__file__).parent.parent / "data"

    if not traffic_path.is_dir():
        raise RuntimeError(f"Test traffic path directory does not exist: {traffic_path}")

    filepath = traffic_path / "output_flights_5.json"

    if not filepath.exists():
        raise FileNotFoundError(f"Output flights not found: {filepath}")

    with open(filepath, encoding="utf-8") as fh:
        data = json.load(fh)

    flights = []

    for d in data:
        f = FlightView.from_dict(d)
        flights.append(f)

    return flights

