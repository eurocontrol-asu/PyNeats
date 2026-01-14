# tests/conftest.py
import json
import logging
import os
from pathlib import Path
from typing import List

import pytest

from pyneats.core.views import FlightView

_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)


def pytest_addoption(parser):
    parser.addoption(
        "--met-cache-dir",
        action="store",
        default=None,  # will be filled from pyproject.toml
        help="Path to test met cache data folder",
    )


@pytest.fixture
def weather_path(pytestconfig) -> Path:
    """Get path to weather data directory.

    Priority:
    1. --met-cache-dir command line option
    2. MET_CACHE_DIR environment variable
    3. tests/data directory (default)
    """
    path = pytestconfig.getoption("met_cache_dir")

    if path:
        return Path(path).resolve()

    env_path = os.environ.get("MET_CACHE_DIR")

    if env_path:
        return Path(env_path).resolve()

    # Default path
    return Path(__file__).parent / "data"


@pytest.fixture
def bada3_path() -> Path | None:
    """Get path to BADA3 data directory.

    Returns None if not available (tests will skip).
    """
    env_path = os.environ.get("BADA3_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir():
            return path.resolve()
    return None


@pytest.fixture
def bada4_path() -> Path | None:
    """Get path to BADA4 data directory.

    Returns None if not available (tests will skip).
    Default to BADA4 for tests.
    """
    env_path = os.environ.get("BADA4_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir():
            return path.resolve()
    return None


@pytest.fixture
def input_flights() -> List[dict]:
    """Load raw input flights from JSON (NM format, before processing).

    Returns:
        List of 5 flight dicts in NM JSON format
    """
    input_path = Path(__file__).parent / "data" / "input_flights_5.json"

    if not input_path.exists():
        pytest.skip(f"Input flights file not found: {input_path}")

    with open(input_path, encoding="utf-8") as f:
        flights = json.load(f)

    _log.info(f"Loaded {len(flights)} input flights from {input_path}")
    return flights


@pytest.fixture
def golden_flights() -> List[FlightView]:
    """Load golden output flights (FleetView format, after full pipeline).

    Returns:
        List of FlightView objects with all columns (weather, performance, emissions, climate)
    """
    output_path = Path(__file__).parent / "data" / "output_flights_5.json"

    if not output_path.exists():
        pytest.skip(f"Golden flights file not found: {output_path}")

    with open(output_path, encoding="utf-8") as f:
        data = json.load(f)

    # Convert to FlightView objects
    flights = [FlightView.from_dict(d) for d in data]

    _log.info(f"Loaded {len(flights)} golden flights from {output_path}")
    return flights
