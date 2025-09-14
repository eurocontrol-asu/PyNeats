from __future__ import annotations

from enum import Enum
from typing import Any
from pyneats.steps.trajectory.protocol import TrajectoryParser
from pyneats.steps.trajectory.nm_parser import NMTrajectoryParser
from pyneats.steps.trajectory.adsb_parser import ADSBParser

__all__ = ["TrajectoryParserType"]

class TrajectoryParserType(Enum):
    """Factory enum for trajectory parsers."""
    NM = NMTrajectoryParser
    ADSB = ADSBParser

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryParser:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
