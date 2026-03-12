"""
Trajectory Parser Parameters Module

Defines the base dataclass for parameters used by trajectory parser steps.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.neats_default_parameters import DEFAULT_MIN_ALTITUDE_FL
from pyneats.core.steps import BaseParams


__all__ = ["TrajectoryParserParams"]


@dataclass(frozen=True)
class TrajectoryParserParams(BaseParams):
    """
    Base parameters for trajectory parser steps.

    Attributes
    ----------
    min_altitude_fl : float | None
        Minimum Flight Level (inclusive). Trajectory points below this FL
        are discarded before conversion to metres. ``None`` disables the filter.
    """

    min_altitude_fl: float | None = DEFAULT_MIN_ALTITUDE_FL
