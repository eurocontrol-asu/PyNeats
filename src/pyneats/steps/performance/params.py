from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams

__all__ = ["PerformanceModelParams"]


@dataclass(frozen=True)
class PerformanceModelParams(BaseParams):
    pass
