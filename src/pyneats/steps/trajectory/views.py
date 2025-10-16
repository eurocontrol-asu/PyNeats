from __future__ import annotations

from typing import Final, ClassVar, Tuple
from pyneats.core.views import FlightView

__all__ = [
    "REQUIRED_4D_COLS",
    "Flight4D",
]

REQUIRED_4D_COLS: Final[Tuple[str, ...]] = (
    "latitude",
    "longitude",
    "altitude",
    "time",
)
OPTIONAL_4D_ATTRS: Final[Tuple[str, ...]] = (
    "takeoff_weight",
    "payload_factor",
    "engine_type",
    "hydrogen_content",
    "h_c_ratio",
    "q_fuel",
)


class Flight4D(FlightView):
    """Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist."""

    REQUIRED: ClassVar[Tuple[str, ...]] = REQUIRED_4D_COLS
    ATTRS_OPTIONAL: ClassVar[Tuple[str, ...]] = OPTIONAL_4D_ATTRS
