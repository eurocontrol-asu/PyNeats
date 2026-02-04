"""
BADA Trajectory Interpolation Module

Defines a placeholder for a physics-based trajectory reconstruction (e.g., BADA).
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.interpolation.params import TrajectoryInterpolationParams
from pyneats.steps.interpolation.protocol import TrajectoryInterpolator
from pyneats.steps.parsing.views import Flight4D


__all__ = [
    "BADATrajectoryPredictor",
    "BADAInterpolationParams",
]


@dataclass(frozen=True)
class BADAInterpolationParams(TrajectoryInterpolationParams):
    """
    Parameters for trajectory interpolation/resampling using BADA.
    """


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

    This class is not yet implemented. When implemented, it should return a validated, zero-copy Flight4D.
    """

    default_params = BADAInterpolationParams

    def run(self, flight: Flight4D) -> Flight4D:
        """
        Not implemented.

        Parameters
        ----------
        flight : Flight4D
            Input flight trajectory data.

        Returns
        -------
        Flight4D
            Interpolated flight trajectory (not implemented).

        Raises
        ------
        NotImplementedError
            Always raised.
        """
        raise NotImplementedError("BADATrajectoryPredictor is not yet implemented")
