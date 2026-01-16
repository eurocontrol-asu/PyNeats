"""
This module builds a wrapper around PyContrail's CoCip to allow for the computation 
of contrail climate functions on a flight, adding the results as new columns to the flight data.

Key components:
- `ContrailsParams`: Parameters for the CoCiP model, including meteorological and radiative datasets.
- `CoCiPModel`: A class that implements the CoCiP model.

"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping

from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.cocip import Cocip

from pyneats.core.fleet_utils import fleet_to_flights, flights_to_fleet
from pyneats.core.neats_default_parameters import DEFAULT_COCIP_KWARGS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import ContrailsModel, ContrailsStepError
from pyneats.steps.climate_functions.views import FlightWithContrailsImpact
from pyneats.steps.emissions.views import FlightWithEmissions

__all__ = [
    "ContrailsParams",
    "CoCiPModel",
]


@dataclass(frozen=True)
class ContrailsParams(ClimateParams):
    """Parameters for the CoCiP model."""
    met: MetDataset | None = None
    rad: MetDataset | None = None

    cocip_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: DEFAULT_COCIP_KWARGS
    )


# ---- PyContrails COCIP wrapper ------------------------------------
@register(ContrailsModel, "cocip")
class CoCiPModel(
    BaseStep[
        FlightWithEmissions,
        FlightWithContrailsImpact,
        ContrailsParams,
    ]
):
    """Calculates contrail climate impact using the Pycontrails's CoCiP implementation"""

    default_params = ContrailsParams

    def _post_init(self) -> None:
        if self.params.met is None or self.params.rad is None:
            raise ContrailsStepError("COCIP requires both 'met' and 'rad' datasets.")

        try:
            self._impl = Cocip(
                met=self.params.met,
                rad=self.params.rad,
                **self.params.cocip_kwargs,
            )
        except Exception as e:
            self.logger.exception("Failed to initialize COCIP model")
            raise ContrailsStepError(f"COCIP initialization failed: {e}") from e

    def run(self, flight: FlightWithEmissions) -> FlightWithContrailsImpact:
        try:
            out: Flight = self._impl.eval(source=flight)
        except Exception as e:
            self.logger.exception("COCIP evaluation failed")
            raise ContrailsStepError(f"COCIP evaluation failed: {e}") from e

        self.logger.info("COCIP step completed successfully")
        return FlightWithContrailsImpact.from_flight(out)

    def run_fleet(self, flights: List[FlightWithEmissions]) -> List[FlightWithContrailsImpact]:
        """
        Fleet-level vectorized CoCiP evaluation.

        Converts List[Flight] → Fleet, runs CoCiP on the entire fleet,
        then converts Fleet → List[Flight].

        Args:
            flights: List of flights with emissions data

        Returns:
            List of flights with contrails impact data

        Raises:
            ContrailsStepError: If CoCiP evaluation fails
        """
        self.logger.info("Fleet-level CoCiP evaluation for %d flights...", len(flights))

        # Convert to Fleet
        fleet = flights_to_fleet(flights)

        # Run CoCiP on Fleet
        try:
            results_fleet = self._impl.eval(source=fleet)
        except Exception as e:
            self.logger.exception("Fleet CoCiP evaluation failed")
            raise ContrailsStepError(f"Fleet CoCiP evaluation failed: {e}") from e

        # Convert back to List[Flight]
        out = fleet_to_flights(results_fleet)

        # Zero-copy validation + type narrowing
        typed = [FlightWithContrailsImpact.from_flight(f) for f in out]

        self.logger.info("Fleet CoCiP step completed successfully")
        return typed
