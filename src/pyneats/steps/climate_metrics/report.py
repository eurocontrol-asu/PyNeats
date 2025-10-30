from __future__ import annotations
from dataclasses import dataclass, fields
from typing import Any, Mapping
from pycontrails.core.flight import Flight

import pyneats
from pyneats.core.neats_default_parameters import (
    DEFAULT_BADA4_VERSION,
    DEFAULT_BADA3_VERSION,
    DEFAULT_ACCF_VERSION,
)

__all__ = [
    "FlightReport",
]

@dataclass(frozen=True, slots=True)
class FlightReport:
    """Subset of PyContrails Flight.attrs relevant for reporting."""

    registration: str | None = None
    departure_airport: str | None = None
    arrival_airport: str | None = None
    aircraft_id: str | None = None
    aobt: Any = None  # datetime | str
    model_type: str | None = None
    aircraft_type: str | None = None
    engine_uid: str | None = None
    aircraft_series: str | None = None
    bada_version: str | None = None
    bada_code: str | None = None
    pycontrails_version: str | None = None

    @classmethod
    def extract(cls, flight: Flight, *, include_none: bool = True) -> dict[str, Any]:
        """Extract reportable metadata from a PyContrails Flight as a dict."""
        attrs: Mapping[str, Any] = flight.attrs or {}
        allowed_keys = {f.name for f in fields(cls)}

        out: dict[str, Any] = {}
        for k in allowed_keys:
            if k in attrs:
                v = attrs[k]
                if include_none or v is not None:
                    out[k] = v

        out["pyneats_version"] = pyneats.__version__
        out["pybada_version"] = "0.0.0"  # TODO: populate from pybada if available
        out["climaccf_version"] = DEFAULT_ACCF_VERSION
        out["bada4_version"] = DEFAULT_BADA4_VERSION
        out["bada3_version"] = DEFAULT_BADA3_VERSION

        return out

