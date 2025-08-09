# interpolator.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Any

from pycontrails import Flight

from .trajectory import ParsedFlight  # zero-copy validator for required 4D cols
from pyneats.parameters import DEFAULT_INTERPOLATION_TIME

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
class InterpolationStepError(RuntimeError):
    """Raised when interpolation/resampling fails or yields invalid output."""


# ---- params --------------------------------------------------------
@dataclass(frozen=True)
class TrajectoryInterpolationParams:
    """Parameters for trajectory interpolation."""
    interpolation_time: str = DEFAULT_INTERPOLATION_TIME


# ---- protocol: return a base Flight for composability --------------
class TrajectoryInterpolator(Protocol):
    """Callable that takes a Flight and returns an interpolated Flight."""
    def __call__(self, flight: Flight) -> Flight: ...


# --- PyContrails interpolator: resample + fill ---
class PyContrailsInterpolator:
    """
    Thin wrapper around `Flight.resample_and_fill`.

    - Returns a base `Flight` to keep the pipeline flexible.
    - Immediately validates via `ParsedFlight.from_flight(out)` (zero-copy) to fail fast.
    """

    def __init__(self, params: TrajectoryInterpolationParams | None = None) -> None:
        self.params = params or TrajectoryInterpolationParams()

    def __call__(self, flight: Flight) -> Flight:
        try:
            out: Flight = flight.resample_and_fill(self.params.interpolation_time)
        except Exception as e:
            logger.exception("Interpolation backend failed (resample_and_fill)")
            raise InterpolationStepError(f"Interpolation failed: {e}") from e

        # Validate that required 4D columns are still present
        try:
            _ = ParsedFlight.from_flight(out)
        except KeyError as e:
            logger.error("Interpolated Flight missing required 4D columns: %s", e)
            raise InterpolationStepError(f"Interpolated Flight invalid: {e}") from e

        logger.info(
            "Interpolation completed successfully at interval=%s; points=%d",
            self.params.interpolation_time,
            len(out.data),
        )
        return out


# --- BADA interpolator: Placeholder ---
class BADATrajectoryPredictor:
    """
    Placeholder for a physics-based trajectory reconstruction (BADA).

    Contract: return a base `Flight`; validate with `ParsedFlight` (zero-copy).
    """

    def __init__(self, params: TrajectoryInterpolationParams | None = None) -> None:
        self.params = params or TrajectoryInterpolationParams()

    def __call__(self, flight: Flight) -> Flight:
        raise NotImplementedError("BADA trajectory predictor not yet implemented")


# ---- factory -------------------------------------------------------
class InterpolatorType(Enum):
    """Enum factory for trajectory interpolators/predictors."""
    PYCONTRAILS = PyContrailsInterpolator
    BADA = BADATrajectoryPredictor

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryInterpolator:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
