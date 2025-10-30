from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from pycontrails import Flight
from pycontrails.models.emissions import Emissions

from pyneats.core.neats_default_parameters import DEFAULT_EMISSIONS_KWARGS
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

    """Parameters for the PyContrails emission model calculation."""

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
    """Calculates aircraft emissions using the pycontrails emissions model.
    
    This class wraps the pycontrails.Emissions calculator to compute
    aircraft emissions based on performance data. It handles:
    - Execution of emissions calculations
    - Error handling 
    - Output validation
    
    Attributes:
        default_params: Default parameters for emissions calculations
        _impl: The underlying pycontrails.Emissions calculator instance
    """

    default_params = PyContrailsEmissionParams
    _impl: Emissions

    def _post_init(self) -> None:
 
        self._impl = Emissions(**self.params.emissions_kwargs)

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:

        """Calculate emissions for a flight.
    
        Args:
            flight: Flight data with performance metrics
            
        Returns:
            FlightWithEmissions: Flight data with emissions calculations
            
        Raises:
            EmissionStepError: If the emissions calculation fails
        """
        try:
            out: Flight = self._impl.eval(flight)
        except Exception as e:
            raise EmissionStepError(f"backend eval failed: {e}") from e

        # Validate required emission columns and return typed view (zero-copy)
        return FlightWithEmissions.from_flight(out)
