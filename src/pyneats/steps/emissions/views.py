"""
Emissions Views Module

Defines zero-copy typed views for emissions-enriched flights.
"""

from __future__ import annotations

from typing import ClassVar
from typing import Final

from pyneats.steps.performance.views import FlightWithPerformance


__all__ = [
    "REQUIRED_EMISSION_COLS",
    "FlightWithEmissions",
]

REQUIRED_EMISSION_COLS: Final[tuple[str, ...]] = ("nvpm_ei_m", "nox_ei")


class FlightWithEmissions(FlightWithPerformance):
    """
    Zero-copy typed view for emissions-enriched flights.

    Attributes
    ----------
    REQUIRED : ClassVar[tuple[str, ...]]
        Required emission columns.
    """

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_EMISSION_COLS
