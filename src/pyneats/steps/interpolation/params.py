"""
Trajectory Interpolation Parameters Module

Defines the dataclass for parameters used by trajectory interpolation steps.
"""
from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.neats_default_parameters import DEFAULT_INTERPOLATION_TIME
from pyneats.core.steps import BaseParams

__all__ = ["TrajectoryInterpolationParams"]


@dataclass(frozen=True)
class TrajectoryInterpolationParams(BaseParams):
    """
    Parameters for trajectory interpolation/resampling.

    Attributes
    ----------
    interpolation_time : str
        Time interval for interpolation (e.g., '1min').
    """
    interpolation_time: str = DEFAULT_INTERPOLATION_TIME
