# climate.py

"""
accf.py

This script builds a wrapper around `pycontrails.models.accf.ACCF` (ClimAccf) to allow for the 
computation of ACCF climate functions on a flight, adding the results as new columns to the flight data.

Key components:
- `NonCO2Params`: Parameters for the ACCF model, including meteorological and surface datasets.
- `make_accf_surface_view`: Function to adapt a surface MetDataset to be compatible with ClimAccf.
- `ACCFModel`: A class that implements the ACCF model as a step in a processing pipeline.   
"""

from __future__ import annotations


from dataclasses import dataclass, field
from typing import Any, Mapping

import xarray as xr

from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.accf import ACCF  # pycontrails’ wrapper for ClimAccf
from pycontrails.datalib.ecmwf import (
    TopNetThermalRadiation,
    SurfaceSolarDownwardRadiation,
)
from pycontrails.core.met_var import TOAOutgoingLongwaveFlux

from pyneats.core.neats_defaults import DEFAULT_ACCF_KWARGS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.climate.views import FlightWithNonCO2Impact
from pyneats.steps.climate.protocol import NonCO2Model, ClimateStepError
from pyneats.steps.climate.params import ClimateParams


__all__ = [
    "NonCO2Params",
    "ACCFModel",
    "make_accf_surface_view",
]


# ---- params --------------------------------------------------------
@dataclass(frozen=True)
class NonCO2Params(ClimateParams):
    met: MetDataset | None = None
    surface: MetDataset | None = None

    accf_kwargs: Mapping[str, Any] = field(default_factory=lambda: DEFAULT_ACCF_KWARGS)


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
    # TOAOutgoingLongwaveFlux = "toa_outgoing_longwave_flux"      # source name present in `surface`
    # TopNetThermalRadiation = "toa_net_thermal_radiation"        # target name expected by ClimAccf
    # SurfaceSolarDownwardRadiation = "surface_downwelling_shortwave_flux"  # example

    # 1) Update attrs for the OLR var, then rename it to "top net thermal"
    if TOAOutgoingLongwaveFlux.standard_name in ds:
        ds = ds.copy(deep=False)  # shallow copy of Dataset header; arrays stay shared
        ds[TOAOutgoingLongwaveFlux.standard_name].attrs.update(
            {
                "long_name": TopNetThermalRadiation.long_name,
                "standard_name": TopNetThermalRadiation.standard_name,
            }
        )
        print("TOAOutgoingLongwaveFlux in")
        ds = ds.rename(
            {
                TOAOutgoingLongwaveFlux.standard_name: TopNetThermalRadiation.standard_name
            }
        )
        print("TOAOutgoingLongwaveFlux in rename")
    else:
        print("TOAOutgoingLongwaveFlux out")
    # 2) Align units on the surface shortwave flux if needed
    if SurfaceSolarDownwardRadiation.standard_name in ds:

        print("SurfaceSolarDownwardRadiation in")
        # Ensure units are consistent with the radiation flux variables expected by ClimAccf (e.g., W m-2)
        ds[SurfaceSolarDownwardRadiation.standard_name].attrs.update(
            {"units": TOAOutgoingLongwaveFlux.units}
        )
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


@register(NonCO2Model, "accf")
class ACCFModel(
    BaseStep[
        FlightWithEmissions,
        FlightWithNonCO2Impact,
        NonCO2Params,
    ]
):
    """
    Thin wrapper around `pycontrails.models.accf.ACCF` (ClimAccf).

    - Builds an ACCF with provided met and an *adapted* surface view.
    - Calls `.eval(flight)` to add climate columns (e.g., accf_total).
    - Validates required columns and returns a base Flight.
    """

    default_params = NonCO2Params

    def _post_init(self) -> None:
        if self.params.met is None or self.params.surface is None:
            raise ClimateStepError("ACCF requires both 'met' and 'surface' datasets.")

        # Build a non-mutating view of surface for ACCF (Cocip can still use the base surface as-is)
        try:
            print("make_accf_surface_view in")
            accf_surface = make_accf_surface_view(self.params.surface)
            print("make_accf_surface_view out")
        except Exception as e:
            print("make_accf_surface_view except")
            self.logger.exception("Failed to adapt surface dataset for ACCF")
            raise ClimateStepError(f"Surface adaptation failed: {e}") from e

        # Defaults you used in your snippet
        try:
            self._impl = ACCF(
                met=self.params.met,
                surface=accf_surface,
                **self.params.accf_kwargs,
            )
        except Exception as e:
            self.logger.exception("Failed to initialize ACCF model")
            raise ClimateStepError(f"ACCF initialization failed: {e}") from e

    def run(self, flight: FlightWithEmissions) -> FlightWithNonCO2Impact:
        try:
            out: Flight = self._impl.eval(flight)
        except KeyError as e:
            self.logger.error("ACCFbackend: %s", e)
            raise ClimateStepError(f"ACCF output missing required columns: {e}") from e

        self.logger.info("ACCF step completed successfully")
        return FlightWithNonCO2Impact.from_flight(out)
