from __future__ import annotations

from typing import Final, ClassVar, Tuple
from pyneats.core.views import FlightView

__all__ = [
    "REQUIRED_4D_COLS",
    "Flight4D",
]

REQUIRED_4D_COLS: Final[Tuple[str, ...]] = ("latitude", "longitude", "altitude", "time")


class Flight4D(FlightView):
    """Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist."""

    REQUIRED: ClassVar[Tuple[str, ...]] = REQUIRED_4D_COLS
