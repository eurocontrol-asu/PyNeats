# tests/conftest.py
"""Pytest configuration and fixtures for PyNeats tests.

This module provides:
- Auto-discovery of golden test cases from tests/data/golden/
- Parametrized fixtures for input/output pairs
- Weather and BADA path configuration
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from pyneats.core.views import FlightView

_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)

# Path to golden test data
GOLDEN_DIR = Path(__file__).parent / "data" / "golden"


# -----------------------------------------------------------------------------
# Pytest hooks
# -----------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (>10s)")
    config.addinivalue_line("markers", "requires_bada: marks tests requiring BADA data")
    config.addinivalue_line("markers", "requires_weather: marks tests requiring weather data")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--met-cache-dir",
        action="store",
        default=None,
        help="Path to test met cache data folder",
    )
    parser.addoption(
        "--bada-root-path",
        action="store",
        default=None,
        help="Path to BADA root directory (containing BADA3 and BADA4 subdirectories)",
    )


# -----------------------------------------------------------------------------
# Golden test case discovery
# -----------------------------------------------------------------------------


def discover_golden_cases() -> list[str]:
    """Discover all golden test cases by scanning for *_input.json files.

    Returns:
        List of case names (e.g., ["fleet_5_flights", "single_flight_basic"])

    Each case name corresponds to a pair of files:
        - {case_name}_input.json
        - {case_name}_output.json
    """
    if not GOLDEN_DIR.is_dir():
        _log.warning("Golden data directory not found: %s", GOLDEN_DIR)
        return []

    cases = []
    for input_file in sorted(GOLDEN_DIR.glob("*_input.json")):
        case_name = input_file.stem.replace("_input", "")
        output_file = GOLDEN_DIR / f"{case_name}_output.json"
        if output_file.exists():
            cases.append(case_name)
        else:
            _log.warning("Golden case '%s' has input but no output file", case_name)

    return cases


# -----------------------------------------------------------------------------
# Fixtures: Golden test data
# -----------------------------------------------------------------------------


@pytest.fixture(params=discover_golden_cases())
def golden_case(request: pytest.FixtureRequest) -> str:
    """Parametrized fixture yielding each golden case name.

    Tests using this fixture will run once per golden case.
    """
    return request.param


@pytest.fixture
def golden_input_path(golden_case: str) -> Path:
    """Path to the input JSON file for the current golden case."""
    return GOLDEN_DIR / f"{golden_case}_input.json"


@pytest.fixture
def golden_output_path(golden_case: str) -> Path:
    """Path to the output JSON file for the current golden case."""
    return GOLDEN_DIR / f"{golden_case}_output.json"


@pytest.fixture
def golden_input(golden_input_path: Path) -> list[dict[str, Any]]:
    """Load input flights for the current golden case.

    Returns:
        List of raw flight dictionaries (NM JSON format)
    """
    with open(golden_input_path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def golden_output(golden_output_path: Path) -> list[FlightView]:
    """Load expected output flights for the current golden case.

    Returns:
        List of FlightView objects (fully processed with all columns)
    """
    with open(golden_output_path, encoding="utf-8") as fh:
        data = json.load(fh)

    return [FlightView.from_dict(d) for d in data]


# -----------------------------------------------------------------------------
# Fixtures: Weather and BADA paths
# -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def weather_path(pytestconfig: pytest.Config) -> Path | None:
    """Get path to weather data directory.

    Priority:
    1. --met-cache-dir command line option
    2. MET_CACHE_DIR environment variable
    3. None (tests will skip)
    """
    path = pytestconfig.getoption("met_cache_dir")
    if path:
        return Path(path).resolve()

    env_path = os.environ.get("MET_CACHE_DIR")
    if env_path:
        return Path(env_path).resolve()

    return None


@pytest.fixture(scope="session")
def bada_root_path(pytestconfig: pytest.Config) -> Path | None:
    """Get path to BADA root directory.

    Priority:
    1. --bada-root-path command line option
    2. BADA_ROOT_PATH environment variable
    3. None (tests will skip)
    """
    path = pytestconfig.getoption("bada_root_path")
    if path:
        return Path(path).resolve()

    env_path = os.environ.get("BADA_ROOT_PATH")
    if env_path:
        return Path(env_path).resolve()

    return None


@pytest.fixture(scope="session")
def weather(weather_path: Path | None):
    """Load weather data from Zarr stores.

    Returns:
        WeatherStore instance or None if weather data not available
    """
    # Import here to avoid issues if pyBADA not installed
    from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr

    if weather_path is None or not weather_path.is_dir():
        _log.warning("weather_path does not exist: %s", weather_path)
        return None

    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"

    if not met_store.is_dir():
        _log.warning("met_store does not exist: %s", met_store)
        return None

    if not rad_store.is_dir():
        _log.warning("rad_store does not exist: %s", rad_store)
        return None

    if not wind_store.is_dir():
        _log.warning("wind_store does not exist: %s", wind_store)
        wind_store = None  # optional

    return get_weather_from_zarr(ZarrPaths(met_store, rad_store, wind_store))
