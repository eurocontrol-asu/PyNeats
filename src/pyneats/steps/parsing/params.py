"""
Trajectory Parser Parameters Module

Defines the base dataclass for parameters used by trajectory parser steps.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams


__all__ = ["TrajectoryParserParams"]


@dataclass(frozen=True)
class TrajectoryParserParams(BaseParams):
    """Base parameters for trajectory parser steps."""
