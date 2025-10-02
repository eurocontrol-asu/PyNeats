from __future__ import annotations

from dataclasses import dataclass
from pyneats.core.steps import BaseParams

__all__ = ["EmissionParams"]


@dataclass(frozen=True)
class EmissionParams(BaseParams):
    """Parameters for emissions."""

    # Placeholder for future parameters
    pass
