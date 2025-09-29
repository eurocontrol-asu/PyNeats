from __future__ import annotations

import logging
from pyneats.core.steps import BaseStep
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.emissions.views import (
    FlightWithEmissions,
    DEFAULT_REQUIRED_EMISSION_COLS,
)
from pyneats.steps.emissions.protocol import EmissionsStepError
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.protocol import EmissionModel

__all__ = ["EurocontrolEmissionModel"]

logger = logging.getLogger(__name__)

@register(EmissionModel, "eurocontrol")
class EurocontrolEmissionModel(BaseStep[FlightWithPerformance, FlightWithEmissions]):
    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        super().__init__()
        self.required_cols = required_cols

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        raise EmissionsStepError(type(self).__name__, "not implemented")
