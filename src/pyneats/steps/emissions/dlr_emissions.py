from __future__ import annotations

import logging
from pyneats.core.steps import BaseStep
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.emissions.views import (
    FlightWithEmissions,
    DEFAULT_REQUIRED_EMISSION_COLS,
)
from pyneats.steps.emissions.pycontrails_emissions import EmissionsStepError

__all__ = ["DLREmissionModel"]

logger = logging.getLogger(__name__)

class DLREmissionModel(BaseStep[FlightWithPerformance, FlightWithEmissions]):
    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        super().__init__()
        self.required_cols = required_cols

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        raise EmissionsStepError(type(self).__name__, "not implemented")
