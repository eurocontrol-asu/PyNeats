from __future__ import annotations

from dataclasses import dataclass
from pyneats.core.parameters import DEFAULT_INTERPOLATION_TIME

__all__ = ["TrajectoryInterpolationParams","InterpolationStepError"]

@dataclass(frozen=True)
class TrajectoryInterpolationParams:
    """Parameters for trajectory interpolation/resampling."""
    interpolation_time: str = DEFAULT_INTERPOLATION_TIME  # e.g., "1min"

class InterpolationStepError(Exception):
    """Raised when interpolation/resampling fails or yields invalid output."""