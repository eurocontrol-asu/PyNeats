from __future__ import annotations

import pandas as pd
from typing import Protocol, runtime_checkable
from pyneats.core.steps import Stage
from pyneats.steps.trajectory.views import Flight4D

__all__ = ["TrajectoryParser"]

@runtime_checkable
class TrajectoryParser(Stage[pd.DataFrame, Flight4D], Protocol):
    """Parses a tabular source into a validated `Flight4D` (zero-copy view)."""
    # def __call__(self, source: pd.DataFrame) -> Flight4D: ...
