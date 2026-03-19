"""
NEATS Flight Runner Module

Implements the main execution pipeline for NEATS in the case of individual flights.
Orchestrates the sequential processing of flight data through multiple analysis stages:

Pipeline Stages
---------------
    - Flight parsing (NM/ADS-B data)
    - Trajectory interpolation
    - Weather data intersection
    - Aircraft performance computation
    - Emissions calculation
    - Contrail effects and Other Non-CO2 effects assessment
    - Non-CO2 equivalent computation

The climate impact step (contrails & others) depends on the set-up (small or large emitter).
This abstract class does not implement the climate impact step, which is defined
in the SmallEmitter and LargeEmitter classes.
"""

import logging
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Self

import pandas as pd
from pycontrails.core.met import MetDataset

from pyneats.core.neats_default_parameters import DEFAULT_CLIMATE_IMPACT
from pyneats.core.neats_default_parameters import DEFAULT_CONTRAILS_MODEL
from pyneats.core.neats_default_parameters import DEFAULT_EMISSIONS
from pyneats.core.neats_default_parameters import DEFAULT_INTERPOLATOR
from pyneats.core.neats_default_parameters import DEFAULT_NON_CO2_MODEL
from pyneats.core.neats_default_parameters import DEFAULT_PERFORMANCE
from pyneats.core.neats_default_parameters import DEFAULT_TRAJECTORY_PARSER
from pyneats.core.steps_registry import build
from pyneats.runners.runner import Runner
from pyneats.steps.climate_functions import FlightWithNonCO2Impact
from pyneats.steps.climate_functions import NonCO2Model
from pyneats.steps.climate_metrics import ClimateImpactModel
from pyneats.steps.climate_metrics import ClimateImpactStepError
from pyneats.steps.climate_metrics import FlightWithClimateImpact
from pyneats.steps.emissions import EmissionModel
from pyneats.steps.emissions import EmissionStepError
from pyneats.steps.emissions import FlightWithEmissions
from pyneats.steps.interpolation import TrajectoryInterpolationStepError
from pyneats.steps.interpolation import TrajectoryInterpolator
from pyneats.steps.parsing import Flight4D
from pyneats.steps.parsing import TrajectoryParser
from pyneats.steps.parsing import TrajectoryParserStepError
from pyneats.steps.performance import FlightWithPerformance
from pyneats.steps.performance import PerformanceModel
from pyneats.steps.performance import PerformanceStepError
from pyneats.steps.weather import FlightWithWeather
from pyneats.steps.weather import WeatherProviderProtocol
from pyneats.steps.weather import WeatherStepError


logger = logging.getLogger(__name__)


@dataclass
class RunnerConfig:
    """Names correspond to registry entries for each step."""

    interpolator: str = DEFAULT_INTERPOLATOR
    trajectory_parser: str = DEFAULT_TRAJECTORY_PARSER
    performance: str = DEFAULT_PERFORMANCE
    emissions: str = DEFAULT_EMISSIONS
    contrails_model: str = DEFAULT_CONTRAILS_MODEL
    non_co2_model: str = DEFAULT_NON_CO2_MODEL
    climate_impact: str = DEFAULT_CLIMATE_IMPACT

    params: dict[str, dict[str, Any]] = field(default_factory=dict)


