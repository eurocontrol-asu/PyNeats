from __future__ import annotations

import logging
import pandas as pd
from dataclasses import dataclass
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.trajectory.views import Flight4D
from pyneats.steps.trajectory.params import TrajectoryParserParams
from pyneats.steps.trajectory.protocol import (
    TrajectoryParser,
    TrajectoryParserStepError,
)

__all__ = [
    "ADSBParser",
    "ADSBParserParams",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ADSBParserParams(TrajectoryParserParams):
    """Parameters for parsing ADS-B trajectory data."""

    # Placeholder for future parameters
    pass


@register(TrajectoryParser, "adsb")
class ADSBParser(
    BaseStep[
        pd.DataFrame,
        Flight4D,
        ADSBParserParams,
    ]
):
    """Placeholder for an ADS-B specific parser yielding `Flight4D`."""

    default_params = ADSBParserParams

    def run(self, source: pd.DataFrame) -> Flight4D:
        raise NotImplementedError("ADSBParser is not yet implemented")
