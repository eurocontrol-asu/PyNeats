"""Global Warming Potential (GWP) Metrics Module

This module implements the computation of climate metrics for aviation emissions
using the Global Warming Potential (GWP) approach. It calculates:

1. Climate Metrics:
   - Absolute Global Warming Potential (AGWP) in J·m⁻²
   - CO₂-equivalent emissions in kg for multiple time horizons
   
2. Species Covered:
   - CO₂ baseline using Joos (2013) impulse response function
   - Contrails using energy forcing and efficacy factors
   - Non-CO₂ effects (CH4, O3, H2O) using ATR scaling and conversion factors 

The calculations follow the methodologies outlined in Joos (2013), and Dahlmann et al. (2025),
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Mapping, Dict, List, Any
import pandas as pd

from pyneats.core.steps import BaseStep, BaseParams
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.views import FlightWithContrailsImpact
from pyneats.steps.climate_functions.climaccf import FlightWithNonCO2Impact
from pyneats.steps.climate_metrics.protocol import (
    ClimateImpactModel,
    ClimateImpactStepError,
)
from pyneats.steps.climate_metrics.report import FlightReport
from pyneats.steps.climate_metrics.views import FlightWithClimateImpact
from pyneats.core.constants import (
    METRICS_HORIZONS,
    SURFACE_EARTH,
    SECONDS_PER_YEAR,
    JOOS_AGWP_COEFF_WM2YR_PER_KG,
    CONVERSION_FACTORS_AGWP_TO_RF,
    CONVERSION_FACTORS_ATR_TO_RF,
    EFFICACY
)

from pyneats.core.neats_default_parameters import DEFAULT_CLIMACCF_KWARGS

__all__ = [
    "GWPParams",
    "GWPMetrics",
]

# Supported species for aCCFs pathway
SPECIES: Final[tuple[str, ...]] = ("CH4", "O3", "H2O")

# Column name pattern expected for ATR at H0 = 20 years
ATR_COL_TEMPLATE: Final[str] = "ATR_20_{spec}"  # J·m⁻² (per CLIMaCCF output at H0=20)


# ---------------------------
# Parameters
# ---------------------------

@dataclass(frozen=True)
class GWPParams(BaseParams):
    """Parameters for GWP climate metrics computation."""
    horizons: tuple[int, ...] = METRICS_HORIZONS
    surface_earth: float = SURFACE_EARTH
    seconds_per_year: int = SECONDS_PER_YEAR

    # Joos (2013) C(H)
    agwp_coeff_wm2yr_per_kg: Mapping[int, float] = field(
        default_factory=lambda: JOOS_AGWP_COEFF_WM2YR_PER_KG
    )

    # Non-contrail species parameters
    # K_{AGWP←RF}^{Spec}(H)
    k_agwp_from_rf: Mapping[int, Mapping[str, float]] = field(
        default_factory=lambda: CONVERSION_FACTORS_AGWP_TO_RF
    )
    # K_{ATR←RF}^{Spec}(H)
    k_atr_from_rf: Mapping[int, Mapping[str, float]] = field(
        default_factory=lambda: CONVERSION_FACTORS_ATR_TO_RF
    )

    # Efficacies
    efficacy: Mapping[str, float] = field(
        default_factory=lambda: EFFICACY
    )
    # Reference horizon H0 for ATR (fixed at 20 per spec)
    atr_ref_horizon: int = DEFAULT_CLIMACCF_KWARGS.get("time_horizon", 20)


# ---------------------------
# Model
# ---------------------------

@register(ClimateImpactModel, "gwp")
class GWPMetrics(
    BaseStep[
        FlightWithNonCO2Impact,
        FlightWithClimateImpact,
        GWPParams,
    ]
):
    """
    Compute AGWP (J·m⁻²) and CO₂-equivalent (kg) for:
      - CO₂ baseline
      - Contrails (using EF from CoCiP, efficacy, and Earth's surface area)
      - Other species via aCCFs + conversion factors

    """

    default_params = GWPParams

    # ---------- Helpers ----------

    def _agwp_co2_J_per_m2(self, m_co2: float) -> dict[int, float]:
        """ AGWP_CO2(H) = C(H) * m_CO2 * s_yr    (units: J·m⁻²)"""
        
        s_yr = self.params.seconds_per_year
        return {h: self.params.agwp_coeff_wm2yr_per_kg[h] * m_co2 * s_yr for h in self.params.horizons}

    def _agwp_contrails_J_per_m2(self, total_ef_J: float) -> dict[int, float]:
        """ AGWP_Con(H) = EF * ε_Con / S_Earth    (units: J·m⁻²) """

        eps = float(self.params.efficacy.get("Contrails", 1.0))
        s = self.params.surface_earth
        return {h: (total_ef_J * eps) / s for h in self.params.horizons}

    def _co2eq_from_agwp_J_per_m2(self, agwp_J_per_m2: dict[int, float]) -> dict[int, float]:
        """ CO2eq(H) = AGWP(H) / ( C(H) * s_yr )  (units: kg) """

        s_yr = self.params.seconds_per_year
        return {
            h: agwp_J_per_m2[h] / (self.params.agwp_coeff_wm2yr_per_kg[h] * s_yr)
            for h in self.params.horizons
        }

    def _agwp_spec_J_per_m2(
        self,
        species: str,
        atr_H0_K: float,  # <-- absolute ATR at H0, in Kelvin
    ) -> dict[int, float]:
        """
        AGWP_Spec(H) =
        * ( C_ATR←Pulse^{Spec}(H) / C_ATR←Pulse^{Spec}(H0) )
        * ε_Spec
        * ATR^{Spec}(H0)

        Expected input: ATR^{Spec}(H0) in **K** 
        Output: AGWP_Spec(H) in **J·m⁻²**.
        """
        eps_spec = float(self.params.efficacy.get(species, 1.0))
        h_0 = self.params.atr_ref_horizon
        s_yr = self.params.seconds_per_year

        # Guard against zero division in C_ATR(H0)
        k_atr_h_0 = float(self.params.k_atr_from_rf.get(h_0, {}).get(species, 1.0))
        if k_atr_h_0 == 0.0:
            raise ClimateImpactStepError(f"k_ATR←E[{species}][H0={h_0}] is zero; cannot scale.")

        out: dict[int, float] = {}
        for h in self.params.horizons:

            k_agwp = float(self.params.k_agwp_from_rf.get(h, {}).get(species, 1.0))
            scale = (k_agwp / k_atr_h_0) * eps_spec * s_yr #  J·m⁻²·K⁻¹ 
            out[h] = scale * atr_H0_K  # J·m⁻²

        return out
    

    # ---------- Main ----------

    def run(self, flight: FlightWithNonCO2Impact) -> FlightWithClimateImpact:
        # Ensure contrail EF is present
        try:
            _ = FlightWithContrailsImpact.from_flight(flight)
        except KeyError as e:
            self.logger.error("Input missing required contrail columns: %s", e)
            raise ClimateImpactStepError(f"Missing required contrail columns: {e}") from e

        df: pd.DataFrame = flight.to_dataframe()

        # Aggregate contrail EF (J)
        try:
            total_ef_J = float(pd.to_numeric(df["ef"], errors="coerce").sum())
        except Exception as e:
            self.logger.exception("Failed to sum contrail EF")
            raise ClimateImpactStepError(f"Failed to aggregate contrail EF: {e}") from e
        
         # Aggregate fuel burn (kg)
        try:
            total_fuel_burn = float(pd.to_numeric(df["fuel_burn"], errors="coerce").sum())
        except Exception as e:
            self.logger.exception("Failed to sum fuel_burn")
            raise ClimateImpactStepError(f"Failed to aggregate fuel_burn: {e}") from e

        # CO₂ baseline mass (kg)
        try:
            total_co2_kg = float(flight.attrs["total_co2"])
        except Exception:
            self.logger.error("Flight attrs missing 'total_co2'")
            raise ClimateImpactStepError("Missing required attr 'total_co2'")

        # Timings and ancillary metadata 
        meta = {
            **FlightReport.extract(flight),
            "contrails_ef_J": total_ef_J,
            "co2_baseline_kg": total_co2_kg,
            "fuel_burn_kg": total_fuel_burn,
        }
        for k in ("non_co2_computation_time", "contrails_computation_time"):
            if k in flight.attrs:
                meta[k] = float(flight.attrs[k])

        horizons = self.params.horizons

        # ---- CO₂: AGWP (J·m⁻²) and CO₂eq = m_CO2 (kg) ----
        agwp_co2 = self._agwp_co2_J_per_m2(total_co2_kg)  # J·m⁻²
        co2eq_co2 = {h: total_co2_kg for h in horizons}    # kg

        # ---- Contrails: AGWP (J·m⁻²) and CO₂eq via Joos ----
        agwp_con = self._agwp_contrails_J_per_m2(total_ef_J)            # J·m⁻²
        co2eq_con = self._co2eq_from_agwp_J_per_m2(agwp_con)            # kg

        results: List[Mapping[str,Any]] = [
            {
                "species": "CO2",
                "value": [
                    {"horizon": h, "AGWP_J_per_m2": agwp_co2[h], "CO2eq_kg": co2eq_co2[h]}
                    for h in horizons
                ],
            },
            {
                "species": "Contrails",
                "value": [
                    {"horizon": h, "AGWP_J_per_m2": agwp_con[h], "CO2eq_kg": co2eq_con[h]}
                    for h in horizons
                ],
            },
        ]

        # ---- Other species via ATR(H0=20) scaling ----
        skipped_species: Dict[str, str] = {}
        added_species: List[str] = []

        for sp in SPECIES:
            atr_col = ATR_COL_TEMPLATE.format(spec=sp)
            if atr_col not in df.columns:
                skipped_species[sp] = f"missing '{atr_col}' column"
                continue

            try:
                # Sum ATR^{Spec}(H0) over trajectory (units should be K)
                atr_h0_series = pd.to_numeric(df[atr_col], errors="coerce").fillna(0.0)
                atr_h0_total_K = float((atr_h0_series).sum())

                # Compute AGWP_Spec(H)
                agwp_spec = self._agwp_spec_J_per_m2(sp, atr_h0_total_K)

                # Convert to CO₂eq via Joos: CO2eq(H) = AGWP(H) / (C(H) * s_yr)
                co2eq_spec = self._co2eq_from_agwp_J_per_m2(agwp_spec)

                results.append(
                    {
                        "species": sp,
                        "value": [
                            {
                                "horizon": h,
                                "AGWP_J_per_m2": agwp_spec[h],
                                "CO2eq_kg": co2eq_spec[h],
                            }
                            for h in horizons
                        ],
                    }
                )
                added_species.append(sp)

            except ClimateImpactStepError as e:
                skipped_species[sp] = str(e)
            except Exception as e:
                self.logger.exception("Failed non-CO2 AGWP/CO2eq for %s", sp)
                skipped_species[sp] = f"exception: {e}"

        # Assemble payload
        climate_impact = {
            "flight_information": {**meta},
            "climate_metrics": results,
        }

        flight.attrs["climate_impact"] = climate_impact
        self.logger.info("Climate impact (GWP) computed with Joos(2013) and Dahlmann(2025) conversion factors")
        return FlightWithClimateImpact.from_flight(flight)
