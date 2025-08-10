# gwp.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Protocol

import pandas as pd
from pycontrails import Flight

from pyneats.core.meta import extract_flight_meta   # single source of truth for metadata
from pyneats.steps.climate.contrails import FlightWithContrailsImpact # validated view guaranteeing 'ef'

__all__ = [
    "DEFAULT_HORIZONS",
    "DEFAULT_EFFICACY",
    "DEFAULT_SURFACE_EARTH",
    "DEFAULT_SECONDS_PER_YEAR",
    "AGWP_AR6_WM2YR_PER_KG",
    "ClimateImpactStepError",
    "FlightWithClimateImpact",
    "GWPParams",
    "ClimateImpactModel",
    "SimpleGWPModel",
    "ClimateImpactModelType",
]

logger = logging.getLogger(__name__)

# ---- configuration defaults ----
DEFAULT_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
DEFAULT_EFFICACY: Final[float] = 0.42
DEFAULT_SURFACE_EARTH: Final[float] = 5.101e14       # m²
DEFAULT_SECONDS_PER_YEAR: Final[int] = 31_556_952    # s

# AR6 Table 7.SM.7 (W·m⁻²·yr·kg⁻¹) -> convert to J·m⁻²·kg⁻¹ by multiplying by seconds/year
AGWP_AR6_WM2YR_PER_KG: Mapping[int, float] = {
    20: 0.0243e-12,
    50: 0.0529e-12,  # often ~0.05e-12
    100: 0.0895e-12,
}

# ---- error type ----
class ClimateImpactStepError(RuntimeError):
    """Raised when the climate impact step fails to evaluate or validate outputs."""


class FlightWithClimateImpact(Flight):
    """
    Zero-copy view guaranteeing that attrs['climate_impact'] exists.

    Provides convenient accessors for the climate impact metadata and results.
    """

    @classmethod
    def from_flight(cls, flight: Flight) -> "FlightWithClimateImpact":
        if "climate_impact" not in getattr(flight, "attrs", {}):
            raise KeyError("Flight missing attrs['climate_impact'] – run the GWP step first.")
        # zero-copy rewrap
        return cls(data=flight.data, attrs=flight.attrs)

    @property
    def climate_payload(self) -> dict[str, Any]:
        return self.attrs["climate_impact"]

    @property
    def climate_meta(self) -> dict[str, Any]:
        return self.climate_payload.get("meta", {})

    @property
    def results(self) -> list[dict[str, Any]]:
        return self.climate_payload.get("results", [])

    def result_for(self, species: str) -> list[dict[str, Any]]:
        """Return the list of horizon dicts for a given species, e.g., 'CO2' or 'Contrails'."""
        for block in self.results:
            if block.get("species") == species:
                return block.get("value", [])
        return []


# ---- params ----
@dataclass(frozen=True)
class GWPParams:
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    efficacy: float = DEFAULT_EFFICACY
    surface_earth: float = DEFAULT_SURFACE_EARTH
    seconds_per_year: int = DEFAULT_SECONDS_PER_YEAR
    agwp_wm2yr_per_kg: Mapping[int, float] = field(
        default_factory=lambda: dict(AGWP_AR6_WM2YR_PER_KG)
    )


# ---- protocol ----
class ClimateImpactModel(Protocol):
    def __call__(self, flight: Flight) -> Flight: ...


# ---- concrete model ----
class SimpleGWPModel(ClimateImpactModel):
    """
    Compute GWP-like summaries:
      - Sums contrail EF (J) from 'ef' column
      - Converts EF to CO₂eq using efficacy and AGWP
      - Adds CO₂ baseline using attrs['total_co2'] (kg)
    Attaches results to `flight.attrs["climate_impact"]` and returns a typed view.
    """

    def __init__(self, params: GWPParams | None = None) -> None:
        self.params = params or GWPParams()

    def __call__(self, flight: Flight) -> FlightWithClimateImpact:
        # Validate presence of EF (zero-copy)
        try:
            _ = FlightWithContrailsImpact.from_flight(flight)
        except KeyError as e:
            logger.error("Climate impact input missing required contrail columns: %s", e)
            raise ClimateImpactStepError(f"Missing required contrail columns: {e}") from e

        # Aggregate EF
        try:
            df: pd.DataFrame = flight.to_dataframe()
            total_ef = float(pd.to_numeric(df["ef"], errors="coerce").sum())  # J
        except Exception as e:
            logger.exception("Failed to aggregate contrail EF")
            raise ClimateImpactStepError(f"Failed to aggregate contrail EF: {e}") from e

        # Read CO₂ baseline
        try:
            total_co2 = float(flight.attrs["total_co2"])  # kg
        except Exception:
            logger.error("Flight attrs missing 'total_co2' required for GWP baseline")
            raise ClimateImpactStepError("Missing required attr 'total_co2'")

        # Precompute AGWP in J·m⁻²·kg⁻¹
        agwp_j_per_m2_per_kg = {
            h: self.params.agwp_wm2yr_per_kg[h] * self.params.seconds_per_year
            for h in self.params.horizons
        }

        # STEP 1: GWP forcing for contrails (scaled by efficacy)
        gwp_contrails = {h: total_ef * self.params.efficacy for h in self.params.horizons}

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
        payload = {
            "meta": {
                **extract_flight_meta(flight),
                "efficacy": self.params.efficacy,
                "surface_earth_m2": self.params.surface_earth,
                "seconds_per_year": self.params.seconds_per_year,
                "agwp_wm2yr_per_kg": dict(self.params.agwp_wm2yr_per_kg),
                "horizons": list(self.params.horizons),
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
                        {"horizon": h, "GWP": gwp_contrails[h], "CO2eq": co2eq_contrails[h]}
                        for h in self.params.horizons
                    ],
                },
            ],
        }

        # Attach to attrs and return a zero-copy typed view
        flight.attrs["climate_impact"] = payload
        logger.info("Climate impact (GWP) step completed successfully")
        return FlightWithClimateImpact.from_flight(flight)


# ---- factory ----
class ClimateImpactModelType(Enum):
    GWP = SimpleGWPModel

    def get(self, *args: Any, **kwargs: Any) -> ClimateImpactModel:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
