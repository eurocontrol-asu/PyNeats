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


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (>10s)")
    config.addinivalue_line("markers", "requires_bada: marks tests requiring BADA data")
    config.addinivalue_line("markers", "requires_weather: marks tests requiring weather data")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


def pytest_generate_tests(metafunc):
    """Generate test parameters with flight IDs for better error reporting."""
    if "flight_idx" in metafunc.fixturenames:
        # Load flight IDs from golden output for test identification
        try:
            traffic_path = Path(__file__).parent / "data"
            filepath = traffic_path / "output_flights_5.json"

            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    flight_ids = []
                    for i, d in enumerate(data):
                        fid = d.get("flight_id", f"flight_{i}")
                        # flight_id is a list (one per waypoint), extract first element
                        if isinstance(fid, list) and len(fid) > 0:
                            fid = fid[0]
                        elif not isinstance(fid, str):
                            fid = f"flight_{i}"
                        flight_ids.append(fid)
            else:
                flight_ids = [f"flight_{i}" for i in range(5)]
        except Exception:
            flight_ids = [f"flight_{i}" for i in range(5)]

        # Parametrize with indices, but use flight_ids for test identification
        metafunc.parametrize("flight_idx", range(len(flight_ids)), ids=flight_ids)


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


@pytest.fixture(scope="session")
def weather_path(pytestconfig) -> Path | None:
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

    return None


@pytest.fixture(scope="session")
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
        return Path(env_path).resolve()

    # Default path
    default_path = Path(__file__).parent.parent / "data" / "BADA"

    if default_path.is_dir() and default_path.exists():
        return default_path.resolve()

    return None
 

