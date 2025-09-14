from __future__ import annotations

import logging
import pandas as pd

from pyneats.core.steps import BaseStage
from pyneats.steps.trajectory.views import Flight4D
from pyneats.steps.trajectory.nm_parser import FlightParsingError

__all__ = ["ADSBParser"]

logger = logging.getLogger(__name__)

class ADSBParser(BaseStage[pd.DataFrame, Flight4D]):
    """Placeholder for an ADS-B specific parser yielding `Flight4D`."""
    def __init__(self) -> None:
        super().__init__()

    def run(self, source: pd.DataFrame) -> Flight4D:
        raise FlightParsingError(type(self).__name__, "not implemented")
