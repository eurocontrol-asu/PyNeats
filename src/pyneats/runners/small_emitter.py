from __future__ import annotations
from dataclasses import dataclass
import logging
from typing import Self
import pandas as pd

# Imports from framework modules
from pyneats.core.neats_default_parameters import DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS
from pyneats.runners.flight import FlightRunner, RunnerConfig
from pyneats.runners.fleet import FleetRunner, FleetRunnerParams
from pyneats.steps.weather import WeatherProviderProtocol
from pyneats.core.steps_registry import build
from pyneats.steps.climate_functions import (
    FlightWithNonCO2Impact,
    NonCO2Model
)
from pyneats.steps.climate_functions.protocol import OpenAirClimStepError
from pyneats.steps.emissions import FlightWithEmissions

logger = logging.getLogger(__name__)

# --- CONFIGURATIONS ---

@dataclass
class SmallEmitterConfig(RunnerConfig):
    """Configuration Preset for Small Emitters (OpenAirClim Pipeline)
    

    """
    # contrails_model is ignored by the SmallEmitter runner
    non_co2_model: str = DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS


@dataclass(kw_only=True)
class SmallFleetRunnerParams(FleetRunnerParams):
    """
    Configuration Preset for Small Emitters (OpenAirClim Pipeline).
    
    Adds the required 'tmp_base_dir_path' field for OpenAirClim file I/O.
    """
    # Override the default model name
    non_co2_model: str = DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS
    
    # New required field for this pipeline type
    tmp_base_dir_path: str


# --- RUNNERS ---

class FlightRunnerSmallEmitter(FlightRunner):
    """

    Small Emitters don't use weather based models. 
    An unified modelling set-up can be applied for both contrails and NOx
    
    Lightweight Pipeline: Emissions -> All Non CO2 without weather (ex: OpenAirClim) -> Metrics
    
    """
    def __init__(
        self,
        weather: WeatherProviderProtocol,
        tmp_base_dir_path: str,
        source: pd.DataFrame | None = None,
        cfg: SmallEmitterConfig | None = None, 
        bada_path: str | None = None,
    ) -> None:
        # Run Shared Init
        super().__init__(weather, source, cfg, bada_path)

        self.cfg = cfg or SmallEmitterConfig()

        # Initialize ONLY one non_CO2 model no call to CoCiP wich requires weather information
        non_co2_params = self.cfg.params.get("non_co2_model", {})
        non_co2_params.update(
            {
                "tmp_base_dir_path" : tmp_base_dir_path
            }
        )

        self.non_co2_model = build(
            NonCO2Model,  # type: ignore[type-abstract]
            self.cfg.non_co2_model,
            **non_co2_params,
        )
        

    # Compute other non-CO₂ effects (aCCF)
    def _climate_impact(self) -> Self:

        if self.flight_with_emissions is None:
            logger.error("Missing flight_with_emissions; did you call _emissions() first?")
            raise RuntimeError("_emissions() must be called before.")

        f_in: FlightWithEmissions = self.flight_with_emissions

        try:
            f_out: FlightWithNonCO2Impact = self.non_co2_model(f_in)
        except OpenAirClimStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during non-CO₂ evaluation")
            raise RuntimeError(f"Non-CO₂ evaluation failed: {e}") from e

        # Zero-copy validated view
        self.flight_with_nonco2 = f_out
        logger.info("Non-CO₂ step completed successfully")

        return self

class FleetRunnerSmallEmitter(FleetRunner):
    """
    Small Emitters Pipeline: Emissions -> Integrated Non-CO2 -> Metrics.
    
    This runner injects the 'tmp_base_dir_path' from the config into the 
    model parameters automatically.
    """

    def __init__(self, cfg: SmallFleetRunnerParams) -> None:

        # ---------------------------------------------------------------
        # Parameter Injection
        # ---------------------------------------------------------------
        # inject the temp path into the params dict BEFORE calling 
        # super().__init__(), because the base class builds the model 
        # immediately upon initialization.
        
        # Ensure the parameter dictionary for non_co2_model exists
        if "non_co2_model" not in cfg.params:
            cfg.params["non_co2_model"] = {}

        # Inject the path (matches logic from FlightRunnerSmallEmitter)
        cfg.params["non_co2_model"]["tmp_base_dir_path"] = cfg.tmp_base_dir_path
        
        # ---------------------------------------------------------------
        # Shared Initialization
        # ---------------------------------------------------------------
        super().__init__(cfg)
        
        # self.non_co2_model is now built (by super) containing the tmp path param.


    def _climate_impact(self) -> Self:
        """
        Execute the integrated climate impact step (Direct Emissions -> NonCO2).
        Skips CoCiP entirely.
        """
        if self.fleet_with_emissions is None:
            raise RuntimeError("_emissions must be set before _climate_impact()")

        # Run the integrated model (ex: OpenAirClim)
        # map over the fleet using the generic parallel runner
        self.fleet_with_nonco2, errs = self._run_parallel_step(
            self.fleet_with_emissions,
            "integrated_non_co2",
            self.non_co2_model
        )
        self.error_records.extend(errs)

        # Cleanup intermediate state
        self.fleet_with_emissions = None 


        return self
