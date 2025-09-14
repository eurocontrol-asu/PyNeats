from __future__ import annotations
from typing import Protocol, runtime_checkable
from pyneats.core.steps import Step
from pyneats.steps.weather.weather_provider import FlightWithWeather
from pyneats.steps.performance.views import FlightWithPerformance

__all__ = ["PerformanceModel"]

@runtime_checkable
class PerformanceModel(Step[FlightWithWeather, FlightWithPerformance], Protocol):
    """
    Performance steps consume a weather-enriched flight and produce
    a performance-enriched flight (zero-copy view).
    """
    # def __call__(self, flight: FlightWithWeather) -> FlightWithPerformance: ...
