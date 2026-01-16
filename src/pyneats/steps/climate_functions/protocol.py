from __future__ import annotations

from typing import Protocol, runtime_checkable

from pyneats.core.steps import Step, StepError
from pyneats.steps.climate_functions.views import (
    FlightWithContrailsImpact,
    FlightWithNonCO2Impact,
)
from pyneats.steps.emissions.views import FlightWithEmissions

__all__ = [
    "ContrailsModel",
    "NonCO2Model",
    "ContrailsStepError",
    "ClimateStepError",
]


@runtime_checkable
class ContrailsModel(Step[FlightWithEmissions, FlightWithContrailsImpact], Protocol):
    """A climate step that enriches a Flight with contrail impact columns."""


@runtime_checkable
class NonCO2Model(Step[FlightWithEmissions, FlightWithNonCO2Impact], Protocol):
    """A climate step that enriches a Flight with non-CO₂ impact columns."""


class ContrailsStepError(StepError):
    """Raised when contrail impact evaluation fails or yields invalid output."""


class ClimateStepError(StepError):
    """Raised when ACCF evaluation fails or yields invalid output."""
