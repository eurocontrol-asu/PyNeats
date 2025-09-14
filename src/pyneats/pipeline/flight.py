import logging
from typing import Final
import pandas as pd
from typing_extensions import Self

from pycontrails import Flight
from pycontrails.core.met import MetDataset

from pyneats.steps.climate import (
    ClimateImpactModelType,
    ClimateImpactModel,
    ClimateImpactStepError,
    ContrailsModelType,
    ContrailsModel,
    ContrailsParams,
    ContrailsStepError,
    FlightWithContrailsImpact,
    COCIPModel,
    FlightWithClimateImpact,
    NonCO2ModelType,
    NonCO2Params,
    NonCO2Model,
    FlightWithNonCO2Impact,
    ClimateStepError,
)

from pyneats.steps.interpolator import (
    TrajectoryInterpolator,
    InterpolatorType,
    InterpolationStepError,
)

from pyneats.steps.trajectory import (
    TrajectoryParserType,
    TrajectoryParser,
    FlightParsingError,
    Flight4D,
)

from pyneats.steps.performance import (
    FlightWithPerformance,
    PerformanceModelType,
    PerformanceStepError,
    PerformanceModel,
)

from pyneats.steps.emissions import (
    EmissionModel,
    EmissionModelType,
    EmissionsStepError,
    FlightWithEmissions,
)

from pyneats.steps.weather import (
    WeatherProviderProtocol,
    WeatherStepError,
    FlightWithWeather,
)

from pyneats.core.meta import extract_flight_meta

logger = logging.getLogger(__name__)

#Default Trajectory in NEATS are NM's FTFM, RTFM and CTFM
DEFAULT_TRAJECTORY_PARSER: Final[TrajectoryParser] = TrajectoryParserType.NM.get()
#Default Trajectory in NEATS is Interpolator/reconstructor from PyContrails
DEFAULT_INTERPOLATOR: Final[TrajectoryInterpolator] = InterpolatorType.PYCONTRAILS.get()
# Default Performance Model is BADA as implemented via pyBADA
DEFAULT_PERFORMANCE_MODEL: Final[PerformanceModel] = PerformanceModelType.BADA.get()
#Default Emission Model is BFFM2 - T4/T2 as implemented in PyContrails
DEFAULT_EMISSION_MODEL: Final[EmissionModel] = EmissionModelType.PYCONTRAILS.get()
# PyContrail's COCIP used for contrail modelling
DEFAULT_CONTRAILS_MODEL_TYPE: Final[ContrailsModelType] = ContrailsModelType.COCIP
# ACCFs  used for other non-co2 species
DEFAULT_NON_CO2_MODEL_TYPE: Final[NonCO2ModelType] = NonCO2ModelType.ACCF
# Default climate impact : GWP
DEFAULT_CLIMAT_IMPACT: Final[ClimateImpactModel]= ClimateImpactModelType.GWP.get()


