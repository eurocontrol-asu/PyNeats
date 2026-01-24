from __future__ import annotations

from typing import Protocol, runtime_checkable

from pyneats.core.steps import Step, StepError, VectorizedStep
from pyneats.steps.climate_functions.views import (
    FlightWithRFContrailsImpact,
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
class ContrailsModel(
    Step[FlightWithEmissions, FlightWithRFContrailsImpact],
    VectorizedStep[FlightWithEmissions, FlightWithRFContrailsImpact],
    Protocol,
):
    """
    A climate step that enriches a Flight with contrail impact columns.

    This protocol requires both single-flight (__call__) and fleet-level
    (run_fleet) execution capabilities.
    """


@runtime_checkable
class NonCO2Model(Step[FlightWithEmissions, FlightWithNonCO2Impact], Protocol):
    """A climate step that enriches a Flight with non-CO₂ impact columns."""


class ContrailsStepError(StepError):
    """Raised when contrail impact evaluation fails or yields invalid output."""


class ClimateStepError(StepError):
    """Raised when ACCF evaluation fails or yields invalid output."""
