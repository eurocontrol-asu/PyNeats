from __future__ import annotations

from dataclasses import dataclass
from pycontrails import Flight
from pyneats.core.steps import BaseStep
from pyneats.core.views import ValidationError
from pyneats.core.steps_registry import register
from pyneats.steps.trajectory import Flight4D
from pyneats.steps.interpolation.params import TrajectoryInterpolationParams
from pyneats.steps.interpolation.protocol import (
    TrajectoryInterpolator,
    TrajectoryInterpolationStepError,
)


__all__ = [
    "PyContrailsInterpolationParams",
    "PyContrailsInterpolator",
]


@dataclass(frozen=True)
class PyContrailsInterpolationParams(TrajectoryInterpolationParams):
    """Parameters for trajectory interpolation/resampling."""


@register(TrajectoryInterpolator, "pycontrails")
class PyContrailsInterpolator(
    BaseStep[
        Flight4D,
        Flight4D,
        PyContrailsInterpolationParams,
    ]
):
    """
    Thin wrapper around `Flight.resample_and_fill`.

    - input:  Flight4D (validated upstream)
    - output: Flight4D (validated here, zero-copy)
    """

    default_params = PyContrailsInterpolationParams

    def run(self, flight: Flight4D) -> Flight4D:
        try:
            tmp: Flight = flight.resample_and_fill(self.params.interpolation_time)
        except Exception as e:
            raise TrajectoryInterpolationStepError(
                f"resample_and_fill failed: {e}"
            ) from e

        try:
            return Flight4D.from_flight(tmp)  # schema/type validation (zero-copy)
        except ValidationError as ve:
            raise TrajectoryInterpolationStepError(
                f"invalid resampled schema: {ve}"
            ) from ve
