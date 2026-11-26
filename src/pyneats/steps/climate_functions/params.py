"""
Climate Functions Parameters Module

Defines the dataclass for parameters used by climate function steps.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.neats_default_parameters import DEFAULT_NON_CO2_SCALING
from pyneats.core.steps import BaseParams


__all__ = ["ClimateParams"]


@dataclass(frozen=True)
class ClimateParams(BaseParams):
    """
    Parameters for climate function steps.

    Extend this class to define specific parameters for climate function models.

    Attributes:
        non_co2_scaling: Non-CO2 scaling (see ``pyneats.core.non_co2_scaling``).
            The fleet and flight runners set it from
            ``RunnerConfig.non_co2_scaling``.
    """

    non_co2_scaling: str = DEFAULT_NON_CO2_SCALING
