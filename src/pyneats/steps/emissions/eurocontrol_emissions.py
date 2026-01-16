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
    pass


@register(EmissionModel, "eurocontrol")
class EurocontrolEmissionModel(
    BaseStep[
        FlightWithPerformance,
        FlightWithEmissions,
        EurocontrolEmissionParams,
    ]
):
    default_params = EurocontrolEmissionParams

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        raise NotImplementedError("EurocontrolEmissionModel is not yet implemented")
