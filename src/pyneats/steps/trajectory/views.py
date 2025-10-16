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
ATTRS_OPTIONAL: Final[Tuple[str, ...]] = (
    "takeoff_weight",
    "payload_factor",
    "engine_type",
    "hydrogen_content",
    "h_c_ratio",
    "q_fuel",
)
ATTS_REQUIRED: Final[Tuple[str, ...]] = (
    "flight_id",
    "aircraft_type",
    "departure_airport",
    "arrival_airport",
    "callsign",
    "model_type",
)


class Flight4D(FlightView):
    """Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist."""

    REQUIRED: ClassVar[Tuple[str, ...]] = REQUIRED_4D_COLS
    ATTRS_OPTIONAL: ClassVar[Tuple[str, ...]] = ATTRS_OPTIONAL
    ATTRS_REQUIRED: ClassVar[Tuple[str, ...]] = ATTS_REQUIRED
