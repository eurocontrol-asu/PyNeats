from __future__ import annotations
from typing import Any, ClassVar, Final
from pyneats.steps.emissions.views import FlightWithEmissions

__all__ = [
    "REQUIRED_CONTRAIL_COLS",
    "REQUIRED_CLIMATE_COLS",
    "FlightWithContrailsImpact",
    "FlightWithNonCO2Impact",
    "FlightWithClimateImpact",
]

REQUIRED_CLIMATE_COLS: Final[tuple[str, ...]] = (
    "ATR_20_CH4",
    "ATR_20_O3",
    "ATR_20_H2O",
)
REQUIRED_CONTRAIL_COLS: Final[tuple[str, ...]] = ("ef",)


class FlightWithContrailsImpact(FlightWithEmissions):
    """Zero-copy typed view for emissions-enriched flights."""

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_CONTRAIL_COLS


class FlightWithNonCO2Impact(FlightWithEmissions):
    """Zero-copy typed view for emissions-enriched flights."""

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_CLIMATE_COLS


class FlightWithClimateImpact(FlightWithNonCO2Impact):
    """
    Zero-copy view guaranteeing that attrs['climate_impact'] exists.

    Provides convenient accessors for the climate impact metadata and results.
    """

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
