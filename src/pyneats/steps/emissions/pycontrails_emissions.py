"""
PyContrails Emissions Model Module

Implements aircraft emissions calculation using pycontrails.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import numpy as np
from pycontrails import Flight
from pycontrails.models.emissions import Emissions
from pycontrails.models.emissions import nvpm

from pyneats.core.neats_default_parameters import DEFAULT_EMISSIONS_KWARGS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.params import EmissionParams
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.emissions.protocol import EmissionStepError
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.performance import FlightWithPerformance


__all__ = [
    "PyContrailsEmissionParams",
    "PyContrailsEmissionModel",
]

# nvPM mass EI of the pycontrails "Constant" route [kg/kg fuel]: 0.088 g/kg
# (Stettler et al., 2013), as in Emissions._nvpm_emission_indices_constant.
_CONSTANT_NVPM_EI_M = 0.088e-3


@dataclass(frozen=True)
class PyContrailsEmissionParams(EmissionParams):
    """
    Parameters for the PyContrails emission model calculation.
    """

    emissions_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: DEFAULT_EMISSIONS_KWARGS
    )


@register(EmissionModel, "pycontrails")  # type: ignore[type-abstract]
class PyContrailsEmissionModel(
    BaseStep[
        FlightWithPerformance,
        FlightWithEmissions,
        PyContrailsEmissionParams,
    ]
):
    """
    Calculates aircraft emissions using the pycontrails emissions model.

    This class wraps the pycontrails.Emissions calculator to compute
    aircraft emissions based on performance data. It handles:
    - Execution of emissions calculations
    - Error handling
    - Output validation

    Attributes
    ----------
    default_params : PyContrailsEmissionParams
        Default parameters for emissions calculations.
    _impl : Emissions
        The underlying pycontrails.Emissions calculator instance.
    """

    default_params = PyContrailsEmissionParams
    _impl: Emissions

    def _post_init(self) -> None:
        """
        Initialize the underlying pycontrails.Emissions calculator.
        """
        self._impl = Emissions(**self.params.emissions_kwargs)

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        """
        Calculate emissions for a flight using pycontrails.

        Parameters
        ----------
        flight : FlightWithPerformance
            Input flight with performance data.

        Returns
        -------
        FlightWithEmissions
            Flight with emissions columns added.

        Raises
        ------
        EmissionStepError
            If the backend evaluation fails.
        """
        try:
            out: Flight = self._impl.eval(flight)
            if _all_nan_nvpm(out):
                out = self._constant_nvpm_fallback(out)
        except Exception as e:
            raise EmissionStepError(f"backend eval failed: {e}") from e

        # Validate required emission columns and return typed view (zero-copy)
        return FlightWithEmissions.from_flight(out)

    def _constant_nvpm_fallback(self, out: Flight) -> Flight:
        """Replace all-NaN nvPM emission indices with the pycontrails constant ones.

        pycontrails >= 0.63 estimates nvPM with SCOPE11 for engines that have
        smoke numbers but no nvPM data in the ICAO EDB. SCOPE11 needs the bypass
        ratio, and EDB v32 has none for some engines (PW4098 ``5PW076``,
        JT9D ``8PW086``, ``8PW087``, ``8PW088``): nvPM is then NaN at every
        waypoint, with no warning, and CoCiP gets no contrail from the flight.

        The fallback gives the emission indices of the pycontrails "Constant"
        route (mass 0.088 g/kg fuel, number ``default_nvpm_ei_n``, both with the
        ICAO Annex 16 fuel correction) and runs pycontrails again, which keeps
        these columns and recomputes ``nvpm_mass``, ``nvpm_number`` and the
        totals. ``nvpm_data_source`` records the fallback.
        """
        source = out.attrs.get("nvpm_data_source")
        self.logger.warning(
            "Flight %s, engine %s: nvPM emission indices are all NaN (%s); "
            "constant nvPM emission indices used instead",
            out.attrs.get("flight_id"),
            out.attrs.get("engine_uid_used", out.attrs.get("engine_uid")),
            source,
        )
        thrust_setting = out["thrust_setting"]
        h_content = out.fuel.hydrogen_content
        k_mass = nvpm.nvpm_mass_fuel_correction_icao_annex_16(h_content, thrust_setting)
        k_num = nvpm.nvpm_number_fuel_correction_icao_annex_16(
            h_content, thrust_setting
        )
        ei_n = self._impl.params["default_nvpm_ei_n"]
        out["nvpm_ei_m"] = (
            np.full(out.size, _CONSTANT_NVPM_EI_M, dtype=np.float32) * k_mass
        )
        out["nvpm_ei_n"] = np.full(out.size, ei_n, dtype=np.float32) * k_num
        # pycontrails keeps nvPM EIs that are already set and recomputes the totals
        out = self._impl.eval(out)
        out.attrs["nvpm_data_source"] = f"Constant (fallback: {source} gave NaN nvPM)"
        return out


def _all_nan_nvpm(flight: Flight) -> bool:
    """True when ``nvpm_ei_n`` or ``nvpm_ei_m`` is NaN at every waypoint."""
    return any(
        col in flight and flight.size > 0 and bool(np.isnan(flight[col]).all())
        for col in ("nvpm_ei_n", "nvpm_ei_m")
    )
