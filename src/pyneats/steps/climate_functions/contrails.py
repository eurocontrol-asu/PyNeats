# contrails.py

"""
contrails.py

This script builds a wrapper around CoCip to allow for the computation of contrail climate functions 
on a flight, adding the results as new columns to the flight data.

Key components:
- `ContrailsParams`: Parameters for the CoCiP model, including meteorological and radiative datasets.
- `CoCiPModel`: A class that implements the CoCiP model.

"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.cocip import Cocip

from pyneats.core.neats_default_parameters import DEFAULT_COCIP_KWARGS
from pyneats.steps.climate_functions.protocol import ContrailsModel, ContrailsStepError
from pyneats.steps.climate_functions.views import FlightWithContrailsImpact
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register

__all__ = [
    "ContrailsParams",
    "CoCiPModel",
]


@dataclass(frozen=True)
class ContrailsParams(ClimateParams):
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