class FlightRunner(Runner, ABC):
    """
    Parses, interpolates, and holds flight trajectory with met data.
    """

    # Explicit attribute types for static analysis
    _source: pd.DataFrame | None
    non_co2_model: NonCO2Model | None

    def __init__(
        self,
        weather: WeatherProviderProtocol,
        source: pd.DataFrame | None = None,
        cfg: RunnerConfig | None = None,
        bada_path: str | None = None,
        airport_fuel_path: str | None = None,
    ) -> None:
        self.cfg = cfg or RunnerConfig()

        self._source = None  # initialize backing field before using the property
        self.source = source  # use the property setter for validation
        self.weather = weather
        self.bada_path = bada_path
        self.airport_fuel_path = airport_fuel_path

        parser_params = dict(self.cfg.params.get("trajectory_parser", {}))
        if self.airport_fuel_path is not None:
            parser_params["airport_fuel_path"] = self.airport_fuel_path

        self.parser: TrajectoryParser = build(
            TrajectoryParser,
            self.cfg.trajectory_parser,
            **parser_params,
        )

        self.interpolator: TrajectoryInterpolator = build(
            TrajectoryInterpolator,
            self.cfg.interpolator,
            **self.cfg.params.get("interpolator", {}),
        )

        performance_params = self.cfg.params.get("performance", {})
        if self.bada_path is not None:
            performance_params.update(
                {
                    "bada4_root_path": self.bada_path,
                    "bada3_root_path": self.bada_path,
                },
            )

        self.performance: PerformanceModel = build(
            PerformanceModel,  # type: ignore[type-abstract]
            self.cfg.performance,
            **performance_params,
        )

        self.emission: EmissionModel = build(
            EmissionModel,  # type: ignore[type-abstract]
            self.cfg.emissions,
            **self.cfg.params.get("emissions", {}),
        )

        self.climate_impact: ClimateImpactModel = build(
            ClimateImpactModel,  # type: ignore[type-abstract]
            self.cfg.climate_impact,
            **self.cfg.params.get("climate_impact", {}),
        )

        # Pipeline elements' outputs
        self.parsed_flight: Flight4D | None = None
        self.interpolated_flight: Flight4D | None = None
        self.flight_with_weather: FlightWithWeather | None = None
        self.flight_with_performance: FlightWithPerformance | None = None
        self.flight_with_emissions: FlightWithEmissions | None = None
        self.flight_with_nonco2: FlightWithNonCO2Impact | None = None
        self.flight_with_climate_impact: FlightWithClimateImpact | None = None

        # Cached met/rad datasets after downselection for this flight
        self._ds_met: MetDataset | None = None
        self._ds_rad: MetDataset | None = None

    @property
    def source(self) -> pd.DataFrame | None:
        """
        Returns a shallow copy of the source DataFrame if it exists, otherwise returns None.

        Returns:
            pd.DataFrame | None: A shallow copy of the source DataFrame,
                or None if the source is not set.
        """
        return None if self._source is None else self._source.copy(deep=False)

    @source.setter
    def source(self, value: pd.DataFrame | None) -> None:
        """Set the trajectory dataframe with a defensive copy to avoid side effects."""
        if value is None:
            self._source = None
            return

        if not isinstance(value, pd.DataFrame):
            raise TypeError(f"source must be a pandas DataFrame, got {type(value)}")

        self._source = value.copy(deep=False)

    # Step 1: Parse flights (NM trajectories, ADS-B flights)
    def _parse_flight(self) -> Self:
        if self.source is None:
            logger.error("No source data provided before _parse_flight()")
            raise RuntimeError("Source data must be set before parsing flights.")

        # Run the parser
        try:
            parsed_flight: Flight4D = self.parser(self.source)
        except TrajectoryParserStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error while parsing trajectory")
            raise RuntimeError(f"Trajectory parsing failed: {e}") from e

        # Cache the parsed flight
        self.parsed_flight = parsed_flight

        logger.info(
            "Flight parsing completed successfully with %d points",
            len(self.parsed_flight.data),
        )

        return self

    # Step 2: Interpolate/reconstruct trajectory
    def _interpolate(self) -> Self:
        if self.parsed_flight is None:
            logger.error("Missing parsed_flight; did you call _parse_flight() first?")
            raise RuntimeError("_parse_flight() must be called before _interpolate().")

        # Run the interpolator
        try:
            interpolated_flight: Flight4D = self.interpolator(self.parsed_flight)
        except TrajectoryInterpolationStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during interpolation")
            raise RuntimeError(f"Interpolation failed: {e}") from e

        self.interpolated_flight = interpolated_flight
        #self.parsed_flight = None

        logger.info(
            "Interpolation completed successfully with %d points",
            len(interpolated_flight.data),
        )

        return self

    # Step 3: Intersect with weather data
    def _intersect_weather(self) -> Self:
        if self.interpolated_flight is None:
            logger.error(
                "Missing interpolated_flight; did you call _interpolate() first?"
            )
            raise RuntimeError(
                "_interpolate() must be called before _intersect_weather()."
            )

        # Run the weather intersection step
        try:
            enriched: FlightWithWeather = self.weather(self.interpolated_flight)
        except WeatherStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during weather intersection")
            raise RuntimeError(f"Weather intersection failed: {e}") from e

        self.flight_with_weather = enriched
        # self.interpolated_flight = None

        # Cache the downsampled met/rad datasets for later use (e.g accfs)
        self._ds_met = self.weather.ds_met()
        self._ds_rad = self.weather.ds_rad()

        logger.info(
            "Weather intersection completed successfully with %d points",
            len(self.flight_with_weather.data),
        )

        return self

    # Step 4: Run Performance model
    def _performance(self) -> Self:
        if self.flight_with_weather is None:
            logger.error(
                "Missing flight_with_weather; did you call _intersect_weather() first?"
            )
            raise RuntimeError(
                "_intersect_weather() must be called before _performance()."
            )

        try:
            enriched: FlightWithPerformance = self.performance(self.flight_with_weather)
        except PerformanceStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during performance evaluation")
            raise RuntimeError(f"Performance evaluation failed: {e}") from e

        self.flight_with_performance = enriched
        # self.flight_with_weather = None
        logger.info("Performance step completed successfully")

        return self

    # Step 5: Run Emission model
    def _emissions(self) -> Self:
        if self.flight_with_performance is None:
            logger.error(
                "Missing flight_with_performance; did you call performance() first?"
            )
            raise RuntimeError("performance() must be called before _emissions().")
        try:
            enriched: FlightWithEmissions = self.emission(self.flight_with_performance)
        except EmissionStepError:
            # Already logged inside the emissions step; just propagate.
            raise
        except Exception as e:
            logger.exception("Unexpected error during emissions backend evaluation")
            raise RuntimeError(f"Emissions evaluation failed: {e}") from e

        # Get the typed, zero-copy view
        self.flight_with_emissions = enriched
        # self.flight_with_performance = None

        logger.info("Emissions step completed successfully")
        return self

    # Step 6 Compute non CO2 climate impact
    @abstractmethod
    def _climate_impact(self) -> Self:
        """Abstract method."""

    # Step 7: Compute CO2 equivalent (using GWP for instance)
    def _climate_metrics(self) -> Self:
        if self.flight_with_nonco2 is None:
            logger.error("Missing flight_with_nonco2; did you call _nonco2() first?")
            raise RuntimeError("_nonco2() must be called before _gwp().")

        try:
            enriched: FlightWithClimateImpact = self.climate_impact(
                self.flight_with_nonco2
            )  # returns FlightWithClimateImpact
        except ClimateImpactStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during climate impact (GWP) evaluation")
            raise RuntimeError(f"Climate impact evaluation failed: {e}") from e

        # keep the typed, zero-copy view
        self.flight_with_climate_impact = enriched
        # self.flight_with_nonco2 = None

        logger.info("Climate impact (GWP) step completed successfully")

        return self

    def _load_data(self) -> Self:
        return self

    def _extract_results(self) -> Self:
        return self
