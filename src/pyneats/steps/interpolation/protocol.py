"""
Trajectory Interpolator Protocol Module

Defines the protocol and error class for trajectory interpolation steps.
"""

from __future__ import annotations

from typing import Protocol
from typing import runtime_checkable

from pyneats.core.steps import Step
from pyneats.core.steps import StepError
from pyneats.steps.parsing.views import Flight4D


__all__ = [
    "TrajectoryInterpolator",
    "TrajectoryInterpolationStepError",
]


@runtime_checkable
class TrajectoryInterpolator(Step[Flight4D, Flight4D], Protocol):
    """
    Protocol for trajectory interpolation steps.

    Interpolators consume a ParsedFlight and must return a ParsedFlight (zero-copy view).
    """


class TrajectoryInterpolationStepError(StepError):
    """
    Raised when interpolation/resampling fails or yields invalid output.
    """
