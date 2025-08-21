# steps/interpolator.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, runtime_checkable, Protocol

from pycontrails import Flight

from pyneats.core.steps import BaseStep, Step, StepError
from pyneats.steps.trajectory import Flight4D  # strong input/output type
from pyneats.core.parameters import DEFAULT_INTERPOLATION_TIME  # keep your source

__all__ = [
    "TrajectoryInterpolationParams",
    "TrajectoryInterpolator",
    "PyContrailsInterpolator",
    "BADATrajectoryPredictor",
    "InterpolatorType",
    "InterpolationStepError",
]

logger = logging.getLogger(__name__)


# ---- error type ----------------------------------------------------
class InterpolationStepError(StepError):
    """Raised when interpolation/resampling fails or yields invalid output."""


# ---- params --------------------------------------------------------
@dataclass(frozen=True)
class TrajectoryInterpolationParams:
    """Parameters for trajectory interpolation/resampling."""
    interpolation_time: str = DEFAULT_INTERPOLATION_TIME  # e.g., "1min"


# ---- protocol: strong contract (ParsedFlight -> ParsedFlight) -----
@runtime_checkable
class TrajectoryInterpolator(Step[Flight4D, Flight4D], Protocol):
    """
    Interpolators consume a ParsedFlight and must return a ParsedFlight
    (zero-copy validated view).
    """
    # Protocol inherits: def __call__(self, flight: In) -> Out: ...


# ---- PyContrails interpolator: resample + fill --------------------
class PyContrailsInterpolator(BaseStep[Flight4D, Flight4D]):
    """
    Thin wrapper around `Flight.resample_and_fill`.

    - input:  ParsedFlight (validated upstream)
    - output: ParsedFlight (validated here, zero-copy)
    """

    def __init__(self, params: TrajectoryInterpolationParams | None = None) -> None:
        super().__init__()
        self.params = params or TrajectoryInterpolationParams()

    def run(self, flight: Flight4D) -> Flight4D:
        # (Optional) input re-validation; cheap and catches upstream drift
        #if self.validate_inputs:
        #    flight = Flight4D.from_flight(flight)

        try:
            out: Flight = flight.resample_and_fill(self.params.interpolation_time)
        except Exception as e:
            raise InterpolationStepError(type(self).__name__, f"resample_and_fill failed: {e}") from e

        # Validate schema and return typed zero-copy view
        return Flight4D.from_flight(out)


# ---- BADA predictor (placeholder with same contract) ---------------
class BADATrajectoryPredictor(BaseStep[Flight4D, Flight4D]):
    """
    Placeholder for a physics-based trajectory reconstruction (e.g., BADA).
    Must return a ParsedFlight (validated, zero-copy).
    """

    def __init__(self, params: TrajectoryInterpolationParams | None = None) -> None:
        super().__init__()
        self.params = params or TrajectoryInterpolationParams()

    def run(self, flight: Flight4D) -> Flight4D:
        raise InterpolationStepError(type(self).__name__, "not implemented")


# ---- factory enum (kept for now) ----------------------------------
class InterpolatorType(Enum):
    PYCONTRAILS = PyContrailsInterpolator
    BADA = BADATrajectoryPredictor

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryInterpolator:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
