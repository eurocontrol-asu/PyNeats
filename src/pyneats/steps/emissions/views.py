from __future__ import annotations

from typing import Final, ClassVar, Tuple
from pyneats.steps.performance.views import FlightWithPerformance

__all__ = [
    "REQUIRED_EMISSION_COLS",
    "FlightWithEmissions",
]

REQUIRED_EMISSION_COLS: Final[Tuple[str, ...]] = ("nvpm_ei_m","nox_ei")


class FlightWithEmissions(FlightWithPerformance):
    """Zero-copy typed view for emissions-enriched flights."""

    REQUIRED: ClassVar[Tuple[str, ...]] = REQUIRED_EMISSION_COLS
