""" NEATS Flight Runner Module

This module implements the main execution pipeline for NEATS (Non-CO2 Effects of Aviation 
Transport Simulator). It orchestrates the sequential processing of flight data through 
multiple analysis stages:

Pipeline Stages:
   - Flight parsing (NM/ADS-B data)
   - Trajectory interpolation
   - Weather data intersection
   - Aircraft performance computation
   - Emissions calculation
   - Contrail formation simulation
   - Other Non-CO2 effects assessment
   - Climate impact metrics computation
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from functools import lru_cache
from importlib import import_module
from importlib.metadata import version as pkg_version, PackageNotFoundError
from typing import Any, Mapping, Dict

from pycontrails.core.flight import Flight

import pyneats
from pyneats.core.neats_default_parameters import (
    DEFAULT_BADA4_VERSION,
    DEFAULT_BADA3_VERSION,
    DEFAULT_ACCF_VERSION,
)

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
      3) (optional) git short SHA fallback as 'git-<sha>'
      4) 'unknown'

    Notes:
      - For pyBADA, only (1) is reliable; it does NOT expose __version__.
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
    """
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
    def extract(cls, flight: Flight,
                include_fleet_metadata: bool = False) -> dict[str, Any]:
        """
        Extract *only* flight-level fields from Flight.attrs (ignoring missing keys).

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
    climaccf_version: str | None = None
    bada4_version: str | None = None
    bada3_version: str | None = None
    pybada_version: str | None = None

    @classmethod
    @lru_cache(maxsize=1)
    def collect(cls) -> Dict[str, str]:
        """
        Collect environment versions once (cached).

        Returns
        -------
        dict[str, str]
        """
        return {
            # Your own package
            "pyneats_version": getattr(pyneats, "__version__", "unknown"),

            # Works for normal installs; editable installs may fall back to git SHA if enabled
            "pycontrails_version": dist_version(
                "pycontrails", module_name="pycontrails", allow_git_fallback=True
            ),

            # ACCF version comes from your config/constants
            "climaccf_version": DEFAULT_ACCF_VERSION,

            # BADA parameter versions (your declared defaults for the run)
            "bada4_version": DEFAULT_BADA4_VERSION,
            "bada3_version": DEFAULT_BADA3_VERSION,

            # pyBADA exposes no __version__; importlib.metadata is the reliable path
            "pybada_version": dist_version(
                "pyBADA", module_name="pyBADA",
                allow_module_dunder_version=False,
                allow_git_fallback=True,
            ),
        }


