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

import numpy as np
from pycontrails import Flight, Fleet
from pycontrails.core.met import MetDataset
from pycontrails.models.cocip import Cocip

from pyneats.core.neats_default_parameters import DEFAULT_COCIP_KWARGS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import ContrailsModel, ContrailsStepError
from pyneats.steps.climate_functions.views import FlightWithContrailsImpact
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.parsing.neats_parser import NEATSFuel

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
        fleet = self._seq_to_fleet(flights)

        # Run CoCiP on Fleet
        try:
            results_fleet = self._impl.eval(source=fleet)
        except Exception as e:
            self.logger.exception("Fleet CoCiP evaluation failed")
            raise ContrailsStepError(f"Fleet CoCiP evaluation failed: {e}") from e

        # Convert back to List[Flight]
        out = self._fleet_to_seq(results_fleet)

        # Zero-copy validation + type narrowing
        typed = [FlightWithContrailsImpact.from_flight(f) for f in out]

        self.logger.info("Fleet CoCiP step completed successfully")
        return typed

    @staticmethod
    def _seq_to_fleet(seq: List[Flight]) -> Fleet:
        """Convert List[Flight] to Fleet, preserving fuel information."""
        for s in seq:
            s.attrs['columns'] = set(s.data.keys())
            s["q_fuel"] = np.full(len(s), s.fuel.q_fuel)
            s["ei_h2o"] = np.full(len(s), s.fuel.ei_h2o)
            s.fuel = None

        fleet: Fleet = Fleet.from_seq(seq)
        fleet.attrs['columns'] = set(fleet.data.keys())
        return fleet

    @staticmethod
    def _fleet_to_seq(fleet: Fleet) -> List[Flight]:
        """Convert Fleet back to List[Flight], restoring fuel information."""
        fleet_columns = fleet.attrs.pop('columns')
        seq = fleet.to_flight_list()

        for s in seq:
            flight_columns = s.attrs.pop('columns')
            columns_to_delete = fleet_columns.difference(flight_columns)

            for c in columns_to_delete:
                s.data.pop(c)
            s.fuel = NEATSFuel.from_attrs(s.attrs)

        return seq
