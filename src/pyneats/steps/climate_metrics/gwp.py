# gwp.py

"""
gwp.py

This script is a wrapper around the GWP model to allow for the computation of GWP climate functions
on a flight based on emissions data, adding the results as new columns to the flight data.

The model uses contrail effective forcing (EF) data computed in previous steps, along with CO₂ emissions data,
to compute GWP and CO₂-equivalent values over specified time horizons.

"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Mapping
import numpy as np
import pandas as pd

from pyneats.core.neats_default_parameters import (
    DEFAULT_HORIZONS,
    DEFAULT_EFFICACY,
    DEFAULT_SURFACE_EARTH,
    DEFAULT_SECONDS_PER_YEAR,
    DEFAULT_AGWP_AR6_WM2YR_PER_KG,
)
from pyneats.core.meta import extract_flight_meta  # single source of truth for metadata
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.accf import FlightWithNonCO2Impact
from pyneats.steps.climate_metrics.protocol import ClimateImpactModel, ClimateImpactStepError
from pyneats.steps.climate_metrics.views import FlightWithClimateImpact
from pyneats.steps.climate_functions.views import FlightWithContrailsImpact
from pyneats.steps.climate_functions.params import ClimateParams

__all__ = [
    "GWPParams",
    "SimpleGWPModel",
]

# RDC: Should they go into params?

# Metric conversion factors from pulse emission to future emission scenario (Dietmüller et al., 2022)
ADJUST_COEFF: Final[dict[str, float]] = {
    "CH4": 1.0e-5,
    "O3": 1.0e-5,
    "H2O": 1.0e-5,
    "NOx": 1.0e-5,
}

# Horizon conversion factors (your P20_F20 / P20_F50 / P20_F100)
HORIZON_CONVERSION_FACTORS: Final[dict[int, dict[str, float]]] = {
    20: {"CH4": 10.8, "O3": 14.5, "H2O": 14.5},
    50: {"CH4": 42.5, "O3": 34.1, "H2O": 34.1},
    100: {"CH4": 98.2, "O3": 58.3, "H2O": 58.3},
}


# ---- params ----
@dataclass(frozen=True)
class GWPParams(ClimateParams):
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    efficacy: float = DEFAULT_EFFICACY
    surface_earth: float = DEFAULT_SURFACE_EARTH
    seconds_per_year: int = DEFAULT_SECONDS_PER_YEAR
    agwp_wm2yr_per_kg: Mapping[int, float] = field(
        default_factory=lambda: DEFAULT_AGWP_AR6_WM2YR_PER_KG
    )


# ---- concrete model ----
@register(ClimateImpactModel, "gwp")
class SimpleGWPModel(
    BaseStep[
        FlightWithNonCO2Impact,
        FlightWithClimateImpact,
        GWPParams,
    ]
):
    """
    Compute GWP-like summaries:
      - Sums contrail EF (J) from 'ef' column
      - Converts EF to CO₂eq using efficacy and AGWP
      - Adds CO₂ baseline using attrs['total_co2'] (kg)
    Attaches results to `flight.attrs["climate_impact"]` and returns a typed view.
    """

    default_params = GWPParams

    def run(self, flight: FlightWithNonCO2Impact) -> FlightWithClimateImpact:
        # Validate presence of EF (zero-copy)
        try:
            _ = FlightWithContrailsImpact.from_flight(flight)
        except KeyError as e:
            self.logger.error(
                "Climate impact input missing required contrail columns: %s", e
            )
            raise ClimateImpactStepError(
                f"Missing required contrail columns: {e}"
            ) from e

        # Aggregate EF
        try:
            df: pd.DataFrame = flight.to_dataframe()
            total_ef = float(pd.to_numeric(df["ef"], errors="coerce").sum())  # J
            total_fuel_flow = float(
                pd.to_numeric(df["fuel_flow"], errors="coerce").sum()
            )
            total_fuel_burn = float(
                pd.to_numeric(df["fuel_burn"], errors="coerce").sum()
            )
            non_co2_computation_time = float(flight.attrs["non_co2_computation_time"])
            contrails_computation_time = float(
                flight.attrs["contrails_computation_time"]
            )

        except Exception as e:
            self.logger.exception("Failed to aggregate contrail EF")
            raise ClimateImpactStepError(f"Failed to aggregate contrail EF: {e}") from e

        # Read CO₂ baseline
        try:
            total_co2 = float(flight.attrs["total_co2"])  # kg
        except Exception:
            self.logger.error(
                "Flight attrs missing 'total_co2' required for GWP baseline"
            )
            raise ClimateImpactStepError("Missing required attr 'total_co2'")

        # Precompute AGWP in J·m⁻²·kg⁻¹
        agwp_j_per_m2_per_kg = {
            h: self.params.agwp_wm2yr_per_kg[h] * self.params.seconds_per_year
            for h in self.params.horizons
        }

        # STEP 1: GWP forcing for contrails (scaled by efficacy)
        gwp_contrails = {
            h: total_ef * self.params.efficacy for h in self.params.horizons
        }

        # STEP 2: Convert contrail forcing into CO₂-equivalent (kg CO₂eq)
        co2eq_contrails = {
            h: gwp_contrails[h] / agwp_j_per_m2_per_kg[h] / self.params.surface_earth
            for h in self.params.horizons
        }

        # STEP 3: CO₂ GWP forcing (kg × AGWP × area)
        gwp_co2 = {
            h: total_co2 * agwp_j_per_m2_per_kg[h] * self.params.surface_earth
            for h in self.params.horizons
        }

        # Build payload with shared metadata (no duplication)
        climate_impact = {
            "meta": {
                **extract_flight_meta(flight),
                "contrails_ef": total_ef,
                "total_fuel_flow": total_fuel_flow,
                "total_fuel_burn": total_fuel_burn,
                "co2_baseline": total_co2,
                "contrails_computation_time": contrails_computation_time,
                "non_co2_computation_time": non_co2_computation_time,
            },
            "results": [
                {
                    "species": "CO2",
                    "value": [
                        {"horizon": h, "GWP": gwp_co2[h], "CO2eq": total_co2}
                        for h in self.params.horizons
                    ],
                },
                {
                    "species": "Contrails",
                    "value": [
                        {
                            "horizon": h,
                            "GWP": gwp_contrails[h],
                            "CO2eq": co2eq_contrails[h],
                        }
                        for h in self.params.horizons
                    ],
                },
            ],
        }

        # --------------------------------------------
        # ADD: Non-CO2 species from ACCF (CH4, O3, H2O)
        # --------------------------------------------
        # Helper to find a column among common spellings (case-insensitive)

        def _first_present_col(df: pd.DataFrame, names: list[str]) -> pd.Series | None:
            name_map = {c.lower(): c for c in df.columns}
            for n in names:
                c = name_map.get(n.lower())
                if c is not None:
                    return pd.to_numeric(df[c], errors="coerce")
            return None

        horizons = self.params.horizons
        agwp_j_per_m2_per_kg = {
            h: self.params.agwp_wm2yr_per_kg[h] * self.params.seconds_per_year
            for h in horizons
        }

        # Inputs we need
        fuel = _first_present_col(df, ["fuel_burn"])
        if fuel is None:
            self.logger.warning(
                "Skipping ACCF species (CH4,O3,H2O): missing 'fuel_burn' column."
            )
            fuel = None

        # Candidate ACCF column spellings per species
        accf_cols = {
            "CH4": ["aCCF_CH4", "accf_ch4", "ACCF_CH4", "accf_CH4"],
            "O3": ["aCCF_O3", "accf_o3", "ACCF_O3", "accf_O3"],
            "H2O": ["aCCF_H2O", "accf_h2o", "ACCF_H2O", "accf_H2O"],
            "NOx": ["aCCF_NOx", "accf_nox", "ACCF_NOx", "accf_NOx"],
        }

        added_species: list[str] = []
        skipped_species: dict[str, str] = {}

        if fuel is not None:
            for sp in ("CH4", "O3", "H2O", "NOx"):
                accf = _first_present_col(df, accf_cols[sp])
                if accf is None:
                    skipped_species[sp] = "missing ACCF column"
                    continue

                try:
                    # warming_sp ~ aCCF_sp * fuel_burn (vector); coerce NaNs to 0 for sum
                    warming_sp = (accf * fuel).fillna(0.0)
                    # total_ef_sp then scaled by your adjust_coeff
                    total_ef_sp = float(np.sum(warming_sp)) / ADJUST_COEFF[sp]

                    if sp == "NOx":
                        # NOx is a special case: cooling effect, so we skip adding it to results
                        climate_impact["meta"]["NOx_effect"] = float(
                            np.sum(accf.fillna(0.0))
                        )

                    # Per-horizon GWP (J m^-2), using your factors
                    gwp_sp = {
                        h: total_ef_sp * HORIZON_CONVERSION_FACTORS[h][sp]
                        for h in horizons
                    }

                    # Convert to CO2eq (kg) using the same AGWP/area recipe
                    co2eq_sp = {
                        h: gwp_sp[h]
                        / agwp_j_per_m2_per_kg[h]
                        / self.params.surface_earth
                        for h in horizons
                    }

                    climate_impact["results"].append(
                        {
                            "species": sp,
                            "value": [
                                {"horizon": h, "GWP": gwp_sp[h], "CO2eq": co2eq_sp[h]}
                                for h in horizons
                            ],
                        }
                    )
                    added_species.append(sp)

                except KeyError as e:
                    skipped_species[sp] = f"missing factor for horizon/species: {e}"
                except Exception as e:
                    self.logger.exception("Failed ACCF-based GWP for %s", sp)
                    skipped_species[sp] = f"exception: {e}"
        else:
            skipped_species = {sp: "missing fuel_burn" for sp in ("CH4", "O3", "H2O")}

        # Record metadata about this augmentation
        climate_impact["meta"].update(
            {
                "accf_adjust_coeff": dict(ADJUST_COEFF),
                "accf_horizon_conversion_factors": {
                    h: dict(HORIZON_CONVERSION_FACTORS[h]) for h in horizons
                },
                "nonco2_species_added": added_species,
                "nonco2_species_skipped": skipped_species,
            }
        )

        # Attach and return view (unchanged from before)
        flight.attrs["climate_impact"] = climate_impact
        self.logger.info("Climate impact (GWP) step completed successfully")
        return FlightWithClimateImpact.from_flight(flight)
