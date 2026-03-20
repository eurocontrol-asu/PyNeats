"""
Flight and Fleet Report Module

Provides reporting utilities for flight and fleet-level metadata and version resolution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import fields
from functools import lru_cache
from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import Any

from pycontrails.core.flight import Flight

import pyneats
from pyneats.core.neats_default_parameters import DEFAULT_BADA3_VERSION
from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION


__all__ = [
    "FlightReport",
    "FleetReport",
    "dist_version",
]


# -----------------------------------------------------------------------------
# Version resolution (cached)
# -----------------------------------------------------------------------------


@lru_cache(maxsize=128)
def dist_version(
    dist_name: str,
    *,
    module_name: str | None = None,
    allow_module_dunder_version: bool = True,
) -> str:
    """
    Resolve a distribution's version string with caching.

    Order:
      1) importlib.metadata.version(dist_name)
      2) (optional) module.__version__

    Notes
    -----
    For pyBADA, only (1) is reliable; it does NOT expose __version__.

    Parameters
    ----------
    dist_name : str
        Name of the distribution.
    module_name : str, optional
        Name of the module to check for __version__.
    allow_module_dunder_version : bool, optional
        Whether to allow checking module.__version__ (default True).

    Returns
    -------
    str
        Version string or "unknown" if not found.
    """
    # 1) Canonical
    try:
        return pkg_version(dist_name)
    except PackageNotFoundError:
        pass
    except Exception:
        pass

    # 2) Optional __version__ attr on the module
    if allow_module_dunder_version and module_name:
        try:
            mod = import_module(module_name)
            v = getattr(mod, "__version__", None)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass

    return "unknown"


# -----------------------------------------------------------------------------
# Flight-scoped report
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlightReport:
    """
    Subset of PyContrails Flight.attrs relevant for *per-flight* reporting.

    This class defines the keys you care about; extraction returns a dict.

    Attributes
    ----------
    flight_id : str or None
        Flight identifier.
    registration : str or None
        Aircraft registration.
    departure_airport : str or None
        Departure airport code.
    arrival_airport : str or None
        Arrival airport code.
    aircraft_id : str or None
        Aircraft identifier.
    aobt : Any
        Actual off-block time (datetime or str).
    model_type : str or None
        Model type.
    aircraft_type : str or None
        Aircraft type.
    engine_uid : str or None
        Engine unique identifier.
    aircraft_series : str or None
        Aircraft series.
    bada_version : str or None
        BADA version.
    bada_code : str or None
        BADA code.
    """

    flight_id: str | None = None
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

    @classmethod
    def extract(
        cls, flight: Flight, include_fleet_metadata: bool = False
    ) -> dict[str, Any]:
        """
        Extract only flight-level fields from Flight.attrs (ignoring missing keys).

        Parameters
        ----------
        flight : Flight
            PyContrails Flight instance.
        include_none : bool
            If False, drop keys whose value is None.

        Returns
        -------
        dict[str, Any]
        """
        attrs: Mapping[str, Any] = flight.attrs or {}
        allowed = {f.name for f in fields(cls)}

        out: dict[str, Any] = {}
        for k in allowed:
            if k in attrs:
                v = attrs[k]
                if v is not None:
                    out[k] = v

        if include_fleet_metadata:
            out = {**out, **FleetReport.collect()}

        return out


# -----------------------------------------------------------------------------
# Fleet/run-scoped report (environment/tool versions)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FleetReport:
    """
    Environment/tool versions that are constant for a whole fleet run.
    Returned as a dict via collect().
    """

    pyneats_version: str | None = None
    pycontrails_version: str | None = None
    openairclim_version: str | None = None
    bada4_version: str | None = None
    bada3_version: str | None = None
    pybada_version: str | None = None

    @classmethod
    @lru_cache(maxsize=1)
    def collect(cls) -> dict[str, str]:
        """
        Collect environment versions once (cached).

        Returns
        -------
        dict[str, str]
        """
        return {
            "pyneats_version": pyneats.__version__,
            "pycontrails_version": dist_version(
                "pycontrails",
                module_name="pycontrails",
            ),
            "openairclim_version": dist_version(
                "openairclim",
                module_name="openairclim",
            ),
            "bada4_version": DEFAULT_BADA4_VERSION,
            "bada3_version": DEFAULT_BADA3_VERSION,
            # pyBADA exposes no __version__; importlib.metadata is the reliable path
            "pybada_version": dist_version("pyBADA", module_name="pyBADA"),
        }
