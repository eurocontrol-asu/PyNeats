"""
Climate Functions Protocol Module

Defines protocols and error classes for contrail and non-CO2 climate function steps.
"""

from __future__ import annotations

from typing import Protocol
from typing import runtime_checkable

from pyneats.core.steps import Step
from pyneats.core.steps import StepError
from pyneats.core.steps import VectorizedStep
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
from pyneats.steps.climate_functions.views import FlightWithRFContrailsImpact
from pyneats.steps.emissions.views import FlightWithEmissions


__all__ = [
    "ContrailsModel",
    "NonCO2Model",
    "ContrailsStepError",
    "ACCFStepError",
    "OpenAirClimStepError",
]


@runtime_checkable
class ContrailsModel(
    Step[FlightWithEmissions, FlightWithRFContrailsImpact],
    VectorizedStep[FlightWithEmissions, FlightWithRFContrailsImpact],
    Protocol,
):
    """
    Protocol for contrail climate function steps.

    A climate step that enriches a Flight with contrail impact columns.
    Requires both single-flight (__call__) and fleet-level (run_fleet) execution capabilities.
    """


@runtime_checkable
class NonCO2Model(Step[FlightWithEmissions, FlightWithNonCO2Impact], Protocol):
    """
    Protocol for non-CO2 climate function steps.

    A climate step that enriches a Flight with non-CO2 impact columns.
    """


class ContrailsStepError(StepError):
    """
    Raised when contrail impact evaluation fails or yields invalid output.
    """


class ACCFStepError(StepError):
    """
    Raised when ACCF evaluation fails or yields invalid output.
    """


class OpenAirClimStepError(StepError):
    """
    Raised when OpenAirClim evaluation fails or yields invalid output.
    """
