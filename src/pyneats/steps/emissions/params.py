"""
Emissions Parameters Module

Defines the dataclass for parameters used by emissions steps.
"""
from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams

__all__ = ["EmissionParams"]


@dataclass(frozen=True)
class EmissionParams(BaseParams):
    """
    Parameters for emissions.

    Extend this class to define specific parameters for emissions models.
    """
    # Placeholder for future parameters
    pass
