from __future__ import annotations

from enum import Enum
from typing import Any
from pyneats.steps.interpolation.protocol import TrajectoryInterpolator
from pyneats.steps.interpolation.pycontrails_interpolation import PyContrailsInterpolator
from pyneats.steps.interpolation.bada_interpolation import BADATrajectoryPredictor

__all__ = ["InterpolatorType"]

class InterpolatorType(Enum):
    """Factory enum for creating trajectory interpolators."""
    PYCONTRAILS = PyContrailsInterpolator
    BADA = BADATrajectoryPredictor

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryInterpolator:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
