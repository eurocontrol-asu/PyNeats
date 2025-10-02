from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from pycontrails import Flight
from pycontrails.models.emissions import Emissions

from pyneats.core.neats_defaults import DEFAULT_EMISSIONS_KWARGS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.emissions.params import EmissionParams
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.emissions.protocol import EmissionStepError, EmissionModel

__all__ = [
    "PyContrailsEmissionParams",
    "PyContrailsEmissionModel",
]


@dataclass(frozen=True)
class PyContrailsEmissionParams(EmissionParams):
    emissions_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: DEFAULT_EMISSIONS_KWARGS
    )


@register(EmissionModel, "pycontrails")
class PyContrailsEmissionModel(
    BaseStep[
        FlightWithPerformance,
        FlightWithEmissions,
        PyContrailsEmissionParams,
    ]
):
    """
    Thin wrapper over pycontrails.Emissions:
    - input:  FlightWithPerformance (validated upstream)
    - output: FlightWithEmissions (validated here, zero-copy)
    """

    default_params = PyContrailsEmissionParams

    def _post_init(self) -> None:
        """Optional hook for subclasses to initialize additional attributes."""
        self._impl = Emissions(**self.params.emissions_kwargs)

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        try:
            out: Flight = self._impl.eval(flight)
        except Exception as e:
            raise EmissionStepError(f"backend eval failed: {e}") from e

        # Validate required emission columns and return typed view (zero-copy)
        return FlightWithEmissions.from_flight(out)
