""" NEATS Flight Runner Module

This module implements the main execution pipeline for NEATS. 
It orchestrates the sequential processing of flight data through multiple analysis stages:

Pipeline Stages:
   - Flight parsing (NM/ADS-B data)
   - Trajectory interpolation
   - Weather data intersection
   - Aircraft performance computation
   - Emissions calculation
   - Contrail effects assessment
   - Other Non-CO2 effects assessment
   - Climate impact metrics computation
"""

import logging
import time
from typing import Any, Optional
from dataclasses import dataclass, field
from typing_extensions import Self
import pandas as pd

from pycontrails.core.met import MetDataset

from pyneats.steps.climate_functions import (
    ContrailsModel,
    FlightWithContrailsImpact,
    FlightWithNonCO2Impact,
    NonCO2Model,
    ContrailsStepError,
    ClimateStepError
)

from pyneats.steps.climate_metrics import (
    FlightWithClimateImpact,
    ClimateImpactModel,
    ClimateImpactStepError,

)


from pyneats.steps.interpolation import (
    TrajectoryInterpolator,
    TrajectoryInterpolationStepError,
)

from pyneats.steps.parsing import (
    TrajectoryParserStepError,
    Flight4D,
    TrajectoryParser,
)

from pyneats.steps.performance import (
    FlightWithPerformance,
    PerformanceStepError,
    PerformanceModel,
)

from pyneats.steps.emissions import (
    EmissionStepError,
    FlightWithEmissions,
    EmissionModel,
)

from pyneats.steps.weather import (
    WeatherProviderProtocol,
    WeatherStepError,
    FlightWithWeather,
)

from pyneats.core.neats_default_parameters import (
    DEFAULT_INTERPOLATOR,
    DEFAULT_TRAJECTORY_PARSER,
    DEFAULT_EMISSIONS,
    DEFAULT_PERFORMANCE,
    DEFAULT_CONTRAILS_MODEL,
    DEFAULT_NON_CO2_MODEL,
    DEFAULT_CLIMATE_IMPACT,
)

from pyneats.core.steps_registry import build

logger = logging.getLogger(__name__)


@dataclass
class RunnerConfig:
    """Names correspond to registry entries (case-insensitive) for each step."""

    interpolator: str = DEFAULT_INTERPOLATOR
    trajectory_parser: str = DEFAULT_TRAJECTORY_PARSER
    performance: str = DEFAULT_PERFORMANCE
    emissions: str = DEFAULT_EMISSIONS
    contrails_model: str = DEFAULT_CONTRAILS_MODEL
    non_co2_model: str = DEFAULT_NON_CO2_MODEL
    climate_impact: str = DEFAULT_CLIMATE_IMPACT

    params: dict[str, dict[str, Any]] = field(default_factory=dict)


