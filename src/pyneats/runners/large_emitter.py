"""
Large Emitter Runner Module

This module implements the sequential "Standard" pipeline for NEATS:
    Emissions -> Contrails (CoCiP) -> Other Non-CO2 (ACCF) -> Metrics

It contains:
- Configuration presets for Large Emitters
- FlightRunnerLargeEmitter: For processing single trajectories with detailed physics
- FleetRunnerLargeEmitter: For processing fleets with vectorized CoCiP execution
"""

from __future__ import annotations

import logging
from typing import Self
import pandas as pd

from pyneats.core.steps_registry import build
from pyneats.steps.climate_functions.protocol import (
    ACCFStepError,
    ContrailsModel,
    ContrailsStepError,
    NonCO2Model,
)
from pyneats.steps.climate_functions.views import (
    FlightWithNonCO2Impact,
    FlightWithRFContrailsImpact,
)
from pyneats.steps.weather import WeatherProviderProtocol
from pyneats.steps.emissions import FlightWithEmissions

# --- Import Base Classes from Framework Modules ---
from pyneats.runners.fleet import FleetRunner, FleetRunnerParams
from pyneats.runners.flight import FlightRunner, RunnerConfig

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
    The Large Emitter setup allows the use of weather based models
    Lagragian models can then be used for Contrails modelling
    This introduces a different computation step for contrails

    Pipeline: Emissions -> Contrails (ex: CoCiP) -> Other Non CO2 (ex: ACCF) -> Metrics

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
        
        return (
            self._contrails()  # pylint: disable=protected-access
            ._other_nonco2()  # pylint: disable=protected-access
        )
    
    # Compute Contrails EF
    def _contrails(self) -> Self:

        if self.flight_with_emissions is None:
            logger.error("Missing flight_with_emissions; did you call _emissions() first?")
            raise RuntimeError("_emissions() must be called before _contrails().")

        # Run the contrails step (COCIP). It returns a base Flight.
        try:
            enriched: FlightWithRFContrailsImpact = self.contrails_model(self.flight_with_emissions)
        except ContrailsStepError:
            # Already logged inside the model; keep original traceback.
            raise
        except Exception as e:
            logger.exception("Unexpected error during contrails (COCIP) evaluation")
            raise RuntimeError(f"Contrails evaluation failed: {e}") from e

        # Zero-copy validated view for ergonomic access (e.g., .ef property)
        self.flight_with_contrails = enriched
        #self.flight_with_emissions = None

        logger.info("Contrails step completed successfully")

        return self

    # Compute other non-CO₂ effects (aCCF)
    def _other_nonco2(self) -> Self:

        if self.flight_with_contrails is None:
            logger.error("Missing flight_with_contrails; did you call _contrails() first?")
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

        # Zero-copy validated view
        self.flight_with_nonco2 = f_out
        logger.info("Other Non-CO₂step completed successfully")

        return self
    

    

# -----------------------------------------------------------------------------
# Fleet Runner (Vectorized Logic)
# -----------------------------------------------------------------------------

class FleetRunnerLargeEmitter(FleetRunner):

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
            self._contrails()  # pylint: disable=protected-access
            ._other_nonco2()  # pylint: disable=protected-access
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





