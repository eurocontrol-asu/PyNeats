"""
CoCiP Contrail Climate Function Module

Builds a wrapper around PyContrails' CoCiP to allow for the computation of contrail climate functions on a flight, adding the results as new columns to the flight data.

Key Components
--------------
- ContrailsParams: Parameters for the CoCiP model, including meteorological and radiative datasets.
- CoCiPModel: A class that implements the CoCiP model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.cocip import Cocip

from pyneats.core.fleet_utils import fleet_to_flights
from pyneats.core.fleet_utils import flights_to_fleet
from pyneats.core.neats_default_parameters import DEFAULT_COCIP_KWARGS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import ContrailsModel
from pyneats.steps.climate_functions.protocol import ContrailsStepError
from pyneats.steps.climate_functions.views import FlightWithRFContrailsImpact
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
@register(ContrailsModel, "cocip")  # type: ignore[type-abstract]
class CoCiPModel(
    BaseStep[
        FlightWithEmissions,
        FlightWithRFContrailsImpact,
        ContrailsParams,
    ]
):
    """Calculates contrail climate impact using the Pycontrails's CoCiP implementation"""

    default_params = ContrailsParams
    output_schema = FlightWithRFContrailsImpact

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

    def run(self, flight: FlightWithEmissions) -> FlightWithRFContrailsImpact:
        try:
            out: Flight = self._impl.eval(source=flight)
        except Exception as e:
            self.logger.exception("COCIP evaluation failed")
            raise ContrailsStepError(f"COCIP evaluation failed: {e}") from e

        self.logger.info("COCIP step completed successfully")
        return FlightWithRFContrailsImpact.from_flight(out)

    def run_fleet(
        self, flights: list[FlightWithEmissions]
    ) -> tuple[list[FlightWithRFContrailsImpact], list[dict[str, Any]]]:
        """
        Fleet-level vectorized CoCiP evaluation.

        Converts List[Flight] → Fleet, runs CoCiP on the entire fleet,
        then converts Fleet → List[Flight].

        Args:
            flights: List of flights with emissions data

        Returns:
            Tuple of (flights with contrails impact data, error records for dropped flights)

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

        # Convert back to List[Flight], detecting dropped flights
        out, errors = fleet_to_flights(results_fleet, step_name="CoCiP evaluation")

        # Zero-copy validation + type narrowing
        typed = [FlightWithRFContrailsImpact.from_flight(f) for f in out]

        self.logger.info("Fleet CoCiP step completed successfully")
        return typed, errors
