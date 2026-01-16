from __future__ import annotations

from typing import ClassVar, Final
from pyneats.core.views import FlightView

__all__ = [
    "REQUIRED_4D_COLS",
    "OPTIONAL_COLS",
    "ATTRS_OPTIONAL",
    "ATTS_REQUIRED",
    "Flight4D",
]

REQUIRED_4D_COLS: Final[tuple[str, ...]] = (
    "latitude",
    "longitude",
    "altitude",
    "time",
)
OPTIONAL_COLS: Final[tuple[str, ...]] = (
    "fuel_flow",
    "aircraft_mass",
    "engine_efficiency",
    "true_airspeed",
)
ATTRS_OPTIONAL: Final[tuple[str, ...]] = (
    "takeoff_weight",
    "payload_factor",
    "hydrogen_content",
    "h_c_ratio",
    "q_fuel",
    "aircraft_series",
    "engine_uid",
    "aromatic_content",
    "sulphur_content",
    "naphtalene",
)

ATTS_REQUIRED: Final[tuple[str, ...]] = (
    "flight_id",
    "aircraft_type",
    "departure_airport",
    "arrival_airport",
    "model_type",
    "aobt",
)


class Flight4D(FlightView):
    """Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist."""

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_4D_COLS
    OPTIONAL: ClassVar[tuple[str, ...]] = OPTIONAL_COLS
    ATTRS_OPTIONAL: ClassVar[tuple[str, ...]] = ATTRS_OPTIONAL
    ATTRS_REQUIRED: ClassVar[tuple[str, ...]] = ATTS_REQUIRED
