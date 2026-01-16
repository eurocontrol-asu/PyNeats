from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.parsing.params import TrajectoryParserParams
from pyneats.steps.parsing.protocol import (
    TrajectoryParser,
)
from pyneats.steps.parsing.views import Flight4D

__all__ = [
    "OpenSkyParser",
    "OpenSkyParserParams",
]


@dataclass(frozen=True)
class OpenSkyParserParams(TrajectoryParserParams):
    """Parameters for parsing ADS-B trajectory data."""

    # Placeholder for future parameters
    pass


@register(TrajectoryParser, "adsb")
class OpenSkyParser(
    BaseStep[
        pd.DataFrame,
        Flight4D,
        OpenSkyParserParams,
    ]
):
    """Placeholder for an ADS-B specific parser yielding `Flight4D`."""

    default_params = OpenSkyParserParams

    def run(self, flight: pd.DataFrame) -> Flight4D:
        raise NotImplementedError("ADSBParser is not yet implemented")
