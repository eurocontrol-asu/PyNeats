"""
Climate Metrics Views Module

Defines zero-copy views for climate-metrics-enriched flights.
"""

from __future__ import annotations

from pyneats.steps.climate_functions.views import FlightWithEmissions


__all__ = ["FlightWithClimateImpact"]


class FlightWithClimateImpact(FlightWithEmissions):
    """
    Zero-copy view guaranteeing that attrs['climate_impact'] exists.

    Provides convenient accessors for the climate impact metadata and results.

    The payload is written by ``GWPMetrics.run``, which documents its shape
    and units (``EAGWP_Wm2yr`` in W m-2 yr, ``CO2eq_kg`` in kg
    CO2-equivalent, ``co2_baseline_kg`` and ``fuel_burn_kg`` in kg).
    """

    '''
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
    '''
