from __future__ import annotations

from typing import Protocol, runtime_checkable
from pyneats.core.steps import Step
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.core.steps import StepError

__all__ = ["EmissionModel", "EmissionsStepError"]

@runtime_checkable
class EmissionModel(Step[FlightWithPerformance, FlightWithEmissions], Protocol):
    """
    Emission steps consume a performance-enriched flight and produce
    an emissions-enriched flight (zero-copy typed view).
    """
    # def __call__(self, flight: FlightWithPerformance) -> FlightWithEmissions: ...

class EmissionsStepError(StepError):
    """Normalized domain error for the emissions step."""