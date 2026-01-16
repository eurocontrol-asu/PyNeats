from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams

__all__ = ["ClimateParams"]


@dataclass(frozen=True)
class ClimateParams(BaseParams):
    """Parameters for climate."""

    # Placeholder for future parameters
    pass
