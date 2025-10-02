from __future__ import annotations
from typing import ClassVar, Final, Tuple
from pyneats.steps.weather.weather_provider import FlightWithWeather

__all__ = [
    "REQUIRED_PERF_COLS",
    "FlightWithPerformance",
]

REQUIRED_PERF_COLS: Final[Tuple[str, ...]] = (
    "true_airspeed",
    "fuel_flow",
    "engine_efficiency",
)


class FlightWithPerformance(FlightWithWeather):
    """Zero-copy typed view for performance-enriched flights."""

    REQUIRED: ClassVar[Tuple[str, ...]] = REQUIRED_PERF_COLS
