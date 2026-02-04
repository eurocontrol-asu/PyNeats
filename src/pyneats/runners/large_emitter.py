"""
Large Emitter Runner Module

Implements the sequential "Standard" pipeline for NEATS:
    Emissions → Contrails (CoCiP) → Other Non-CO2 (ACCF) → Metrics

Classes
-------
FlightRunnerLargeEmitter
    Processes single trajectories with detailed physics for large emitters.
FleetRunnerLargeEmitter
    Processes fleets with vectorized CoCiP execution for large emitters.
"""

from __future__ import annotations

import logging
from typing import Self

import pandas as pd

from pyneats.core.steps_registry import build

# --- Import Base Classes from Framework Modules ---
from pyneats.runners.fleet import FleetRunner
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.flight import FlightRunner
from pyneats.runners.flight import RunnerConfig
from pyneats.steps.climate_functions.protocol import ACCFStepError
from pyneats.steps.climate_functions.protocol import ContrailsModel
from pyneats.steps.climate_functions.protocol import ContrailsStepError
from pyneats.steps.climate_functions.protocol import NonCO2Model
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
from pyneats.steps.climate_functions.views import FlightWithRFContrailsImpact
from pyneats.steps.emissions import FlightWithEmissions
from pyneats.steps.weather import WeatherProviderProtocol


logger = logging.getLogger(__name__)

__all__ = [
    "FlightRunnerLargeEmitter",
    "FleetRunnerLargeEmitter",
]


# -----------------------------------------------------------------------------
# Single Flight Runner (Sequential Logic)
# -----------------------------------------------------------------------------


class FlightRunnerLargeEmitter(FlightRunner):
    """
    Runner for large emitters using weather-based models and Lagrangian contrails modeling.

    Pipeline:
        Emissions -> Contrails (e.g., CoCiP) -> Other Non-CO2 (e.g., ACCF) -> Metrics

    Methods
    -------
    _climate_impact()
        Compute contrails and other non-CO2 effects.
    _contrails()
        Compute contrail effects using the configured contrails model.
    _other_nonco2()
        Compute other non-CO2 effects using the configured non-CO2 model.
    """

    def __init__(
        self,
        weather: WeatherProviderProtocol,
        source: pd.DataFrame | None = None,
        cfg: RunnerConfig | None = None,
        bada_path: str | None = None,
    ) -> None:
        # 1. Run Shared Init
        super().__init__(weather, source, cfg, bada_path)

        # Initialize Contrails (CoCiP)
        # Specific to this pipeline
        contrail_params = self.cfg.params.get("contrails_model", {})
        contrail_params.update(
            {
                "met": self.weather.met(),
                "rad": self.weather.rad(),
            },
        )
        self.contrails_model: ContrailsModel = build(
            ContrailsModel,  # type: ignore[type-abstract]
            self.cfg.contrails_model,
            **contrail_params,
        )

        self.flight_with_contrails: FlightWithRFContrailsImpact | None = None

    # Compute non CO2 climate impact
    def _climate_impact(self) -> Self:
        """
        Compute climate impact by running contrails and other non-CO2 steps sequentially.

        Returns
        -------
        Self
            The runner instance after processing.
        """
        return (
            self._contrails()._other_nonco2()  # pylint: disable=protected-access  # pylint: disable=protected-access
        )

    # Compute Contrails EF
    def _contrails(self) -> Self:
        """
        Compute contrail effects using the configured contrails model.

        Returns
        -------
        Self
            The runner instance after processing.

        Raises
        ------
        RuntimeError
            If emissions step was not run first or if contrails evaluation fails.
        """
        if self.flight_with_emissions is None:
            logger.error(
                "Missing flight_with_emissions; did you call _emissions() first?"
            )
            raise RuntimeError("_emissions() must be called before _contrails().")
        try:
            enriched: FlightWithRFContrailsImpact = self.contrails_model(
                self.flight_with_emissions
            )
        except ContrailsStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during contrails (COCIP) evaluation")
            raise RuntimeError(f"Contrails evaluation failed: {e}") from e
        self.flight_with_contrails = enriched
        logger.info("Contrails step completed successfully")
        return self

    # Compute other non-CO₂ effects (aCCF)
    def _other_nonco2(self) -> Self:
        """
        Compute other non-CO2 effects using the configured non-CO2 model.

        Returns
        -------
        Self
            The runner instance after processing.

        Raises
        ------
        RuntimeError
            If contrails step was not run first or if non-CO2 evaluation fails.
        """
        if self.flight_with_contrails is None:
            logger.error(
                "Missing flight_with_contrails; did you call _contrails() first?"
            )
            raise RuntimeError("_contrails() must be called before.")
        other_params = self.cfg.params.get("non_co2_model", {})
        other_params.update(
            {
                "met": self._ds_met,
                "surface": self._ds_rad,
            }
        )
        self.non_co2_model = build(
            NonCO2Model,  # type: ignore[type-abstract]
            self.cfg.non_co2_model,
            **other_params,
        )
        f_in: FlightWithEmissions = self.flight_with_contrails
        try:
            f_out: FlightWithNonCO2Impact = self.non_co2_model(f_in)
        except ACCFStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during non-CO₂ (ACCF) evaluation")
            raise RuntimeError(f"Non-CO₂ evaluation failed: {e}") from e
        self.flight_with_nonco2 = f_out
        logger.info("Other Non-CO₂step completed successfully")
        return self


# -----------------------------------------------------------------------------
# Fleet Runner (Vectorized Logic)
# -----------------------------------------------------------------------------


class FleetRunnerLargeEmitter(FleetRunner):
    """
    Fleet runner for large emitters using vectorized CoCiP execution.

    Methods
    -------
    _contrails()
        Run vectorized CoCiP for the fleet.
    _climate_impact()
        Compute contrails and other non-CO2 effects for the fleet.
    _other_nonco2()
        Compute other non-CO2 effects for the fleet.
    """

    def __init__(self, cfg: FleetRunnerParams) -> None:
        super().__init__(cfg)

        self.cocip_step: ContrailsModel | None = None

        self.fleet_with_contrails: list[FlightWithRFContrailsImpact] | None = None

    def _contrails(self) -> Self:
        if self.fleet_with_emissions is None:
            raise RuntimeError("_emissions must be set before _contrails()")
        if self.cocip_step is None:
            raise RuntimeError("cocip_step must be initialized before _contrails()")

        # Run vectorized CoCiP
        flights = self._run_vectorized_step(
            self.fleet_with_emissions,
            "CoCiP evaluation",
            self.cocip_step,
            self.cfg.cocip_critical_columns,
        )

        self.fleet_with_contrails = flights
        self.fleet_with_emissions = None  # free memory

        return self

    def _climate_impact(self) -> Self:
        return (
            self._contrails()._other_nonco2()  # pylint: disable=protected-access  # pylint: disable=protected-access
        )

    def _other_nonco2(self) -> Self:
        if self.fleet_with_contrails is None:
            raise RuntimeError("_contrails must be set before _nonco2()")

        self.fleet_with_nonco2, errs = self._run_parallel_step(
            self.fleet_with_contrails, "non_co2_model", self.non_co2_model
        )
        self.error_records.extend(errs)

        self.fleet_with_contrails = None  # free memory

        return self
