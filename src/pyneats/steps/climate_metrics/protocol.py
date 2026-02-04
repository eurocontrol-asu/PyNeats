"""
Climate Metrics Protocol Module

Defines the protocol and error class for climate metrics steps.
"""

from __future__ import annotations

from typing import Protocol
from typing import runtime_checkable

from pyneats.core.steps import Step
from pyneats.core.steps import StepError
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
    Protocol for climate impact model steps.

    Climate impact model steps consume a FlightWithNonCO2Impact and produce
    a climate-metrics-enriched flight (zero-copy typed view).
    """


class ClimateImpactStepError(StepError):
    """
    Raised when the climate impact step fails to evaluate or validate outputs.
    """
