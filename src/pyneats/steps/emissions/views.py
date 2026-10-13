"""
Emissions Views Module

Defines zero-copy typed views for emissions-enriched flights.
"""

from __future__ import annotations

from typing import ClassVar
from typing import Final

from pyneats.steps.performance.views import FlightWithPerformance


__all__ = [
    "REQUIRED_EMISSION_COLS",
    "FlightWithEmissions",
]

# nvpm_ei_m [kg nvPM / kg fuel]; nox_ei [kg NOx / kg fuel], NOx expressed as
# NO2 (pycontrails, ICAO EDB convention).
REQUIRED_EMISSION_COLS: Final[tuple[str, ...]] = ("nvpm_ei_m", "nox_ei")


class FlightWithEmissions(FlightWithPerformance):
    """
    Zero-copy typed view for emissions-enriched flights.

    Only ``nvpm_ei_m`` and ``nox_ei`` are enforced. With the ``pycontrails``
    emissions backend the flight also carries, per waypoint:

    - ``co2``, ``h2o``, ``so2``, ``sulphates``, ``oc``, ``nox``, ``co``,
      ``hc``, ``nvpm_mass``: mass emitted over the segment [kg], i.e. fuel
      burned (whole-aircraft ``fuel_flow`` [kg/s] x segment duration [s])
      times the emission index.
    - ``nvpm_number``: number of nvPM particles emitted over the segment.
    - ``nox_ei``, ``co_ei``, ``hc_ei``, ``nvpm_ei_m``: emission indices
      [kg/kg fuel]; ``nvpm_ei_n``: particles per kg fuel.
    - ``attrs["total_<species>"]``: flight totals (``np.nansum`` of the
      per-segment values; kg, or a count for ``total_nvpm_number``).
      Segments with NaN emission indices (e.g. NOx/CO/HC outside the met
      domain) contribute nothing to the totals.

    Attributes
    ----------
    REQUIRED : ClassVar[tuple[str, ...]]
        Required emission columns.
    """

    REQUIRED: ClassVar[tuple[str, ...]] = REQUIRED_EMISSION_COLS
