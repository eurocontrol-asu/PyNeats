from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams

__all__ = ["TrajectoryParserParams"]


@dataclass(frozen=True)
class TrajectoryParserParams(BaseParams):
    """Parameters for trajectory parsing."""

    # Placeholder for future parameters
    pass
