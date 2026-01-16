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
        return Path(env_path).resolve()

    # Default path
    default_path = Path(__file__).parent.parent / "data" / "BADA"
    
    if default_path.is_dir() and default_path.exists():
        return default_path.resolve()
    
    return None 

