from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from pycontrails import Flight
from pycontrails.models.emissions import Emissions

from pyneats.core.steps import BaseStep, StepError
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.emissions.views import (
    FlightWithEmissions,
    DEFAULT_REQUIRED_EMISSION_COLS,
)

__all__ = [
    "EmissionsStepError",
    "PyContrailsEmissionParams",
    "PyContrailsEmissionModel",
]

logger = logging.getLogger(__name__)

class EmissionsStepError(StepError):
    """Normalized domain error for the emissions step."""

@dataclass(frozen=True)
class PyContrailsEmissionParams:
    extra_kwargs: Optional[Mapping[str, Any]] = None

class PyContrailsEmissionModel(BaseStep[FlightWithPerformance, FlightWithEmissions]):
    """
    Thin wrapper over pycontrails.Emissions:
    - input:  FlightWithPerformance (validated upstream)
    - output: FlightWithEmissions (validated here, zero-copy)
    """

    def __init__(
        self,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS,
        params: PyContrailsEmissionParams | None = None,
    ) -> None:
        super().__init__()
        self.required_cols = required_cols
        extra = dict(params.extra_kwargs) if (params and params.extra_kwargs) else {}
        self._impl = Emissions(**extra)

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        try:
            out: Flight = self._impl.eval(flight)  # pycontrails attaches columns on the same Flight
        except Exception as e:
            raise EmissionsStepError(type(self).__name__, f"backend eval failed: {e}") from e

        # Validate required emission columns and return typed view (zero-copy)
        return FlightWithEmissions.from_flight(out, require=self.required_cols)
