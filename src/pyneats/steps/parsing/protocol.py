from __future__ import annotations
from typing import Protocol, runtime_checkable
import pandas as pd
from pyneats.steps.parsing.views import Flight4D
from pyneats.core.steps import Step, StepError

__all__ = [
    "TrajectoryParser",
    "TrajectoryParserStepError",
]


@runtime_checkable
class TrajectoryParser(Step[pd.DataFrame, Flight4D], Protocol):
    """Parses a tabular source into a validated `Flight4D` (zero-copy view)."""


class TrajectoryParserStepError(StepError):
    """Raised when a trajectory table cannot be parsed into a valid Flight."""
