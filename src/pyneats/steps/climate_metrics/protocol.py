from __future__ import annotations

from typing import Protocol, runtime_checkable

from pyneats.core.steps import Step, StepError
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
from pyneats.steps.climate_metrics.views import FlightWithClimateImpact

__all__ = [
    "ClimateImpactModel",
    "ClimateImpactStepError",
]


@runtime_checkable
class ClimateImpactModel(
    Step[FlightWithNonCO2Impact, FlightWithClimateImpact], Protocol
):
    """
    Cilmate Impatct Model steps consume a FlightWithNonCO2Impact and produce
    an climate-metrics-enriched flight (zero-copy typed view).
    """


class ClimateImpactStepError(StepError):
    """Raised when the climate impact step fails to evaluate or validate outputs."""
