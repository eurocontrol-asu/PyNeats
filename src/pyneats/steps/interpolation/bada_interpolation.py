from __future__ import annotations

from dataclasses import dataclass
from pyneats.core.steps import BaseStep
from pyneats.steps.trajectory import Flight4D
from pyneats.core.steps_registry import register
from pyneats.steps.interpolation.params import TrajectoryInterpolationParams
from pyneats.steps.interpolation.protocol import (
    TrajectoryInterpolator,
)

__all__ = [
    "BADATrajectoryPredictor",
    "BADAInterpolationParams",
]


@dataclass(frozen=True)
class BADAInterpolationParams(TrajectoryInterpolationParams):
    """Parameters for trajectory interpolation/resampling."""


@register(TrajectoryInterpolator, "bada-predictor")
class BADATrajectoryPredictor(
    BaseStep[
        Flight4D,
        Flight4D,
        BADAInterpolationParams,
    ]
):
    """
    Placeholder for a physics-based trajectory reconstruction (e.g., BADA).
    Must return a Flight4D (validated, zero-copy).
    """

    default_params = BADAInterpolationParams

    def run(self, flight: Flight4D) -> Flight4D:
        raise NotImplementedError("BADATrajectoryPredictor is not yet implemented")
