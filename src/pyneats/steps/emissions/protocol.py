from __future__ import annotations

from typing import Protocol, runtime_checkable
from pyneats.core.steps import Step, StepError
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.emissions.views import FlightWithEmissions

__all__ = [
    "EmissionModel",
    "EmissionStepError",
]


@runtime_checkable
class EmissionModel(Step[FlightWithPerformance, FlightWithEmissions], Protocol):
    """
    Emission steps consume a performance-enriched flight and produce
    an emissions-enriched flight (zero-copy typed view).
    """


class EmissionStepError(StepError):
    """Normalized domain error for the emissions step."""
