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
from pyneats.steps.climate_functions.views import FlightWithGlobalAGWP
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
from pyneats.steps.climate_functions.views import FlightWithRFContrailsImpact
from pyneats.steps.climate_functions.views import FlightWithSegmentATR
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

# Primary-mode ozone: computed separately, with its own efficacy and conversion
# factors, then added into the "CH4" output entry (the output keeps 5 species).
PMO: Final[str] = "PMO"

# Column name pattern expected for ATR at H0 = 20 years [K per segment]
ATR_COL_TEMPLATE: Final[str] = "ATR_20_{spec}"


# ---------------------------
# Parameters (Unchanged)
# ---------------------------


@dataclass(frozen=True)
class GWPParams(BaseParams):
    """
    Parameters for GWP climate metrics computation.
    """

    horizons: tuple[int, ...] = METRICS_HORIZONS  # [years]
    surface_earth: float = SURFACE_EARTH  # [m^2]
    seconds_per_year: int = SECONDS_PER_YEAR  # [s/yr]
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
    # H0 of the input ATR columns [years]
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

    # ---------- Helpers (Lookup) ----------

    @staticmethod
    def _factor(table: str, mapping: Mapping[str, float], species: str) -> float:
        """Return ``mapping[species]``; raise if the species has no entry.

        A missing species used to fall back to 1.0, which silently mis-scales it
        (for PMO without an RF backward factor, about 2x too large).
        """
        try:
            return float(mapping[species])
        except KeyError:
            raise ClimateImpactStepError(
                f"No {table} value for species '{species}'"
            ) from None

    def _conversion_factor(
        self,
        table: str,
        mapping: Mapping[int, Mapping[str, float]],
        horizon: int,
        species: str,
    ) -> float:
        """Return ``mapping[horizon][species]``; raise if either key is missing."""
        if horizon not in mapping:
            raise ClimateImpactStepError(f"No {table} values for horizon H={horizon}")
        return self._factor(f"{table}[H={horizon}]", mapping[horizon], species)

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
            EAGWP for each time horizon in W·m⁻²·yr (the same value for every
            horizon).
        """
        eps = self._factor("efficacy", self.params.efficacy, "Contrails")
        s = self.params.surface_earth
        s_yr = self.params.seconds_per_year
        return dict.fromkeys(self.params.horizons, total_ef_J * eps / (s * s_yr))

    def _co2eq_from_eagwp_Wm2yr(self, agwp_Wm2yr: dict[int, float]) -> dict[int, float]:
        """CO2eq(H) [kg CO2-eq] = EAGWP(H) [W m-2 yr] / C(H) [W m-2 yr kg-1]"""
        return {
            h: agwp_Wm2yr[h] / self.params.agwp_coeff_wm2yr_per_kg[h]
            for h in self.params.horizons
        }

    def _eagwp_spec_Wm2yr(self, species: str, atr_H0_K: float) -> dict[int, float]:
        """Scales ATR(H0) [K] to EAGWP(H) [W·m⁻²·yr].

        EAGWP(H) = ATR(H0) * k_AGWP(H) / k_ATR(H0) / rf_backward * efficacy**2.

        Every factor is looked up for ``species`` itself (PMO has its own);
        a missing entry raises ``ClimateImpactStepError``.
        """
        eps_spec = self._factor("efficacy", self.params.efficacy, species)
        h_0 = self.params.atr_ref_horizon
        rf_backward = self._factor(
            "RF backward factor", self.params.rf_backward_factor, species
        )

        k_atr_h_0 = self._conversion_factor(
            "k_ATR conversion factor", self.params.k_atr_from_rf, h_0, species
        )
        if k_atr_h_0 == 0.0:
            raise ClimateImpactStepError(f"k_ATR←E[{species}][H0={h_0}] is zero.")

        out: dict[int, float] = {}
        for h in self.params.horizons:
            k_agwp = self._conversion_factor(
                "k_AGWP conversion factor", self.params.k_agwp_from_rf, h, species
            )
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
        1. Sums 'ef' column for Contrails [J].
        2. Sums 'ATR_20_X' columns for Non-CO2 [K].
        3. Applies conversion factors.
        4. If 'ATR_20_PMO' is present, converts it with the PMO factors and
           adds it into the CH4 entry.

        Each entry's values hold ``EAGWP_Wm2yr`` [W m-2 yr] and ``CO2eq_kg``
        [kg CO2-equivalent].
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

                pmo_col = ATR_COL_TEMPLATE.format(spec=PMO)
                if sp == "CH4" and pmo_col in df.columns:
                    # PMO part with its own efficacy and factors, added into CH4
                    atr_pmo_K = float(
                        pd.to_numeric(df[pmo_col], errors="coerce").fillna(0.0).sum()
                    )
                    eagwp_pmo = self._eagwp_spec_Wm2yr(PMO, atr_pmo_K)
                    eagwp_spec = {h: eagwp_spec[h] + eagwp_pmo[h] for h in horizons}

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
            except ClimateImpactStepError:
                # Missing or zero factor: a configuration error, not a data issue
                raise
            except Exception:
                self.logger.exception("Failed to compute %s metrics from segments", sp)

        return results

    def _compute_from_global_agwp(
        self, flight: FlightWithGlobalAGWP
    ) -> list[dict[str, Any]]:
        """
        Computations for Method D
        1. Reads 'AGWP_{h}_{spec}' directly from attributes [W m-2 yr].
        2. Applies Efficacy.
        3. Adds 'AGWP_{h}_PMO' x efficacy_PMO, when present, into CH4.
        4. Divides by CO2 contribution (CO2eq).

        Each entry's values hold ``EAGWP_Wm2yr`` [W m-2 yr] and ``CO2eq_kg``
        [kg CO2-equivalent].
        """
        results = []
        horizons = self.params.horizons

        # PMO is optional (absent in flights from before it was stored apart)
        has_pmo = any(f"AGWP_{h}_{PMO}" in flight.attrs for h in horizons)
        eps_pmo = (
            self._factor("efficacy", self.params.efficacy, PMO) if has_pmo else 0.0
        )

        # --- A. Non-CO2 Species (CH4 incl. PMO, O3, H2O) ---
        for sp in SPECIES:
            eps = self._factor("efficacy", self.params.efficacy, sp)
            val_list = []
            for h in horizons:
                # Key format: AGWP_20_CH4
                attr_key = f"AGWP_{h}_{sp}"

                # Default to 0.0 if specific horizon missing (or handle error)
                raw_agwp = flight.attrs.get(attr_key, 0.0)

                # Apply Efficacy
                eagwp = raw_agwp * eps
                if sp == "CH4" and has_pmo:
                    # PMO part with its own efficacy, added into CH4
                    eagwp += flight.attrs.get(f"AGWP_{h}_{PMO}", 0.0) * eps_pmo

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
                eps = self._factor("efficacy", self.params.efficacy, "Contrails")
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
        """Convert non-CO2 ATR contributions into GWP-based CO2-equivalents.

        Implements the EAGWP / CO2eq formulas from *Dahlmann et al. (2025)* —
        see `docs/explanation/mrv-specification.md` §3.7 for the full spec.
        Polymorphic on the input view:

        - ``FlightWithSegmentATR`` → Method C (sums per-segment ATR then
          applies Dahlmann conversion factors).
        - ``FlightWithGlobalAGWP`` → Method D (reads pre-integrated AGWP
          attributes from OpenAirClim).

        A guardrail rejects non-CO2 species whose CO2eq exceeds
        ``MAX_NONCO2_CO2_RATIO`` times the total CO2 (implausible ratio check).

        Args:
            flight: Non-CO2 impact view. Must carry ``attrs["total_co2"]`` and
                either per-segment ATR columns (Method C) or flight-level AGWP
                attrs (Method D).

        Returns:
            ``FlightWithClimateImpact`` — stores the final payload at
            ``flight.attrs["climate_impact"]`` with shape (units below)::

                {
                    "flight_information": {
                        "co2_baseline_kg": float,
                        "fuel_burn_kg": float,
                        "contrails_ef_J": float,
                        ...  # from FlightReport.extract
                    },
                    "climate_metrics": [
                        {"species": "CO2", "value": [{"horizon": 20, ...}, ...]},
                        {"species": "CH4", "value": [...]},
                        ...
                    ],
                }

            Units:

            - ``co2_baseline_kg``: flight total CO2 [kg] (``attrs["total_co2"]``,
              the pycontrails nansum of per-segment ``co2``).
            - ``fuel_burn_kg``: flight total fuel burned [kg] (nansum of the
              per-segment ``fuel_burn`` column, else the ``fuel_burn`` or
              ``fuel_burn_kg`` attr).
            - ``contrails_ef_J``: Method C, sum of the CoCiP per-segment energy
              forcing ``ef`` [J]. Method D stores ``attrs["AGWP_20_CONT"]``
              under this key, an AGWP in W m-2 yr without efficacy, not J
              (see docs/internal/pyneats_units_audit.md).
            - Each ``climate_metrics`` value: ``horizon`` [years],
              ``EAGWP_Wm2yr`` (efficacy-weighted time-integrated forcing,
              [W m-2 yr]) and ``CO2eq_kg`` (EAGWP / C(H), [kg CO2-equivalent]).
              For CO2, ``CO2eq_kg`` is the total CO2 [kg]. The ``CH4`` entry
              is CH4 including PMO: the PMO part (Method C ``ATR_20_PMO``,
              written when ``accf_kwargs["PMO"]`` is True (default); Method D
              ``AGWP_{H}_PMO``) is computed with its own efficacy and factors
              and added to the CH4 part before the guardrail.

        Raises:
            ClimateImpactStepError: If ``total_co2`` is missing, if the input
                view shape is inconsistent, if a species has no efficacy, RF
                backward or conversion factor, or if the non-CO2/CO2 guardrail
                trips.
            TypeError: If the input view type is neither segment-ATR nor
                global-AGWP.
        """
        # 1. Common Metadata & CO2 Baseline
        # total_co2: flight total CO2 mass [kg]
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
            self.logger.info("Computed metrics using Segment-Level ATR summation")

        elif isinstance(flight, FlightWithGlobalAGWP):
            other_results = self._compute_from_global_agwp(flight)
            self.logger.info(
                "Computed metrics using Flight-Level AGWP attributes (Integrated)"
            )
            # Stores AGWP_20_CONT, an AGWP in W m-2 yr (without efficacy), under
            # the J-named contrails_ef_J key below
            # (see docs/internal/pyneats_units_audit.md).
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
