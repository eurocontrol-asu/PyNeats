from __future__ import annotations

from typing import ClassVar, Final

from pyneats.steps.weather.weather_provider import FlightWithWeather

__all__ = [
    "REQUIRED_PERF_COLS",
    "FlightWithPerformance",
]


"""
Performance-Enriched Flight View Module

Defines the zero-copy typed view for flights enriched with performance data.
"""

REQUIRED_PERF_COLS: Final[tuple[str, ...]] = (
    "true_airspeed",
    "fuel_flow",
    "engine_efficiency",
)



class FlightWithPerformance(FlightWithWeather):
    """
    Zero-copy typed view for performance-enriched flights.

    Attributes
    ----------
    REQUIRED : ClassVar[tuple[str, ...]]
        Required columns for a performance-enriched flight.
    """
    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_PERF_COLS
