from __future__ import annotations
from typing import Protocol, runtime_checkable
from pyneats.core.steps import Step, StepError
from pyneats.steps.climate.views import (
    FlightWithContrailsImpact,
    FlightWithNonCO2Impact,
    FlightWithClimateImpact,
)
from pyneats.steps.emissions.views import FlightWithEmissions

__all__ = [
    "ContrailsModel",
    "NonCO2Model",
    "ClimateImpactModel",
    "ContrailsStepError",
    "ClimateStepError",
    "ClimateImpactStepError",
]


@runtime_checkable
class ContrailsModel(Step[FlightWithEmissions, FlightWithContrailsImpact], Protocol):
    """A climate step that enriches a Flight with contrail impact columns."""


@runtime_checkable
class NonCO2Model(Step[FlightWithEmissions, FlightWithNonCO2Impact], Protocol):
    """A climate step that enriches a Flight with non-CO₂ impact columns."""


@runtime_checkable
class ClimateImpactModel(
    Step[FlightWithNonCO2Impact, FlightWithClimateImpact], Protocol
):
    """
    Cilmate Impatct Model steps consume a FlightWithNonCO2Impact and produce
    an climate-metrics-enriched flight (zero-copy typed view).
    """


class ContrailsStepError(StepError):
    """Raised when contrail impact evaluation fails or yields invalid output."""


class ClimateStepError(StepError):
    """Raised when ACCF evaluation fails or yields invalid output."""


class ClimateImpactStepError(StepError):
    """Raised when the climate impact step fails to evaluate or validate outputs."""
