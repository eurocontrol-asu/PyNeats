"""
Interpolation step package for NEATS.

Exposes all trajectory interpolation classes, protocols, and parameters.
"""
from pyneats.steps.interpolation.bada_interpolation import (
    BADAInterpolationParams,
    BADATrajectoryPredictor,
)
from pyneats.steps.interpolation.params import TrajectoryInterpolationParams
from pyneats.steps.interpolation.protocol import (
    TrajectoryInterpolationStepError,
    TrajectoryInterpolator,
)
from pyneats.steps.interpolation.pycontrails_interpolation import (
    PyContrailsInterpolationParams,
    PyContrailsInterpolator,
)

__all__ = [
    "TrajectoryInterpolator",
    "TrajectoryInterpolationParams",
    "TrajectoryInterpolationStepError",
    "TrajectoryInterpolationParams",
    "PyContrailsInterpolationParams",
    "PyContrailsInterpolator",
    "BADATrajectoryPredictor",
    "BADAInterpolationParams",
]
