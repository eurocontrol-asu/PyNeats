import dotenv
import logging
from pathlib import Path
from typing import Any


def pytest_configure(config: Any) -> None:
    _log = logging.getLogger()
    _log.setLevel(logging.INFO)
    _log.info(f"Loading: {Path(__file__).parent / 'tests.env'}")
    dotenv.load_dotenv(Path(__file__).parent / "tests.env")
