from __future__ import annotations

import logging
from pycontrails import Flight

from pyneats.core.steps import BaseStep
from pyneats.core.views import ValidationError
from pyneats.steps.trajectory import Flight4D
from pyneats.steps.interpolation.params import TrajectoryInterpolationParams
from pyneats.steps.interpolation.protocol import InterpolationStepError
from pyneats.core.steps_registry import register

__all__ = ["PyContrailsInterpolator"]

logger = logging.getLogger(__name__)



@register("interpolator", "pycontrails")
class PyContrailsInterpolator(BaseStep[Flight4D, Flight4D]):
    """
    Thin wrapper around `Flight.resample_and_fill`.

    - input:  Flight4D (validated upstream)
    - output: Flight4D (validated here, zero-copy)
    """

    def __init__(self, params: TrajectoryInterpolationParams | None = None) -> None:
        super().__init__()
        self.params = params or TrajectoryInterpolationParams()

    def run(self, flight: Flight4D) -> Flight4D:
        try:
            tmp: Flight = flight.resample_and_fill(self.params.interpolation_time)
        except Exception as e:
            raise InterpolationStepError(f"{type(self).__name__}: resample_and_fill failed: {e}") from e

        try:
            return Flight4D.from_flight(tmp)  # schema/type validation (zero-copy)
        except ValidationError as ve:
            raise InterpolationStepError(
                f"{type(self).__name__}: invalid resampled schema: {ve}"
            ) from ve
