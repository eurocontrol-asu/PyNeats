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
    parser.addoption(
        "--bada-root-path",
        action="store",
        default=None,
        help="Path to BADA root directory (containing BADA3 and BADA4 subdirectories)",
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
def bada_root_path(pytestconfig) -> Path | None:
    """Get path to BADA root directory.

    Priority:
    1. --bada-root-path command line option
    2. BADA_ROOT_PATH environment variable
    3. tests/data/BADA directory (default)

    Returns None if not available (tests will skip).
    """
    # Command line option
    path = pytestconfig.getoption("bada_root_path")
    if path:
        return Path(path).resolve()

    # Environment variable
    env_path = os.environ.get("BADA_ROOT_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir():
            return path.resolve()

    # Default path (for local development)
    default_path = Path(__file__).parent / "data" / "BADA"
    if default_path.is_dir():
        return default_path.resolve()

    return None


@pytest.fixture
def bada3_path(bada_root_path) -> Path | None:
    """Get path to BADA3 data directory.

    Priority:
    1. BADA3_PATH environment variable (CI workflows)
    2. bada_root_path/BADA3 (if bada_root_path exists)

    Returns None if not available (tests will skip).
    """
    # Environment variable (for CI workflows)
    env_path = os.environ.get("BADA3_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir():
            return path.resolve()

    # Derive from bada_root_path
    if bada_root_path:
        bada3 = bada_root_path / "BADA3"
        if bada3.is_dir():
            return bada3.resolve()

    return None


@pytest.fixture
def bada4_path(bada_root_path) -> Path | None:
    """Get path to BADA4 data directory.

    Priority:
    1. BADA4_PATH environment variable (CI workflows)
    2. bada_root_path/BADA4 (if bada_root_path exists)

    Returns None if not available (tests will skip).
    Default to BADA4 for tests.
    """
    # Environment variable (for CI workflows)
    env_path = os.environ.get("BADA4_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir():
            return path.resolve()

    # Derive from bada_root_path
    if bada_root_path:
        bada4 = bada_root_path / "BADA4"
        if bada4.is_dir():
            return bada4.resolve()

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
