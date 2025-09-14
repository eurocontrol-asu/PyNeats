from __future__ import annotations

from typing import Protocol, runtime_checkable
from pyneats.core.steps import Step
from pyneats.steps.trajectory import Flight4D

__all__ = ["TrajectoryInterpolator"]

@runtime_checkable
class TrajectoryInterpolator(Step[Flight4D, Flight4D], Protocol):
    """
    Interpolators consume a ParsedFlight and must return a ParsedFlight (zero-copy view).
    """
    # def __call__(self, flight: Flight4D) -> Flight4D: ...
