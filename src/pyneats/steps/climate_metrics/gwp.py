"""
Global Warming Potential (GWP) Metrics Module

Implements GWP and ATR climate metrics for aviation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Final

import pandas as pd

from pyneats.core.neats_default_parameters import DEFAULT_CLIMACCF_KWARGS
from pyneats.core.neats_default_parameters import MAX_NONCO2_CO2_RATIO
from pyneats.core.physics import CO2_AGWP_COEFF_WM2YR_PER_KG
from pyneats.core.physics import CONVERSION_FACTORS_AGWP_TO_RF
from pyneats.core.physics import CONVERSION_FACTORS_ATR_TO_RF
from pyneats.core.physics import EFFICACY
from pyneats.core.physics import METRICS_HORIZONS
from pyneats.core.physics import RF_BACKWARD_FACTOR
from pyneats.core.physics import SECONDS_PER_YEAR
from pyneats.core.physics import SURFACE_EARTH
from pyneats.core.steps import BaseParams
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.views import (
    FlightWithGlobalAGWP,  # Concrete View B (New/Integrated)
)

# --- Updated Imports for Views ---
from pyneats.steps.climate_functions.views import (
    FlightWithNonCO2Impact,  # The Union (for type hinting)
)
from pyneats.steps.climate_functions.views import (
    FlightWithRFContrailsImpact,  # Needed for column validation in View A
)
from pyneats.steps.climate_functions.views import (
    FlightWithSegmentATR,  # Concrete View A (Legacy/Detailed)
)
from pyneats.steps.climate_metrics.protocol import ClimateImpactModel
from pyneats.steps.climate_metrics.protocol import ClimateImpactStepError
from pyneats.steps.climate_metrics.report import FlightReport
from pyneats.steps.climate_metrics.views import FlightWithClimateImpact


__all__ = [
    "GWPParams",
    "GWPMetrics",
]

# Supported species for aCCFs pathway
SPECIES: Final[tuple[str, ...]] = ("CH4", "O3", "H2O")

# Column name pattern expected for ATR at H0 = 20 years
ATR_COL_TEMPLATE: Final[str] = "ATR_20_{spec}"


# ---------------------------
# Parameters (Unchanged)
# ---------------------------


@dataclass(frozen=True)
class GWPParams(BaseParams):
    """
    Parameters for GWP climate metrics computation.
    """

    horizons: tuple[int, ...] = METRICS_HORIZONS
    surface_earth: float = SURFACE_EARTH
    seconds_per_year: int = SECONDS_PER_YEAR
    agwp_coeff_wm2yr_per_kg: Mapping[int, float] = field(
        default_factory=lambda: CO2_AGWP_COEFF_WM2YR_PER_KG
    )
    k_agwp_from_rf: Mapping[int, Mapping[str, float]] = field(
        default_factory=lambda: CONVERSION_FACTORS_AGWP_TO_RF
    )
    k_atr_from_rf: Mapping[int, Mapping[str, float]] = field(
        default_factory=lambda: CONVERSION_FACTORS_ATR_TO_RF
    )
    efficacy: Mapping[str, float] = field(default_factory=lambda: EFFICACY)
    atr_ref_horizon: int = field(
        default_factory=lambda: DEFAULT_CLIMACCF_KWARGS.get("time_horizon", 20)
    )
    rf_backward_factor: Mapping[str, float] = field(
        default_factory=lambda: RF_BACKWARD_FACTOR
    )


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
    Computes GWP and ATR climate metrics for aviation.

    This class implements the Global Warming Potential (GWP) and Absolute Temperature Response (ATR)
    metrics for aviation climate impact assessment.
    """

    default_params = GWPParams

    # ---------- Helpers (Math) ----------

    def _agwp_co2_Wm2yr(self, m_co2: float) -> dict[int, float]:
        """
        Compute AGWP_CO2(H) = C(H) * m_CO2.

        Parameters
        ----------
        m_co2 : float
            Mass of CO2 emitted (kg).

        Returns
        -------
        dict[int, float]
            AGWP for each time horizon in W·m⁻²·yr.
        """
        return {
            h: self.params.agwp_coeff_wm2yr_per_kg[h] * m_co2
            for h in self.params.horizons
        }

    def _eagwp_contrails_Wm2yr(self, total_ef_J: float) -> dict[int, float]:
        """
        Compute EAGWP_Con(H) = EF * ε_Con / (S_Earth * s_yr).

        Parameters
        ----------
        total_ef_J : float
            Total energy forcing from contrails (J).

        Returns
        -------
        dict[int, float]
            EAGWP for each time horizon in W·m⁻²·yr.
        """
        eps = float(self.params.efficacy.get("Contrails", 1.0))
        s = self.params.surface_earth
        s_yr = self.params.seconds_per_year
        return dict.fromkeys(self.params.horizons, total_ef_J * eps / (s * s_yr))

    def _co2eq_from_eagwp_Wm2yr(self, agwp_Wm2yr: dict[int, float]) -> dict[int, float]:
        """CO2eq(H) = EAGWP(H) / C(H)"""
        return {
            h: agwp_Wm2yr[h] / self.params.agwp_coeff_wm2yr_per_kg[h]
            for h in self.params.horizons
        }

    def _eagwp_spec_Wm2yr(self, species: str, atr_H0_K: float) -> dict[int, float]:
        """Scales ATR(H0) [K] to AGWP(H) [W·m⁻²·yr]"""
        eps_spec = float(self.params.efficacy.get(species, 1.0))
        h_0 = self.params.atr_ref_horizon
        rf_backward = float(self.params.rf_backward_factor.get(species, 1.0))

        k_atr_h_0 = float(self.params.k_atr_from_rf.get(h_0, {}).get(species, 1.0))
        if k_atr_h_0 == 0.0:
            raise ClimateImpactStepError(f"k_ATR←E[{species}][H0={h_0}] is zero.")

        out: dict[int, float] = {}
        for h in self.params.horizons:
            k_agwp = float(self.params.k_agwp_from_rf.get(h, {}).get(species, 1.0))
            # the conversion factors do include efficacy for ATR calculation
            # therefore need to multiply the ATR values from the aCCFs with the efficacy to be consistent with the conversion factors
            # this translates with the efficacy being square in the formula:
            scale = (k_agwp / k_atr_h_0) / rf_backward * eps_spec**2
            out[h] = scale * atr_H0_K

        return out

    # ---------- Logic Implementation Helpers ----------

    def _compute_from_segment_atr(
        self, flight: FlightWithSegmentATR
    ) -> list[dict[str, Any]]:
        """
        Computations for Method C
        1. Sums 'ef' column for Contrails.
        2. Sums 'ATR_20_X' columns for Non-CO2.
        3. Applies conversion factors.
        """
        df = flight.to_dataframe()
        results = []
        horizons = self.params.horizons

        # --- A. Contrails (From 'ef' column) ---
        # We can trust 'ef' exists because FlightWithSegmentATR inherits from FlightWithRFContrailsImpact
        try:
            total_ef_J = float(pd.to_numeric(df["ef"], errors="coerce").sum())
            eagwp_con = self._eagwp_contrails_Wm2yr(total_ef_J)
            co2eq_con = self._co2eq_from_eagwp_Wm2yr(eagwp_con)

            results.append(
                {
                    "species": "Contrails",
                    "value": [
                        {
                            "horizon": h,
                            "EAGWP_Wm2yr": eagwp_con[h],
                            "CO2eq_kg": co2eq_con[h],
                        }
                        for h in horizons
                    ],
                }
            )
        except Exception as e:
            self.logger.exception("Failed to compute Contrail metrics from segments")
            raise ClimateImpactStepError(f"Contrail segment calc failed: {e}") from e

        # --- B. Non-CO2 (From 'ATR' columns) ---
        for sp in SPECIES:
            atr_col = ATR_COL_TEMPLATE.format(spec=sp)
            if atr_col not in df.columns:
                continue

            try:
                atr_h0_total_K = float(
                    pd.to_numeric(df[atr_col], errors="coerce").fillna(0.0).sum()
                )
                eagwp_spec = self._eagwp_spec_Wm2yr(sp, atr_h0_total_K)
                co2eq_spec = self._co2eq_from_eagwp_Wm2yr(eagwp_spec)

                results.append(
                    {
                        "species": sp,
                        "value": [
                            {
                                "horizon": h,
                                "EAGWP_Wm2yr": eagwp_spec[h],
                                "CO2eq_kg": co2eq_spec[h],
                            }
                            for h in horizons
                        ],
                    }
                )
            except Exception:
                self.logger.exception("Failed to compute %s metrics from segments", sp)

        return results

    def _compute_from_global_agwp(
        self, flight: FlightWithGlobalAGWP
    ) -> list[dict[str, Any]]:
        """
        Computations for Method D
        1. Reads 'AGWP_{h}_{spec}' directly from attributes.
        2. Applies Efficacy.
        3. Divides by CO2 contribution (CO2eq).
        """
        results = []
        horizons = self.params.horizons

        # --- A. Non-CO2 Species (CH4, O3, H2O) ---
        for sp in SPECIES:
            val_list = []
            for h in horizons:
                # Key format: AGWP_20_CH4
                attr_key = f"AGWP_{h}_{sp}"

                # Default to 0.0 if specific horizon missing (or handle error)
                raw_agwp = flight.attrs.get(attr_key, 0.0)

                # Apply Efficacy
                eps = float(self.params.efficacy.get(sp, 1.0))
                eagwp = raw_agwp * eps

                # Convert to CO2eq
                denom = self.params.agwp_coeff_wm2yr_per_kg[h]
                co2eq = eagwp / denom

                val_list.append({"horizon": h, "EAGWP_Wm2yr": eagwp, "CO2eq_kg": co2eq})
            results.append({"species": sp, "value": val_list})

        # --- B. Contrails (From Attributes) ---
        # Key format: AGWP_20_CONT
        cont_val_list = []
        has_contrails = False

        for h in horizons:
            attr_key = f"AGWP_{h}_CONT"
            # Only process if at least one horizon exists
            if attr_key in flight.attrs:
                has_contrails = True

                raw_agwp = flight.attrs.get(attr_key, 0.0)
                eps = float(self.params.efficacy.get("Contrails", 1.0))
                eagwp = raw_agwp * eps

                denom = self.params.agwp_coeff_wm2yr_per_kg[h]
                co2eq = eagwp / denom

                cont_val_list.append(
                    {"horizon": h, "EAGWP_Wm2yr": eagwp, "CO2eq_kg": co2eq}
                )

        if has_contrails:
            results.append({"species": "Contrails", "value": cont_val_list})

        return results

    # ---------- Main Run Method ----------

    def run(self, flight: FlightWithNonCO2Impact) -> FlightWithClimateImpact:
        # 1. Common Metadata & CO2 Baseline
        try:
            total_co2_kg = float(flight.attrs["total_co2"])
        except Exception:
            self.logger.error("Flight attrs missing 'total_co2'")
            raise ClimateImpactStepError("Missing required attr 'total_co2'") from None

        # --- RESTORED LOGIC: Total Fuel Burn ---
        total_fuel_burn = 0.0

        # Strategy A: Sum the column (Standard for Trajectory modes)
        if "fuel_burn" in flight:
            # use numpy nansum for speed and safety
            import numpy as np

            total_fuel_burn = float(np.nansum(flight["fuel_burn"]))

        # Strategy B: Check attributes (Fallback for Aggregate/Fleet modes)
        elif "fuel_burn" in flight.attrs:
            total_fuel_burn = float(flight.attrs["fuel_burn"])

        # Strategy C: Check 'fuel_burn_kg' (Alternative attribute name)
        elif "fuel_burn_kg" in flight.attrs:
            total_fuel_burn = float(flight.attrs["fuel_burn_kg"])

        else:
            self.logger.warning(
                "Could not find fuel_burn in columns or attributes. Setting to 0.0"
            )

        # ---------------------------------------

        # CO2 Calculations (Common)
        horizons = self.params.horizons
        agwp_co2 = self._agwp_co2_Wm2yr(total_co2_kg)
        co2eq_co2 = dict.fromkeys(horizons, total_co2_kg)

        base_results = [
            {
                "species": "CO2",
                "value": [
                    {
                        "horizon": h,
                        "EAGWP_Wm2yr": agwp_co2[h],
                        "CO2eq_kg": co2eq_co2[h],
                    }
                    for h in horizons
                ],
            }
        ]

        # 2. Polymorphic Dispatch
        other_results = []

        if isinstance(flight, FlightWithSegmentATR):
            # Ensure 'ef' column exists via strict casting
            # This protects against passing a generic FlightWithEmissions
            try:
                _ = FlightWithRFContrailsImpact.from_flight(flight)
                df = flight.to_dataframe()
                total_ef_J = float(pd.to_numeric(df["ef"], errors="coerce").sum())

            except Exception as e:
                raise ClimateImpactStepError(
                    "SegmentATR view missing required Contrail columns"
                ) from e

            other_results = self._compute_from_segment_atr(flight)
            self.logger.info(
                "Computed metrics using Segment-Level ATR summation (Legacy)"
            )

        elif isinstance(flight, FlightWithGlobalAGWP):
            other_results = self._compute_from_global_agwp(flight)
            self.logger.info(
                "Computed metrics using Flight-Level AGWP attributes (Integrated)"
            )
            total_ef_J = float(flight.attrs.get("AGWP_20_CONT", 0.0))
        else:
            raise TypeError(f"Unknown input view type: {type(flight)}")

        # Extract report info and Add the metric back
        flight_information = {
            **FlightReport.extract(flight),
            "co2_baseline_kg": total_co2_kg,
            "fuel_burn_kg": total_fuel_burn,
            "contrails_ef_J": total_ef_J,
        }

        # 2.5) Guardrail: reject implausible non-CO2 impact
        if total_co2_kg > 0.0:
            for entry in other_results:
                species = entry["species"]
                for val in entry["value"]:
                    co2eq = abs(val["CO2eq_kg"])
                    if co2eq > MAX_NONCO2_CO2_RATIO * total_co2_kg:
                        raise ClimateImpactStepError(
                            f"Non-CO2 species '{species}' at H={val['horizon']}yr has "
                            f"CO2eq={co2eq:.1f} kg, exceeding {MAX_NONCO2_CO2_RATIO}x "
                            f"CO2 baseline ({total_co2_kg:.1f} kg)"
                        )

        # 3. Assemble and Return
        climate_impact = {
            "flight_information": flight_information,
            "climate_metrics": base_results + other_results,
        }

        flight.attrs["climate_impact"] = climate_impact
        return FlightWithClimateImpact.from_flight(flight)
