from __future__ import annotations

from typing import Any
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact


__all__ = ["FlightWithClimateImpact"]

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
