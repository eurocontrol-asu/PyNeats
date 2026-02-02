"""
This module builds a wrapper around `pycontrails.models.accf.ACCF` (ClimAccf) to allow for the
computation of ACCF climate functions on a flight

Key components:
- `NonCO2Params`: Parameters for the ACCF model, including meteorological and surface datasets.
- `make_accf_surface_view`: Function to adapt a surface MetDataset to be compatible with ClimAccf.
- `ACCFModel`: A class that implements the ACCF model as a step in a processing pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import xarray as xr
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.core.met_var import TOAOutgoingLongwaveFlux
from pycontrails.datalib.ecmwf import (
    SurfaceSolarDownwardRadiation,
    TopNetThermalRadiation,
)
from pycontrails.models.accf import ACCF  # pycontrails’ wrapper for ClimAccf

from pyneats.core.neats_default_parameters import DEFAULT_CLIMACCF_KWARGS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import ACCFStepError, NonCO2Model
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact, FlightWithSegmentATR
from pyneats.steps.emissions.views import FlightWithEmissions

__all__ = [
    "ACCFParams",
    "ACCFModel",
    "make_accf_surface_view",
]


# ---- params --------------------------------------------------------
@dataclass(frozen=True)
class ACCFParams(ClimateParams):
    """Parameters for the ACCF (ClimAccf) model."""

    met: MetDataset | None = None
    surface: MetDataset | None = None

    accf_kwargs: Mapping[str, Any] = field(default_factory=lambda: DEFAULT_CLIMACCF_KWARGS)


# ---- surface adapter for ACCF -------------------------------------
def make_accf_surface_view(surface: MetDataset) -> MetDataset:
    """
    Return an ACCF-compatible surface MetDataset WITHOUT mutating the given one.

    Performs:
      - variable aliasing / renaming for ClimAccf expectations
      - minimal attrs/unit tweaks

    """

    # Work on an xr.Dataset view
    ds: xr.Dataset = surface.data

    # 1) Update attrs for the OLR var, then rename it to "top net thermal"
    if TOAOutgoingLongwaveFlux.standard_name in ds:
        ds = ds.copy(deep=False)  # shallow copy to avoid mutating original
        ds[TOAOutgoingLongwaveFlux.standard_name].attrs.update(
            {
                "long_name": TopNetThermalRadiation.long_name,
                "standard_name": TopNetThermalRadiation.standard_name,
            }
        )
        ds = ds.rename(
            {TOAOutgoingLongwaveFlux.standard_name: TopNetThermalRadiation.standard_name}
        )
    # 2) Align units on the surface shortwave flux if needed
    if SurfaceSolarDownwardRadiation.standard_name in ds:
        # Ensure units are consistent with the radiation flux variables expected by ClimAccf (e.g., W m-2) # noqa: E501
        ds[SurfaceSolarDownwardRadiation.standard_name].attrs.update(
            {"units": TOAOutgoingLongwaveFlux.units}
        )

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
        FlightWithSegmentATR,
        ACCFParams,
    ]
):
    """
    Thin wrapper around `pycontrails.models.accf.ACCF` (ClimAccf).

    - Builds an ACCF with provided met and an *adapted* surface view.
    - Calls `.eval(flight)` to add climate columns (e.g., accf_total).
    - Validates required columns and returns a base Flight.
    """

    default_params = ACCFParams

    def _post_init(self) -> None:
        if self.params.met is None or self.params.surface is None:
            raise ACCFStepError("ACCF requires both 'met' and 'surface' datasets.")

        # Build a non-mutating view of surface for ACCF (Cocip can still use the base surface as-is)
        try:
            accf_surface = make_accf_surface_view(self.params.surface)
        except Exception as e:
            self.logger.exception("Failed to adapt surface dataset for ACCF")
            raise ACCFStepError(f"Surface adaptation failed: {e}") from e

        # Defaults you used in your snippet
        try:
            self._impl = ACCF(
                met=self.params.met,
                surface=accf_surface,
                **self.params.accf_kwargs,
            )
        except Exception as e:
            self.logger.exception("Failed to initialize ACCF model")
            raise ACCFStepError(f"ACCF initialization failed: {e}") from e

    def run(self, flight: FlightWithEmissions) -> FlightWithNonCO2Impact:
        try:
            out: Flight = self._impl.eval(flight)
            df: pd.DataFrame = out.to_dataframe()
            fuel_burn = pd.to_numeric(df["fuel_burn"], errors="coerce").fillna(0.0)
            nox_ei = pd.to_numeric(df["nox_ei"], errors="coerce").fillna(0.0)

            if not self.params.accf_kwargs["unit_K_per_kg_fuel"]:
                # Convert aCCF outputs from K per kg NOx to K per kg H2O and K per Fuel
                df["aCCF_CH4"] = df["aCCF_CH4"] * nox_ei
                df["aCCF_O3"] = df["aCCF_O3"] * nox_ei

            # Compute final ART_20 (K) from aCCF outputs (K per kg fuel)

            flight["ATR_20_CH4"] = fuel_burn * df["aCCF_CH4"]  # K
            flight["ATR_20_O3"] = fuel_burn * df["aCCF_O3"]  # K
            flight["ATR_20_H2O"] = fuel_burn * df["aCCF_H2O"]  # K

        except KeyError as e:
            self.logger.error("ACCFbackend: %s", e)
            raise ACCFStepError(f"ACCF output missing required columns: {e}") from e

        self.logger.info("ACCF step completed successfully")
        return FlightWithSegmentATR.from_flight(flight)