class FlightRunner:
    """
    Parses, interpolates, and holds flight trajectory with met data.
    """

    # Explicit attribute types for static analysis
    _source: pd.DataFrame | None

    # Defaults (unchanged)
    default_trajectory_parser: TrajectoryParser = DEFAULT_TRAJECTORY_PARSER
    default_interpolator: TrajectoryInterpolator = DEFAULT_INTERPOLATOR
    default_performance: PerformanceModel = DEFAULT_PERFORMANCE_MODEL
    default_emission: EmissionModel = DEFAULT_EMISSION_MODEL
    default_contrails_model_type: ContrailsModelType = DEFAULT_CONTRAILS_MODEL_TYPE
    default_non_co2_model_type : NonCO2ModelType = DEFAULT_NON_CO2_MODEL_TYPE
    default_climate_impact: ClimateImpactModel = DEFAULT_CLIMAT_IMPACT
    

    def __init__(
        self,
        weather: WeatherProviderProtocol,
        source: pd.DataFrame | None = None,
        parser: TrajectoryParser | None = None,
        interpolator: TrajectoryInterpolator | None = None,
        performance: PerformanceModel | None = None,
        emission: EmissionModel | None = None,
        contrails_model: ContrailsModel | None = None,
        non_co2_model: NonCO2Model | None = None,
        climate_impact: ClimateImpactModel | None = None
        

    ) -> None:
        # initialize backing field before using the property
        self._source = None
        self.source = source

        self.weather = weather

        self.parser = parser or self.default_trajectory_parser
        self.interpolator = interpolator or self.default_interpolator
        self.performance = performance or self.default_performance
        self.emission = emission or self.default_emission
        self.climate_impact = climate_impact or self.default_climate_impact

        self.contrails_model = contrails_model or COCIPModel(
            params=ContrailsParams(
                met=self.weather.met(),
                rad=self.weather.rad(),
            )
        )

        '''
        self.non_co2_model = non_co2_model or self.default_non_co2_model_type.get(
            params=NonCO2Params(
                met=self.weather.met(),
                surface=self.weather.rad(),
                )
        )
        '''

        # Pipeline state
        self.parsed_flight: Flight4D | None = None
        self.interpolated_flight: Flight4D | None = None
        self.flight_with_weather: FlightWithWeather | None = None
        self.flight_with_performance: FlightWithPerformance | None = None
        self.flight_with_emissions: FlightWithEmissions | None = None
        self.flight_with_contrails: Flight | None = None
        self.flight_with_climate_impact: Flight | None = None
        self.flight_with_nonco2: FlightWithNonCO2Impact | None = None
        self.current: Flight | None = None

        # Cached met/rad datasets after downselection for this flight
        self._ds_met : MetDataset | None = None
        self._ds_rad : MetDataset | None = None

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

        # Shallow copy is enough for numeric frames, deep copy if unsure
        self._source = value.copy(deep=False)
    
    # Step 1: Parse flights (NM trajectories, ADS-B flights)
    def _parse_flight(self) -> Self:

        if self.source is None:
            logger.error("No source data provided before _parse_flight()")
            raise RuntimeError("Source data must be set before parsing flights.")

        # Run the parser (may raise FlightParsingError)
        try:
            parsed_flight: Flight4D = self.parser(self.source)
        except FlightParsingError:
            # Already logged inside the parser; just propagate with original traceback
            raise
        except Exception as e:
            logger.exception("Unexpected error while parsing trajectory")
            raise RuntimeError(f"Trajectory parsing failed: {e}") from e
        
        # Cache the parsed flight
        self.parsed_flight = parsed_flight
        self.current = self.parsed_flight

        logger.info("Flight parsing completed successfully with %d points", len(self.parsed_flight.data))
        return self
    
    # Step 2: Interpolate/reconstruct trajectory
    def _interpolate(self) -> Self:

        if self.parsed_flight is None:
            logger.error("Missing parsed_flight; did you call _parse_flight() first?")
            raise RuntimeError("_parse_flight() must be called before _interpolate().")

        # Run the interpolator (may raise InterpolationStepError)
        try:
            interpolated_flight: Flight4D = self.interpolator(self.parsed_flight)
        except InterpolationStepError:
            # Already logged inside the interpolator; propagate with original traceback
            raise
        except Exception as e:
            logger.exception("Unexpected error during interpolation")
            raise RuntimeError(f"Interpolation failed: {e}") from e

        self.interpolated_flight = interpolated_flight
        # Advance the pipeline pointer
        self.current = self.interpolated_flight
        # Release previous reference 
        self.parsed_flight = None

        logger.info(
            "Interpolation completed successfully with %d points",
            len(interpolated_flight.data),
        )
        return self
    
    # Step 3: Intersect with weather data
    def _intersect_weather(self) -> Self:

        if self.interpolated_flight is None:
            logger.error("Missing interpolated_flight; did you call _interpolate() first?")
            raise RuntimeError("_interpolate() must be called before _intersect_weather().")

        # Run the weather intersection step (returns a base Flight)
        try:
            wx_flight: FlightWithWeather = self.weather(self.interpolated_flight)
        except WeatherStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during weather intersection")
            raise RuntimeError(f"Weather intersection failed: {e}") from e

        self.flight_with_weather = wx_flight

        # Advance pointer & release previous stage reference
        self.current = self.flight_with_weather
        self.interpolated_flight = None

        # Cache the downsampled met/rad datasets for later use (e.g accfs)
        self._ds_met = self.weather.ds_met()
        self._ds_rad = self.weather.ds_rad()

        logger.info("Weather intersection completed successfully with %d points",
                    len(wx_flight.data))
        return self
    
    # Step 4: Run Performance model
    def _performance(self) -> Self:
        perf = self.performance

        if self.flight_with_weather is None:
            logger.error("Missing flight_with_weather; did you call _intersect_weather() first?")
            raise RuntimeError("_intersect_weather() must be called before _performance().")

        try:
            enriched: FlightWithPerformance = perf(self.flight_with_weather)
        except PerformanceStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during performance evaluation")
            raise RuntimeError(f"Performance evaluation failed: {e}") from e

        try:
            self.flight_with_performance = FlightWithPerformance.from_flight(enriched)
        except KeyError as e:
            logger.error("Performance output missing required columns: %s", e)
            raise RuntimeError(f"Performance validation failed: {e}") from e

        self.current = self.flight_with_performance
        self.flight_with_weather = None
        logger.info("Performance step completed successfully")
        return self

    # Step 5: Run Emission model
    def _emissions(self) -> Self:

        if self.flight_with_performance is None:
            logger.error("Missing flight_with_performance; did you call performance() first?")
            raise RuntimeError("performance() must be called before _emissions().")

        try:
            enriched: Flight = self.emission(self.flight_with_performance)
        except EmissionsStepError:
            # Already logged inside the emissions step; just propagate.
            raise
        except Exception as e:
            logger.exception("Unexpected error during emissions backend evaluation")
            raise RuntimeError(f"Emissions evaluation failed: {e}") from e

        # Get the typed, zero-copy view
        self.flight_with_emissions = FlightWithEmissions.from_flight(enriched)
        self.current = self.flight_with_emissions
        self.flight_with_performance = None

        logger.info("Emissions step completed successfully")
        return self
    
    # Step 6: Compute Contrails EF
    def _contrails(self) -> Self:

        if self.flight_with_emissions is None:
            logger.error("Missing flight_with_emissions; did you call _emissions() first?")
            raise RuntimeError("_emissions() must be called before _contrails().")

        # Run the contrails step (COCIP). It returns a base Flight.
        try:
            f_out: Flight = self.contrails_model(self.flight_with_emissions)
        except ContrailsStepError:
            # Already logged inside the model; keep original traceback.
            raise
        except Exception as e:
            logger.exception("Unexpected error during contrails (COCIP) evaluation")
            raise RuntimeError(f"Contrails evaluation failed: {e}") from e

        # Zero-copy validated view for ergonomic access (e.g., .ef property)
        self.flight_with_contrails = FlightWithContrailsImpact.from_flight(f_out)

        # Advance pointer & release previous stage
        self.current = self.flight_with_contrails
        self.flight_with_emissions = None

        logger.info("Contrails step completed successfully")
        return self
    
    # Step 7: Compute non-CO₂ (ACCF)
    def _nonco2(self) -> Self:

        # Prefer the most recent enriched flight. ACCF needs emissions + weather;
        # both are still present in the current Flight even after contrails.
        flight_in: Flight | None = (
            self.current
            or self.flight_with_contrails
            or self.flight_with_emissions
        )

        if flight_in is None:
            logger.error("No flight available; run _emissions() (and optionally _contrails()) first.")
            raise RuntimeError("_emissions() must be called before _nonco2().")

        #lon_buf = (0.0, 0.0)    # deg
        #lat_buf = (0.0, 0.0)    # deg
        #time_buf = (np.timedelta64(0, "h"), np.timedelta64(0, "h"))
        #level_buf = (0.0, 0.0)  # hPa

        # Downselect from the provider to shrink the graph
        #ds_met = flight_in.downselect_met(self.weather.met(),  longitude_buffer=lon_buf,
        #                                latitude_buffer=lat_buf, time_buffer=time_buf, level_buffer=level_buf)
        #ds_sfc = flight_in.downselect_met(self.weather.rad(),  longitude_buffer=lon_buf,
        #                                latitude_buffer=lat_buf, time_buffer=time_buf, level_buffer=level_buf)

        #met_sel  = MetDataset(ds_met)
        #surf_sel = MetDataset(ds_sfc)


        self.non_co2_model = self.default_non_co2_model_type.get(
            params=NonCO2Params(
                met=self._ds_met,
                surface=self._ds_rad,
                )
        )

        try:
            f_out: Flight = self.non_co2_model(flight_in)
        except ClimateStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during non-CO₂ (ACCF) evaluation")
            raise RuntimeError(f"Non-CO₂ evaluation failed: {e}") from e

        # Zero-copy validated view
        self.flight_with_nonco2 = FlightWithNonCO2Impact.from_flight(f_out)

        # Advance pointer; keep contrails if you want both available.
        self.current = self.flight_with_nonco2
        # Optionally free memory:
        # self.flight_with_contrails = None
        # self.flight_with_emissions = None

        logger.info("Non-CO₂ (ACCF) step completed successfully")
        return self

    # Step 8: Compute Climate Impact (GWP)
    def _gwp(self) -> Self:
        if self.flight_with_nonco2 is None:
            logger.error("Missing flight_with_contrails; did you call _contrails() first?")
            raise RuntimeError("_contrails() must be called before _gwp().")

        try:
            out = self.climate_impact(self.flight_with_nonco2)  # returns FlightWithClimateImpact
        except ClimateImpactStepError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during climate impact (GWP) evaluation")
            raise RuntimeError(f"Climate impact evaluation failed: {e}") from e

        # keep the typed, zero-copy view
        self.flight_with_climate_impact = FlightWithClimateImpact.from_flight(out)
        self.current = self.flight_with_climate_impact

        logger.info("Climate impact (GWP) step completed successfully")
        return self

    def get_meta_data(self) -> dict[str, object]:
        if self.current is None:
            raise RuntimeError("No current flight available to extract metadata.")
        return dict(extract_flight_meta(self.current))
    
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
            self._parse_flight()     # pylint: disable=protected-access
            ._interpolate()          # pylint: disable=protected-access
            ._intersect_weather()    # pylint: disable=protected-access
            ._performance()          # pylint: disable=protected-access
            ._emissions()            # pylint: disable=protected-access
            ._contrails()            # pylint: disable=protected-access
            ._nonco2()               # pylint: disable=protected-access
            ._gwp()                  # pylint: disable=protected-access
        )
        