"""
Climate Functions Parameters Module

Defines the dataclass for parameters used by climate function steps.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams


__all__ = ["ClimateParams"]


@dataclass(frozen=True)
class ClimateParams(BaseParams):
    """
    Parameters for climate function steps.

    Extend this class to define specific parameters for climate function models.
    """

    # Placeholder for future parameters
    pass
