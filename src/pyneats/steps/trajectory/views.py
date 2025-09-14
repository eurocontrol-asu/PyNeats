from __future__ import annotations

from typing import Final
from pyneats.core.views import FlightView

__all__ = ["REQUIRED_4D_COLS", "Flight4D"]

# Canonical 4D schema
REQUIRED_4D_COLS: Final[tuple[str, ...]] = ("latitude", "longitude", "altitude", "time")

class Flight4D(FlightView):
    """Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist."""
    REQUIRED = REQUIRED_4D_COLS