class FlightRunner:
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
        cfg: Optional[RunnerConfig] = None,
    ) -> None:

        self.cfg = cfg or RunnerConfig()

        self._source = None  # initialize backing field before using the property
        self.source = source  # use the property setter for validation
        self.weather = weather

        self.parser: TrajectoryParser = build(
            TrajectoryParser,
            self.cfg.trajectory_parser,
            **self.cfg.params.get("trajectory_parser", {}),
        )

        self.interpolator: TrajectoryInterpolator = build(
            TrajectoryInterpolator,
            self.cfg.interpolator,
            **self.cfg.params.get("interpolator", {}),
        )

        self.performance: PerformanceModel = build(
            PerformanceModel,
            self.cfg.performance,
            **self.cfg.params.get("performance", {}),
        )

        self.emission: EmissionModel = build(
            EmissionModel,
            self.cfg.emissions,
            **self.cfg.params.get("emissions", {}),
        )

        contrail_params = self.cfg.params.get("contrails_model", {})
        contrail_params.update(
            {
                "met": self.weather.met(),
                "rad": self.weather.rad(),
            },
        )
        self.contrails_model: ContrailsModel = build(
            ContrailsModel,
            self.cfg.contrails_model,
            **contrail_params,
        )

        self.climate_impact: ClimateImpactModel = build(
            ClimateImpactModel,
            self.cfg.climate_impact,
            **self.cfg.params.get("climate_impact", {}),
        )

        # Pipeline elements' outputs
        self.parsed_flight: Flight4D | None = None
        self.interpolated_flight: Flight4D | None = None
        self.flight_with_weather: FlightWithWeather | None = None
        self.flight_with_performance: FlightWithPerformance | None = None
        self.flight_with_emissions: FlightWithEmissions | None = None
        self.flight_with_contrails: FlightWithContrailsImpact | None = None
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
            pd.DataFrame | None: A shallow copy of the source DataFrame, or None if the source is not set.
        """
        return None if self._source is None else self._source.copy(deep=False)

    @source.setter
    def source(self, value: pd.DataFrame | None) -> None:
        """Set the trajectory dataframe with a defensive copy to avoid side effects."""
        if value is None:
            self._source = None
            return

        if not isinstance(value, pd.DataFrame):  # type: ignore[unnecessary-isinstance]
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
        #self.interpolated_flight = None

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
        #self.flight_with_weather = None
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
        #self.flight_with_performance = None

        logger.info("Emissions step completed successfully")
        return self

    # Step 6: Compute Contrails EF
    def _contrails(self) -> Self:

        start = time.time()
        if self.flight_with_emissions is None:
            logger.error(
                "Missing flight_with_emissions; did you call _emissions() first?"
            )
            raise RuntimeError("_emissions() must be called before _contrails().")

        # Run the contrails step (COCIP). It returns a base Flight.
        try:
            enriched: FlightWithContrailsImpact = self.contrails_model(
                self.flight_with_emissions
            )
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
        end = time.time()

        self.flight_with_contrails.attrs["contrails_computation_time"] = end - start

        return self

    # Step 7: Compute other non-CO₂ effects (aCCF)
    def _nonco2(self) -> Self:

        start = time.time()
        if self.flight_with_contrails is None:
            logger.error(
                "Missing flight_with_contrails; did you call _contrails() first?"
            )
            raise RuntimeError("_contrails() must be called before.")

        accf_params = self.cfg.params.get("non_co2_model", {})
        accf_params.update(
            {
                "met": self._ds_met,
                "surface": self._ds_rad,
            }
        )
        self.non_co2_model = build(
            NonCO2Model,
            self.cfg.non_co2_model,
            **accf_params,
        )

        f_in: FlightWithEmissions = self.flight_with_contrails

        try:
            f_out: FlightWithNonCO2Impact = self.non_co2_model(f_in)
        except ClimateStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during non-CO₂ (ACCF) evaluation")
            raise RuntimeError(f"Non-CO₂ evaluation failed: {e}") from e

        # Zero-copy validated view
        self.flight_with_nonco2 = f_out
        logger.info("Non-CO₂ (ACCF) step completed successfully")
        end = time.time()

        self.flight_with_nonco2.attrs["non_co2_computation_time"] = end - start
        return self

    # Step 8: Compute Climate Impact (GWP)
    def _gwp(self) -> Self:
        if self.flight_with_nonco2 is None:
            logger.error(
                "Missing flight_with_contrails; did you call _contrails() first?"
            )
            raise RuntimeError("_contrails() must be called before _gwp().")

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
        logger.info("Climate impact (GWP) step completed successfully")

        return self

    def eval(self) -> Self:
        """
        Run the full NEATS processing pipeline on the current flight.

        This method executes all processing stages in sequence:

            1. `_parse_flight()` — Parse the raw trajectory data into a validated `Flight` object.
            2. `_interpolate()` — Interpolate or reconstruct the trajectory to uniform time steps.
            3. `_intersect_weather()` — Intersect the trajectory with meteorological data.
            4. `_performance()` — Compute aircraft performance metrics (e.g., fuel flow, thrust).
            5. `_emissions()` — Estimate non-CO₂ and CO₂ emissions.
            6. `_contrails()` — Simulate contrail formation and compute energy forcing.
            7. `_gwp()` — Convert contrail energy forcing into climate impact metrics (e.g., CO₂eq).

        Returns
        -------
        Self
            The `FlightRunner` instance with the final processed flight in `self.current`
            and all intermediate results available in their respective attributes.
        """
        return (
            self._parse_flight()  # pylint: disable=protected-access
            ._interpolate()  # pylint: disable=protected-access
            ._intersect_weather()  # pylint: disable=protected-access
            ._performance()  # pylint: disable=protected-access
            ._emissions()  # pylint: disable=protected-access
            ._contrails()  # pylint: disable=protected-access
            ._nonco2()  # pylint: disable=protected-access
            ._gwp()  # pylint: disable=protected-access
        )
