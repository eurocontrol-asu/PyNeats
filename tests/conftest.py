# tests/conftest.py
import pytest
from pathlib import Path
import os
import logging

_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)


def pytest_addoption(parser):
    parser.addoption(
        "--met-cache-dir",
        action="store",
        default=None,  # will be filled from pyproject.toml
        help="Path to test met chache data folder",
    )


@pytest.fixture
def weather_path(pytestconfig):
    path = pytestconfig.getoption("met_cache_dir")

    if path:
        return Path(path).resolve()

    env_path = os.environ.get("MET_CACHE_DIR")

    if env_path:
        return Path(env_path).resolve()

    # Default path
    return Path(__file__).parent / "data"
