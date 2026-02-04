"""
Eurocontrol Emissions Model Module

Defines a placeholder for the Eurocontrol emissions model.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.params import EmissionParams
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.performance import FlightWithPerformance


__all__ = [
    "EurocontrolEmissionModel",
    "EurocontrolEmissionParams",
]


@dataclass(frozen=True)
class EurocontrolEmissionParams(EmissionParams):
    """
    Parameters for the Eurocontrol emissions model.
    """

    pass


@register(EmissionModel, "eurocontrol")
class EurocontrolEmissionModel(
    BaseStep[
        FlightWithPerformance,
        FlightWithEmissions,
        EurocontrolEmissionParams,
    ]
):
    """
    Placeholder for the Eurocontrol emissions model.
    """

    default_params = EurocontrolEmissionParams

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        """
        Not implemented.

        Parameters
        ----------
        flight : FlightWithPerformance
            Input flight with performance data.

        Returns
        -------
        FlightWithEmissions
            Flight with emissions columns (not implemented).

        Raises
        ------
        NotImplementedError
            Always raised.
        """
        raise NotImplementedError("EurocontrolEmissionModel is not yet implemented")
