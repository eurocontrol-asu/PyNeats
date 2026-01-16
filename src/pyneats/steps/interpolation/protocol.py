from __future__ import annotations

from typing import Protocol, runtime_checkable

from pyneats.core.steps import Step, StepError
from pyneats.steps.parsing.views import Flight4D

__all__ = [
    "TrajectoryInterpolator",
    "TrajectoryInterpolationStepError",
]


@runtime_checkable
class TrajectoryInterpolator(Step[Flight4D, Flight4D], Protocol):
    """
    Interpolators consume a ParsedFlight and must return a ParsedFlight (zero-copy view).
    """


class TrajectoryInterpolationStepError(StepError):
    """Raised when interpolation/resampling fails or yields invalid output."""
