from __future__ import annotations

from typing import Final, ClassVar, Tuple
from pyneats.core.views import FlightView

__all__ = [
    "REQUIRED_4D_COLS",
    "OPTIONAL_COLS",
    "ATTRS_OPTIONAL",
    "ATTS_REQUIRED",
    "Flight4D",
]

REQUIRED_4D_COLS: Final[Tuple[str, ...]] = (
    "latitude",
    "longitude",
    "altitude",
    "time",
)
OPTIONAL_COLS: Final[Tuple[str, ...]] = (
    "fuel_flow",
    "aircraft_mass",
    "engine_efficiency",
    "true_airspeed",
)
ATTRS_OPTIONAL: Final[Tuple[str, ...]] = (
    "takeoff_weight",
    "payload_factor",
    "hydrogen_content",
    "h_c_ratio",
    "q_fuel",
    "aircraft_series",
    "engine_id",
    "aromatic_content",
    "sulfur_content",
    "naphtalene",
)

ATTS_REQUIRED: Final[Tuple[str, ...]] = (
    "flight_id",
    "aircraft_type",
    "departure_airport",
    "arrival_airport",
    "registration",
    "model_type",
    "aobt"
)


class Flight4D(FlightView):
    """Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist."""

    REQUIRED: ClassVar[Tuple[str, ...]] = REQUIRED_4D_COLS
    OPTIONAL: ClassVar[Tuple[str, ...]] = OPTIONAL_COLS
    ATTRS_OPTIONAL: ClassVar[Tuple[str, ...]] = ATTRS_OPTIONAL
    ATTRS_REQUIRED: ClassVar[Tuple[str, ...]] = ATTS_REQUIRED
