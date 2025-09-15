from __future__ import annotations

import logging
from pyneats.core.steps import BaseStep
from pyneats.steps.trajectory import Flight4D
from pyneats.steps.interpolation.params import TrajectoryInterpolationParams
from pyneats.steps.interpolation.protocol import InterpolationStepError
from pyneats.core.steps_registry import register

__all__ = ["BADATrajectoryPredictor"]

logger = logging.getLogger(__name__)

@register("interpolator", "bada-predictor")
class BADATrajectoryPredictor(BaseStep[Flight4D, Flight4D]):
    """
    Placeholder for a physics-based trajectory reconstruction (e.g., BADA).
    Must return a Flight4D (validated, zero-copy).
    """

    def __init__(self, params: TrajectoryInterpolationParams | None = None) -> None:
        super().__init__()
        self.params = params or TrajectoryInterpolationParams()

    def run(self, flight: Flight4D) -> Flight4D:
        raise InterpolationStepError(f"{type(self).__name__}: not implemented")
