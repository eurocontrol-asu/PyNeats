"""
Flight4D View Module

Defines the zero-copy, typed view for 4D flight data (latitude, longitude, altitude, time).
"""

from __future__ import annotations

from typing import ClassVar
from typing import Final

from pyneats.core.views import FlightView


__all__ = [
    "REQUIRED_4D_COLS",
    "OPTIONAL_COLS",
    "ATTRS_OPTIONAL",
    "ATTS_REQUIRED",
    "Flight4D",
]

REQUIRED_4D_COLS: Final[tuple[str, ...]] = (
    "latitude",  # degrees (decimal, WGS 84)
    "longitude",  # degrees (decimal, WGS 84)
    # Flight level (hundreds of ft) at parser input; metres of ISA pressure
    # altitude after NeatsTrajectoryParser.
    "altitude",
    # Parsed as UTC; tz-naive UTC in the parsed Flight.
    "time",
)
OPTIONAL_COLS: Final[tuple[str, ...]] = (
    "fuel_flow",  # kg/s, treated as whole aircraft
    "aircraft_mass",  # kg
    # Dimensionless fraction; pycontrails uses it as overall propulsion efficiency.
    "engine_efficiency",
    "true_airspeed",  # m/s
)
ATTRS_OPTIONAL: Final[tuple[str, ...]] = (
    "takeoff_weight",  # kg
    "payload_factor",  # dimensionless fraction: payload / maximum payload
    "hydrogen_content",  # wt.% (percent by mass, e.g. 13.79)
    "h_c_ratio",  # read as atomic (molar) H/C; used only if hydrogen_content absent
    "q_fuel",  # J/kg of fuel (lower calorific value)
    "aircraft_series",
    "engine_uid",
    "aromatic_content",  # % by volume basis, scale undefined; unused in calculations
    "sulphur_content",  # % by mass basis, scale undefined; unused in calculations
    # Spelled "naphtalene" here; neats_io emits and NEATSFuel.from_attrs reads
    # "naphthalene" (see docs/internal/pyneats_units_audit.md).
    "naphtalene",
)

ATTS_REQUIRED: Final[tuple[str, ...]] = (
    "flight_id",
    "aircraft_type",
    "departure_airport",
    "arrival_airport",
    "model_type",
    "aobt",  # string copied verbatim from the input; never parsed
)


class Flight4D(FlightView):
    """
    Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist.

    Attributes
    ----------
    REQUIRED : ClassVar[tuple[str, ...]]
        Required columns for a 4D flight.
    OPTIONAL : ClassVar[tuple[str, ...]]
        Optional columns for a 4D flight.
    ATTRS_OPTIONAL : ClassVar[tuple[str, ...]]
        Optional attributes for a 4D flight.
    ATTRS_REQUIRED : ClassVar[tuple[str, ...]]
        Required attributes for a 4D flight.
    """

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_4D_COLS
    OPTIONAL: ClassVar[tuple[str, ...]] = OPTIONAL_COLS
    ATTRS_OPTIONAL: ClassVar[tuple[str, ...]] = ATTRS_OPTIONAL
    ATTRS_REQUIRED: ClassVar[tuple[str, ...]] = ATTS_REQUIRED
