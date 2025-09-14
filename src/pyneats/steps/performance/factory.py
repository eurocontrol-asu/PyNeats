from __future__ import annotations
from enum import Enum
from typing import Any
from pyneats.steps.performance.protocol import PerformanceModel
from pyneats.steps.performance.bada_model import BADAPerformanceModel

__all__ = ["PerformanceModelType"]

class PerformanceModelType(Enum):
    BADA = BADAPerformanceModel

    def get(self, *args: Any, **kwargs: Any) -> PerformanceModel:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
