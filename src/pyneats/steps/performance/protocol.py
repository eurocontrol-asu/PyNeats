from __future__ import annotations

from typing import Protocol, runtime_checkable

from pyneats.core.steps import Step, StepError
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
    """
