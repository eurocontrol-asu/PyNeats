"""
Small Emitter Runner Module

Implements the OpenAirClim pipeline for small emitters, handling non-weather-based climate impact calculations.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Self

import pandas as pd

# Imports from framework modules
from pyneats.core.neats_default_parameters import DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS
from pyneats.core.steps_registry import build
from pyneats.runners.fleet import FleetRunner
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.flight import FlightRunner
from pyneats.runners.flight import RunnerConfig
from pyneats.steps.climate_functions import FlightWithNonCO2Impact
from pyneats.steps.climate_functions import NonCO2Model
from pyneats.steps.climate_functions.protocol import OpenAirClimStepError
from pyneats.steps.emissions import FlightWithEmissions
from pyneats.steps.weather import WeatherProviderProtocol


logger = logging.getLogger(__name__)

# --- CONFIGURATIONS ---


@dataclass
class SmallEmitterConfig(RunnerConfig):
    """
    Configuration preset for Small Emitters (OpenAirClim Pipeline).

    Attributes
    ----------
    non_co2_model : str
        Name of the non-CO2 model to use (default: open_airclim).
    """

    non_co2_model: str = DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS


@dataclass(kw_only=True)
class SmallFleetRunnerParams(FleetRunnerParams):
    """
    Fleet runner configuration for Small Emitters (OpenAirClim Pipeline).

    Adds the required 'tmp_base_dir_path' field for OpenAirClim file I/O.

    Attributes
    ----------
    non_co2_model : str
        Name of the non-CO2 model to use (default: open_airclim).
    tmp_base_dir_path : str
        Path for temporary file I/O required by OpenAirClim.
    """

    non_co2_model: str = DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS
    tmp_base_dir_path: str


# --- RUNNERS ---


class FlightRunnerSmallEmitter(FlightRunner):
    """
    Runner for small emitters using non-weather-based models (OpenAirClim pipeline).

    Pipeline:
        Emissions -> All Non-CO2 without weather (e.g., OpenAirClim) -> Metrics

    Methods
    -------
    _climate_impact()
        Compute non-CO2 effects using the configured non-CO2 model.
    """

    def __init__(
        self,
        weather: WeatherProviderProtocol,
        tmp_base_dir_path: str,
        source: pd.DataFrame | None = None,
        cfg: SmallEmitterConfig | None = None,
        bada_path: str | None = None,
        airport_fuel_path: str | None = None,
    ) -> None:
        # Run Shared Init
        super().__init__(weather, source, cfg, bada_path, airport_fuel_path)

        self.cfg = cfg or SmallEmitterConfig()

        # Initialize ONLY one non_CO2 model no call to CoCiP wich requires weather information
        non_co2_params = self.cfg.params.get("non_co2_model", {})
        non_co2_params.update({"tmp_base_dir_path": tmp_base_dir_path})

        self.non_co2_model = build(
            NonCO2Model,  # type: ignore[type-abstract]
            self.cfg.non_co2_model,
            **non_co2_params,
        )

    # Compute other non-CO₂ effects (aCCF)
    def _climate_impact(self) -> Self:
        if self.flight_with_emissions is None:
            logger.error(
                "Missing flight_with_emissions; did you call _emissions() first?"
            )
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
    Fleet runner for small emitters: Emissions -> Integrated Non-CO2 -> Metrics.

    Injects the 'tmp_base_dir_path' from the config into the model parameters automatically.
    """

    def __init__(self, cfg: SmallFleetRunnerParams) -> None:
        # ---------------------------------------------------------------
        # Parameter Injection
        # ---------------------------------------------------------------
        # inject the temp path into the params dict BEFORE calling
        # super().__init__(), because the base class builds the model
        # immediately upon initialization.

        # Build modified params without mutating the caller's cfg object
        _non_co2_params = {
            **cfg.params.get("non_co2_model", {}),
            "tmp_base_dir_path": cfg.tmp_base_dir_path,
        }
        cfg = dataclasses.replace(
            cfg, params={**cfg.params, "non_co2_model": _non_co2_params}
        )

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
            self.fleet_with_emissions, "integrated_non_co2", self.non_co2_model
        )
        self.error_records.extend(errs)

        # Cleanup intermediate state
        self.fleet_with_emissions = None

        return self
