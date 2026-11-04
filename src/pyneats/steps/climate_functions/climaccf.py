"""
ClimAccf Non-CO2 Climate Function Module

Builds a wrapper around pycontrails.models.accf.ACCF (ClimAccf) to allow for the computation of ACCF climate functions on a flight.

Key Components
--------------
- ACCFParams: Parameters for the ACCF model, including meteorological and surface datasets.
- make_accf_surface_view: Function to adapt a surface MetDataset to be compatible with ClimAccf.
- ACCFModel: A class that implements the ACCF model as a step in a processing pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import ClassVar

import pandas as pd
import xarray as xr
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.core.met_var import TOAOutgoingLongwaveFlux
from pycontrails.datalib.ecmwf import SurfaceSolarDownwardRadiation
from pycontrails.datalib.ecmwf import TopNetThermalRadiation
from pycontrails.models.accf import ACCF  # pycontrails’ wrapper for ClimAccf

from pyneats.core.neats_default_parameters import DEFAULT_CLIMACCF_KWARGS
from pyneats.core.physics import PMO_CH4_RF_RATIO
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import ACCFStepError
from pyneats.steps.climate_functions.protocol import NonCO2Model
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
from pyneats.steps.climate_functions.views import FlightWithSegmentATR
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

    accf_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: DEFAULT_CLIMACCF_KWARGS
    )


# ---- surface adapter for ACCF -------------------------------------
# ECMWF met variables of pycontrails ``ACCF`` (read once, at import).
_ACCF_MET_VARIABLES = ACCF.ecmwf_met_variables()


def make_accf_met_view(met: MetDataset) -> MetDataset:
    """Return the met for pycontrails ``ACCF`` without changing the given one.

    Renames the variables to the ECMWF names ``ACCF`` uses. When
    ``relative_humidity`` is in "%", a new variable divided by 100 (units "1")
    replaces it in a shallow copy. ``ACCF.__init__`` would otherwise run
    ``met.data["relative_humidity"] /= 100.0`` on its renamed met, which
    shares the numpy buffer with the given met: the given values would be
    divided by 100 again for every new ``ACCF`` while their units stay "%".
    The other variables share the given arrays (no copy).
    """
    accf_met = met.standardize_variables(_ACCF_MET_VARIABLES)
    rh = accf_met.data["relative_humidity"]
    if rh.attrs.get("units") != "%":
        return accf_met
    ds = accf_met.data.copy(deep=False)
    ds["relative_humidity"] = (rh / 100.0).assign_attrs({**rh.attrs, "units": "1"})
    return MetDataset(ds, copy=False)


def make_accf_surface_view(surface: MetDataset) -> MetDataset:
    """
    Return an ACCF-compatible surface MetDataset WITHOUT mutating the given one.

    Performs:
      - variable aliasing / renaming for ClimAccf expectations
      - minimal attrs/unit tweaks

    Notes
    -----
    Only names and ``units`` attributes change; no values are converted
    (see docs/internal/pyneats_units_audit.md):

    - ``toa_outgoing_longwave_flux`` (pycontrails OLR, positive upward,
      W m-2) is renamed to ECMWF ``top_net_thermal_radiation`` without a
      sign change, although ECMWF defines ``ttr`` as minus OLR.
    - ``surface_solar_downward_radiation`` is relabelled ``W m**-2``.
      ``DWDFactory.build_cache`` (default ``sdr_accumulate_dt_s=3600``)
      stores this field as W m-2 x 3600 labelled ``J m**-2``; after the
      relabel, pycontrails ``ACCF`` multiplies by 3600 again. The DWD
      source field (``sdr``) is TOA incoming solar according to the DWD
      store history, not surface radiation.
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
            {
                TOAOutgoingLongwaveFlux.standard_name: TopNetThermalRadiation.standard_name
            }
        )
    # 2) Align units on the surface shortwave flux if needed
    if SurfaceSolarDownwardRadiation.standard_name in ds:
        # Ensure units are consistent with the radiation flux variables expected by ClimAccf (e.g., W m-2)
        # Relabels the units attribute only; values are not converted
        # (see docs/internal/pyneats_units_audit.md).
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

    - Builds an ACCF with provided met and an *adapted* surface view, a new
      one for every flight (see ``_new_impl``).
    - Calls `.eval(flight)` to add climate columns (e.g., accf_total).
    - Validates required columns and returns a base Flight.

    ``FleetRunner`` passes its ``met`` and ``rad`` datasets as ``met`` and
    ``surface`` when ``requires_met_surface`` is True, unless the caller gives
    them in ``params["non_co2_model"]``.
    """

    default_params = ACCFParams

    # FleetRunner gives this step its met / rad datasets (as met / surface).
    requires_met_surface: ClassVar[bool] = True

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
            # PMO is never merged into aCCF_CH4 by the library (it would carry
            # the CH4 efficacy and factors, audit O14). ``run`` writes it as a
            # separate ATR_20_PMO column when accf_kwargs["PMO"] is True.
            self._accf_surface = accf_surface
            self._accf_met = make_accf_met_view(self.params.met)
            # Built here only to fail early on bad met / surface / kwargs;
            # ``run`` builds a new ACCF for every flight.
            self._new_impl()
        except Exception as e:
            self.logger.exception("Failed to initialize ACCF model")
            raise ACCFStepError(f"ACCF initialization failed: {e}") from e

    def _new_impl(self) -> ACCF:
        """Return a new pycontrails ``ACCF`` on the full met and surface.

        ``ACCF.eval`` replaces the model's ``met`` and ``surface`` with copies
        cut to the evaluated flight. An ``ACCF`` reused for a second flight
        then has only the weather of the first flight, and CLIMaCCF fails
        (IndexError) or gives wrong values. ``FleetRunner`` keeps one step per
        process for all its flights, so ``run`` must not reuse one ``ACCF``.
        A new ``ACCF`` per flight is also safe with ``prefer="threads"``.

        ``ACCF`` does not copy ``met`` (it renames the variables into a new
        ``MetDataset`` that shares the arrays) and makes a shallow copy of
        ``surface``, so a new ``ACCF`` per flight does not copy the weather.
        It gets ``self._accf_met``, whose relative humidity is already in
        "1", so ``ACCF.__init__`` never divides a shared array by 100.
        """
        return ACCF(
            met=self._accf_met,
            surface=self._accf_surface,
            **{**self.params.accf_kwargs, "PMO": False},
        )

    def run(self, flight: FlightWithEmissions) -> FlightWithNonCO2Impact:
        """Compute non-CO2 ATR contributions via the CLIMaCCF library (aCCF v1.0A).

        Delegates to the ``climaccf`` package to obtain per-segment aCCF outputs
        (K per kg NOx or K per kg fuel depending on ``accf_kwargs``), then
        converts them to ``ATR_20_{CH4,O3,H2O}`` columns on the flight.
        ``climaccf`` is not a declared PyNEATS dependency; this backend is not
        the default.

        With ``accf_kwargs["unit_K_per_kg_fuel"] = False`` (default), the
        CH4/O3 aCCFs are multiplied here by the flight's ``nox_ei``
        [kg NOx (as NO2) / kg fuel]. With ``True``, the flight's ``nox_ei`` is
        not used: with ``merged`` True (pycontrails default) CLIMaCCF applies
        its own NOx emission index, selected by the pycontrails ``ACCF``
        ``nox_ei`` parameter (default ``"TTV"``, a fixed 0.013 kg/kg)
        (see docs/internal/pyneats_units_audit.md). NaN ``fuel_burn`` and
        ``nox_ei`` are treated as 0.

        Args:
            flight: Flight with emissions data. Must expose ``fuel_burn``
                [kg fuel per segment] and ``nox_ei`` [kg/kg fuel] columns.

        Returns:
            ``FlightWithNonCO2Impact`` — flight with ``ATR_20_CH4``,
            ``ATR_20_O3``, ``ATR_20_H2O`` columns (K per segment) consumed by
            ``GWPMetrics`` downstream. The library is always called with
            ``PMO=False``, so ``ATR_20_CH4`` excludes PMO. With
            ``accf_kwargs["PMO"]`` True (default) it also writes
            ``ATR_20_PMO`` = ``PMO_CH4_RF_RATIO`` (0.29) x ``ATR_20_CH4``.

        Raises:
            ACCFStepError: If the CLIMaCCF output is missing required columns.
        """
        try:
            out: Flight = self._new_impl().eval(flight)
            df: pd.DataFrame = out.to_dataframe()
            fuel_burn = pd.to_numeric(df["fuel_burn"], errors="coerce").fillna(0.0)
            nox_ei = pd.to_numeric(df["nox_ei"], errors="coerce").fillna(0.0)

            if not self.params.accf_kwargs["unit_K_per_kg_fuel"]:
                # Convert O3/CH4 aCCFs from K per kg NOx (as NO2) to K per kg fuel
                df["aCCF_CH4"] = df["aCCF_CH4"] * nox_ei
                df["aCCF_O3"] = df["aCCF_O3"] * nox_ei

            # ATR_20 [K per segment] = fuel_burn [kg] x aCCF [K per kg fuel]

            flight["ATR_20_CH4"] = fuel_burn * df["aCCF_CH4"]  # K per segment
            flight["ATR_20_O3"] = fuel_burn * df["aCCF_O3"]  # K per segment
            flight["ATR_20_H2O"] = fuel_burn * df["aCCF_H2O"]  # K per segment
            if self.params.accf_kwargs.get("PMO", False):
                # PMO apart from CH4 (O14): own efficacy and factors in gwp.py
                flight["ATR_20_PMO"] = PMO_CH4_RF_RATIO * flight["ATR_20_CH4"]

        except KeyError as e:
            self.logger.error("ACCFbackend: %s", e)
            raise ACCFStepError(f"ACCF output missing required columns: {e}") from e

        self.logger.info("ACCF step completed successfully")
        return FlightWithSegmentATR.from_flight(flight)
