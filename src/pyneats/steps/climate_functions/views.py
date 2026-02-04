"""
Climate Functions Views Module

Defines zero-copy typed views for contrail and non-CO2 climate impact enrichment.
"""

from __future__ import annotations

from typing import ClassVar
from typing import Final

from pyneats.steps.emissions.views import FlightWithEmissions


__all__ = [
    "REQUIRED_CONTRAIL_COLS",
    "REQUIRED_ATR_COLS",
    "FlightWithRFContrailsImpact",
    "FlightWithNonCO2Impact",
    "FlightWithSegmentATR",
    "FlightWithGlobalAGWP",
]

REQUIRED_ATR_COLS: Final[tuple[str, ...]] = (
    "ATR_20_CH4",
    "ATR_20_O3",
    "ATR_20_H2O",
)

REQUIRED_AGWP_ATTRS: Final[tuple[str, ...]] = (
    "AGWP_20_CH4",
    "AGWP_20_O3",
    "AGWP_20_H2O",
    "AGWP_20_CONT",
    "AGWP_50_CH4",
    "AGWP_50_O3",
    "AGWP_50_H2O",
    "AGWP_50_CONT",
    "AGWP_100_CH4",
    "AGWP_100_O3",
    "AGWP_100_H2O",
    "AGWP_100_CONT",
)

REQUIRED_CONTRAIL_COLS: Final[tuple[str, ...]] = ("ef",)


class FlightWithRFContrailsImpact(FlightWithEmissions):
    """Zero-copy typed view for emissions-enriched flights."""

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_CONTRAIL_COLS


class FlightWithSegmentATR(FlightWithRFContrailsImpact):
    """
    Contains 4D segment-level columns for ATR.
    """

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_ATR_COLS


class FlightWithGlobalAGWP(FlightWithEmissions):
    """
    Contains aggregated attributes for AGWPS (including contrails).
    """

    ATTRS_REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_AGWP_ATTRS


FlightWithNonCO2Impact = FlightWithSegmentATR | FlightWithGlobalAGWP
