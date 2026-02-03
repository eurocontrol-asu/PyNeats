"""
OpenSky ADS-B Trajectory Parser Module

Defines a placeholder for an ADS-B specific parser yielding Flight4D.
"""

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
    """
    Parameters for parsing ADS-B trajectory data.

    Extend this class to define specific parameters for ADS-B parsers.
    """
    pass


@register(TrajectoryParser, "adsb")  # type: ignore[type-abstract]
class OpenSkyParser(
    BaseStep[
        pd.DataFrame,
        Flight4D,
        OpenSkyParserParams,
    ]
):
    """
    Placeholder for an ADS-B specific parser yielding `Flight4D`.
    """
    default_params = OpenSkyParserParams

    def run(self, flight: pd.DataFrame) -> Flight4D:
        """
        Not implemented.

        Parameters
        ----------
        flight : pd.DataFrame
            Input ADS-B trajectory data.

        Returns
        -------
        Flight4D
            Parsed flight data (not implemented).

        Raises
        ------
        NotImplementedError
            Always raised.
        """
        raise NotImplementedError("ADSBParser is not yet implemented")
