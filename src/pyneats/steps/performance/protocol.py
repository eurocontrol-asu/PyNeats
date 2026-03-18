from __future__ import annotations

from typing import Protocol
from typing import runtime_checkable

from pyneats.core.steps import Step
from pyneats.core.steps import StepError
from pyneats.steps.performance.views import FlightWithPerformance
from pyneats.steps.weather.weather_provider import FlightWithWeather


__all__ = [
    "PerformanceModel",
    "PerformanceStepError",
]


@runtime_checkable
class PerformanceModel(Step[FlightWithWeather, FlightWithPerformance], Protocol):
    """
    Protocol for performance model steps.

    Performance steps consume a weather-enriched flight and produce a
    performance-enriched flight (zero-copy view).
    """


class PerformanceStepError(StepError):
    """
    Raised when the performance step fails to evaluate or validate outputs.

    Parameters
    ----------
    message : str
        Error description.
    retryable : bool
        Whether the error may be resolved by retrying with modified input
        (e.g. altitude filtering). Structural errors (missing BADA paths,
        unknown aircraft) should set this to ``False``.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
