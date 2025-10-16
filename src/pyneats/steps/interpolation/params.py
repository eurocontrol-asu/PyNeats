from __future__ import annotations

from dataclasses import dataclass
from pyneats.core.neats_default_parameters import DEFAULT_INTERPOLATION_TIME
from pyneats.core.steps import BaseParams

__all__ = ["TrajectoryInterpolationParams"]


@dataclass(frozen=True)
class TrajectoryInterpolationParams(BaseParams):
    """Parameters for trajectory interpolation/resampling."""

    interpolation_time: str = DEFAULT_INTERPOLATION_TIME
