from __future__ import annotations

from typing import Final
from pyneats.core.views import FlightView

__all__ = [
    "DEFAULT_REQUIRED_EMISSION_COLS",
    "FlightWithEmissions",
]

# Columns that this step promises to attach
DEFAULT_REQUIRED_EMISSION_COLS: Final[tuple[str, ...]] = ("nvpm_ei_m",)

class FlightWithEmissions(FlightView):
    """Zero-copy typed view for emissions-enriched flights."""
    REQUIRED = DEFAULT_REQUIRED_EMISSION_COLS