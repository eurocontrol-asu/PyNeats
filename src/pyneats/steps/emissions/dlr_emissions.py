from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.emissions.params import EmissionParams
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.emissions.protocol import EmissionModel

__all__ = ["DLREmissionModel"]


@dataclass(frozen=True)
class DLREmissionParams(EmissionParams):
    pass


@register(EmissionModel, "dlr")
class DLREmissionModel(
    BaseStep[
        FlightWithPerformance,
        FlightWithEmissions,
        DLREmissionParams,
    ]
):
    default_params = DLREmissionParams

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        raise NotImplementedError("DLREmissionModel is not yet implemented")
