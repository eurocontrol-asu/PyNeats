# climate.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Protocol, runtime_checkable

import xarray as xr

from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.accf import ACCF  # pycontrails’ wrapper for ClimAccf
from pycontrails.datalib.ecmwf import TopNetThermalRadiation, SurfaceSolarDownwardRadiation
from pycontrails.core.met_var  import TOAOutgoingLongwaveFlux

from pyneats.core.views import FlightView
from pyneats.core.steps import Step, BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.views import FlightWithEmissions

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_REQUIRED_CLIMATE_COLS",
    "FlightWithNonCO2Impact",
    "NonCO2Model",
    "NonCO2Params",
    "ACCFModel",
    "ClimateStepError",
    "make_accf_surface_view",
]

# ---- configuration -------------------------------------------------
# Keep minimal; adjust once you settle on schema (e.g., per-species columns)
DEFAULT_REQUIRED_CLIMATE_COLS: Final[tuple[str, ...]] = ("aCCF_NOx",)

# If you want per-component outputs later, you can change to:
# DEFAULT_REQUIRED_CLIMATE_COLS = ("accf_o3", "accf_ch4", "accf_h2o", "accf_pmo", "accf_total")

# ---- error type ----------------------------------------------------
class ClimateStepError(RuntimeError):
    """Raised when ACCF evaluation fails or yields invalid output."""

class FlightWithNonCO2Impact(FlightView):
    """Zero-copy typed view for emissions-enriched flights."""
    REQUIRED = DEFAULT_REQUIRED_CLIMATE_COLS


@runtime_checkable
class NonCO2Model(Step[FlightWithEmissions, FlightWithNonCO2Impact], Protocol):
    """A climate step that enriches a Flight with non-CO₂ impact columns."""
    def __call__(self, flight: FlightWithEmissions) -> FlightWithNonCO2Impact: ...

# ---- params --------------------------------------------------------
@dataclass(frozen=True)
class NonCO2Params:
    met: MetDataset | None = None
    # Use a *base* surface radiation dataset here (COCIP-safe). We'll adapt it for ACCF without mutating.
    surface: MetDataset | None = None
    accf_kwargs: Mapping[str, Any] = field(default_factory=dict)   # passed to ACCF(...)
    unit_K_per_kg_fuel: bool = True
    forecast_step: int = 12  # what you used in your snippet

    # No __post_init__ mutation: keep it simple & frozen

# ---- surface adapter for ACCF -------------------------------------
def make_accf_surface_view(surface: MetDataset) -> MetDataset:
    """
    Return an ACCF-compatible surface MetDataset WITHOUT mutating the given one.

    Performs:
      - variable aliasing / renaming for ClimAccf expectations
      - minimal attrs/unit tweaks

    This relies on xarray’s copy-on-write semantics for coords/data; large arrays are not duplicated.
    """

    # Work on an xr.Dataset view
    ds: xr.Dataset = surface.data

    # Expected names in your snippet
    #TOAOutgoingLongwaveFlux = "toa_outgoing_longwave_flux"      # source name present in `surface`
    #TopNetThermalRadiation = "toa_net_thermal_radiation"        # target name expected by ClimAccf
    #SurfaceSolarDownwardRadiation = "surface_downwelling_shortwave_flux"  # example



    # 1) Update attrs for the OLR var, then rename it to "top net thermal"
    if TOAOutgoingLongwaveFlux.standard_name in ds:
        ds = ds.copy(deep=False)  # shallow copy of Dataset header; arrays stay shared
        ds[TOAOutgoingLongwaveFlux.standard_name].attrs.update({
            "long_name": TopNetThermalRadiation.long_name,
            "standard_name": TopNetThermalRadiation.standard_name,
        })
        print("TOAOutgoingLongwaveFlux in")
        ds = ds.rename({TOAOutgoingLongwaveFlux.standard_name: TopNetThermalRadiation.standard_name})
        print("TOAOutgoingLongwaveFlux in rename")
    else:
        print("TOAOutgoingLongwaveFlux out")
    # 2) Align units on the surface shortwave flux if needed
    if SurfaceSolarDownwardRadiation.standard_name in ds:

        print("SurfaceSolarDownwardRadiation in")
        # Ensure units are consistent with the radiation flux variables expected by ClimAccf (e.g., W m-2)
        ds[SurfaceSolarDownwardRadiation.standard_name].attrs.update({
            "units": TOAOutgoingLongwaveFlux.units
        })
    else: 
        print("SurfaceSolarDownwardRadiation out")

    # Wrap back into a MetDataset; keep other attrs untouched
    attrs_dict: dict[str, Any] | None = (
        {str(k): v for k, v in surface.attrs.items()} if surface.attrs else None
    )

    accf_surface = MetDataset(
        data=ds,
        cachestore=surface.cachestore,
        copy=False,
        attrs=attrs_dict,
    )
    return accf_surface


@register("non_co2_model", "accf")
class ACCFModel(BaseStep[FlightWithEmissions, FlightWithNonCO2Impact]):
    """
    Thin wrapper around `pycontrails.models.accf.ACCF` (ClimAccf).

    - Builds an ACCF with provided met and an *adapted* surface view.
    - Calls `.eval(flight)` to add climate columns (e.g., accf_total).
    - Validates required columns and returns a base Flight.
    """

    def __init__(
        self,
        params: NonCO2Params,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_CLIMATE_COLS,
    ) -> None:
        if params.met is None or params.surface is None:
            raise ClimateStepError("ACCF requires both 'met' and 'surface' datasets.")

        self.logger = logging.getLogger(__name__)  # <-- and keep a logger on self
        
        # Build a non-mutating view of surface for ACCF (Cocip can still use the base surface as-is)
        try:
            print("make_accf_surface_view in")
            accf_surface = make_accf_surface_view(params.surface)
            print("make_accf_surface_view out")
        except Exception as e:
            print("make_accf_surface_view except")
            logger.exception("Failed to adapt surface dataset for ACCF")
            raise ClimateStepError(f"Surface adaptation failed: {e}") from e

        self.required_cols = required_cols

        # Defaults you used in your snippet
        accf_args = dict(params.accf_kwargs)
        accf_args.setdefault("unit_K_per_kg_fuel", params.unit_K_per_kg_fuel)
        accf_args.setdefault("forecast_step", params.forecast_step)

        try:
            self._impl = ACCF(
                met=params.met,
                surface=accf_surface,
                **accf_args,
            )
        except Exception as e:
            logger.exception("Failed to initialize ACCF model")
            raise ClimateStepError(f"ACCF initialization failed: {e}") from e
    

    def run(self, flight: FlightWithEmissions) -> FlightWithNonCO2Impact:
        try:
            out: Flight = self._impl.eval(flight)
        except KeyError as e:
            logger.error("ACCFbackend: %s", e)
            raise ClimateStepError(f"ACCF output missing required columns: {e}") from e

        self.logger.info("ACCF step completed successfully")
        return FlightWithNonCO2Impact.from_flight(out, require=self.required_cols)

