"""
DLR Emissions Model Module

Defines a placeholder for the DLR emissions model.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.params import EmissionParams
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.performance import FlightWithPerformance


__all__ = ["DLREmissionModel"]


@dataclass(frozen=True)
class DLREmissionParams(EmissionParams):
    """
    Parameters for the DLR emissions model.
    """

    pass


@register(EmissionModel, "dlr")
class DLREmissionModel(
    BaseStep[
        FlightWithPerformance,
        FlightWithEmissions,
        DLREmissionParams,
    ]
):
    """
    Placeholder for the DLR emissions model.
    """

    default_params = DLREmissionParams

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
        raise NotImplementedError("DLREmissionModel is not yet implemented")
