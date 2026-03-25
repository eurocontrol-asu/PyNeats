"""
Trajectory Parser Parameters Module

Defines the base dataclass for parameters used by trajectory parser steps.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.neats_default_parameters import DEFAULT_MAX_PRESSURE_LEVEL
from pyneats.core.steps import BaseParams


__all__ = ["TrajectoryParserParams"]


@dataclass(frozen=True)
class TrajectoryParserParams(BaseParams):
    """Base parameters for trajectory parser steps.

    Attributes
    ----------
    max_pressure_level : float | None
        Maximum pressure level (hPa) allowed for the flight's highest point.
        Flights whose *minimum* pressure level exceeds this threshold (i.e. never
        reach high enough altitude) are rejected.  ``500 hPa`` ≈ FL180.
        Set to ``None`` to disable the filter.
    """

    max_pressure_level: float | None = DEFAULT_MAX_PRESSURE_LEVEL
