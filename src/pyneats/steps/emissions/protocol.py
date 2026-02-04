"""
Emissions Protocol Module

Defines the protocol and error class for emissions steps.
"""

from __future__ import annotations

from typing import Protocol
from typing import runtime_checkable

from pyneats.core.steps import Step
from pyneats.core.steps import StepError
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.performance import FlightWithPerformance


__all__ = [
    "EmissionModel",
    "EmissionStepError",
]


@runtime_checkable
class EmissionModel(Step[FlightWithPerformance, FlightWithEmissions], Protocol):
    """
    Protocol for emissions steps.

    Emission steps consume a performance-enriched flight and produce
    an emissions-enriched flight (zero-copy typed view).
    """


class EmissionStepError(StepError):
    """
    Normalized domain error for the emissions step.
    """
