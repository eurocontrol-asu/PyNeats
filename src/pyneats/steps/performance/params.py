"""
Performance Model Parameters Module

Defines the base dataclass for parameters used by performance model steps.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams


__all__ = ["PerformanceModelParams"]


@dataclass(frozen=True)
class PerformanceModelParams(BaseParams):
    """
    Base parameters for performance model steps.

    Extend this class to define specific parameters for performance models.
    """

    pass
