from __future__ import annotations
from typing import Any, Mapping, TypedDict
from pycontrails import Flight

class FlightMeta(TypedDict, total=False):
    aircraft_id: str | None
    departure_airport: str | None
    arrival_airport: str | None
    aircraft_type: str | None
    bada_version: str | None
    callsign: str | None
    aobt: Any  # keep as Any if it can be datetime/string
    pycontrails_version: str | None

_META_KEYS = {
    "aircraft_id": "flight_id",
    "departure_airport": "departure_airport",
    "arrival_airport": "arrival_airport",
    "aircraft_type": "aircraft_type",
    "bada_version": "bada_version",
    "callsign": "callsign",
    "aobt": "aobt",
    "pycontrails_version": "pycontrails_version",
}

def extract_flight_meta(flight: Flight) -> FlightMeta:
    """Zero-copy extraction of common metadata from a Flight's attrs."""
    attrs: Mapping[str, Any] = getattr(flight, "attrs", {}) or {}
    out: FlightMeta = {}
    for k_out, k_in in _META_KEYS.items():
        out[k_out] = attrs.get(k_in)  # type: ignore[index]
    return out