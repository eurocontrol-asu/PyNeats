from pycontrails.models.humidity_scaling import ConstantHumidityScaling
from pycontrails import Flight

import logging
from typing import Final, Dict, Any
import numpy as np
import pandas as pd
from typing_extensions import Self

from pyneats.interpolator import TrajectoryInterpolator, InterpolatorType
from pyneats.trajectory import TrajectoryParserType, TrajectoryParser, FlightParsingError, ParsedFlight
from pyneats.performance import FlightPerformanceModel, PerformanceModelType
from pyneats.emissions import EmissionModel, EmissionModelType, EmissionsStepError, FlightWithEmissions
from pyneats.climate import ContrailsModelType, ContrailsModel, ContrailsParams
from pyneats.weather import  WeatherProviderProtocol

logger = logging.getLogger(__name__)

#Default Trajectory in NEATS is Interpolator/reconstructor from PyContrails (cf class PyContrailsInterpolator) 
DEFAULT_INTERPOLATOR: Final[TrajectoryInterpolator] = InterpolatorType.PYCONTRAILS.get()
    
#Default Trajectory in NEATS are NM's FTFM, RTFM and CTFM
DEFAULT_TRAJECTORY_PARSER: Final[TrajectoryParser] = TrajectoryParserType.NM.get()
    
#Default Performance Model is BADA as implemented in PyBADA
DEFAULT_PERFORMANCE_MODEL: Final[FlightPerformanceModel] = PerformanceModelType.BADA.get()
    
#Default Performance Model is T4/T2 as implemented in PyContrails
DEFAULT_EMISSION_MODEL: Final[EmissionModel] = EmissionModelType.PYCONTRAILS.get()

DEFAULT_CONTRAILS_PARAMS = {
    "dt_integration": np.timedelta64(1, "m"),
    "humidity_scaling": ConstantHumidityScaling(rhi_adj=0.99),
    }
DEFAULT_CONTRAILS_MODEL_TYPE: Final[ContrailsModelType] = ContrailsModelType.COCIP

class NeatsFlight():
    """
    Parses, interpolates, and holds flight trajectory with met data.
    """
    
    default_trajectory_parser: TrajectoryParser = DEFAULT_TRAJECTORY_PARSER
    default_interpolator: TrajectoryInterpolator = DEFAULT_INTERPOLATOR
    default_performance: FlightPerformanceModel = DEFAULT_PERFORMANCE_MODEL
    default_emission: EmissionModel = DEFAULT_EMISSION_MODEL
    default_contrails_model_type: ContrailsModelType = DEFAULT_CONTRAILS_MODEL_TYPE
    default_contrails_params: Dict[str,Any] = DEFAULT_CONTRAILS_PARAMS
        
    def __init__(
        self,
        weather: WeatherProviderProtocol,
        source: pd.DataFrame | None = None,
        parser: TrajectoryParser | None = None,
        interpolator: TrajectoryInterpolator | None =  None,
        performance: FlightPerformanceModel | None =  None,
        emission: EmissionModel| None =  None,
        contrails_model: ContrailsModel| None =  None
    ):
        
        self.source = source.copy() if source is not None else None

        self.parser = parser or self.default_trajectory_parser
        self.interpolator = interpolator or self.default_interpolator
        self.weather = weather
        self.performance = performance or self.default_performance
        self.emission = emission or self.default_emission
        self.contrails_model = self.default_contrails_model_type.get(ContrailsParams(met=self.weather.met,
                                                               rad=self.weather.rad,
                                                               contrails_params=self.default_contrails_params))

        # After the main eval() method:
        self.parsed_flight: Flight | None = None
        self.interpolated_flight: Flight | None = None
        self.flight_with_weather: Flight | None = None
        self.flight_with_performance: FlightWithPerformance | None = None
        self.flight_with_emissions: Flight | None = None
        self.flight_with_contrails: FlightWithContrailsImpact | None = None
            
    @property
    def source(self):
        """Get the trajectory dataframe."""
        return self._source

    @source.setter
    def source(self, value):
        """
        Set the trajectory dataframe.
        Make a defensive copy to avoid side effects.
        """
        self._source = value.copy() if value is not None else None
            
    # Step 1: Parse flights (NM trajectories, ADS-B flights)
    def _parse_flight(self) -> Self:

        if self.source is None:
            logger.error("No source data provided before _parse_flight()")
            raise RuntimeError("Source data must be set before parsing flights.")

        # Run the parser (may raise FlightParsingError)
        try:
            base: Flight = self.parser(self.source)
        except FlightParsingError:
            # Already logged inside the parser; just propagate with original traceback
            raise
        except Exception as e:
            logger.exception("Unexpected error while parsing trajectory")
            raise RuntimeError(f"Trajectory parsing failed: {e}") from e
        
        # Optional: validate again (zero-copy). Since the parser already validates,
        self.parsed_flight = ParsedFlight.from_flight(base)

        self.current = self.parsed_flight
        logger.info("Flight parsing completed successfully with %d points", len(base.data))
        return self
    
    # Step 2: Interpolate/reconstruct trajectory
    def _interpolate(self) -> Self:
        
        assert self.parsed_flight is not None, "parse_flight() must be called first"
        self.interpolated_flight = self.interpolator(self.parsed_flight)
        self.current = self.interpolated_flight
        del self.parsed_flight
        return self
    
    # Step 3: Intersect with weather data 
    def _intersect_weather(self) -> Self:
        
        assert self.interpolated_flight is not None, "interpolate() must be called first"
        self.flight_with_weather = self.weather.intersect(self.interpolated_flight)
        self.current = self.flight_with_weather
        del self.interpolated_flight
        return self
    
    # Step 4: Run Performance model 
    def _performance(self) -> Self:
        
        assert self.flight_with_weather is not None, "intersect_weather() must be called first"
        self.flight_with_performance  = self.performance(self.flight_with_weather)
        self.current = self.flight_with_performance
        del self.flight_with_weather
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

        assert self.flight_with_emissions is not None, "emissions() must be called first"
        self.flight_with_contrails  = self.contrails_model(self.flight_with_emissions)
        self.current = self.flight_with_contrails
        del self.flight_with_emissions
        return self
    
    
    def get_meta_data(self):
        
        attrs = self.current.attrs
    
        return {'aircraft_id': attrs['flight_id'],
                'departure_airport': attrs.get('departure_airport'),
                'arrival_airport': attrs.get('arrival_airport'),
                'aircraft_type': attrs.get('aircraft_type'),
                'bada_version' : attrs.get('bada_version'),
                'callsign': attrs.get('callsign'),
                'aobt': attrs['aobt'],
                'pycontrails_version': attrs.get('pycontrails_version')
               }
    
    # Step 7: Compute Climate Impact 
    def _gwp(self) -> Self:
        
        assert self.flight_with_contrails is not None, "contrails() must be called first"
        
        # Constants
        EFFICACY = 0.42
        SURFACE_EARTH = 5.101e14        # Earth's surface area in m²
        SECONDS_PER_YEAR = 31_556_952  # seconds per year

        # AGWP values for CO₂ (from IPCC AR6 Table 7.SM.7) in W·m⁻²·yr·kg⁻¹
        # Converting to J·m⁻²·kg⁻¹ by multiplying by seconds per year
        AGWP = {
            20: 0.0243e-12 * SECONDS_PER_YEAR,
            50: 0.0529e-12 * SECONDS_PER_YEAR,  # Fill in AGWP₅₀ once available from AR6 — often around 0.05e-12
            100: 0.0895e-12 * SECONDS_PER_YEAR,
        }

        HORIZONS = [20, 50, 100]

        # Flight data and metadata
        df = self.flight_with_contrails.to_dataframe()
        attrs = self.flight_with_contrails.attrs

        total_ef = df['ef'].sum()             # total contrail energy forcing (Joules)
        total_co2 = attrs['total_co2']        # total CO₂ emissions (kg)

        result = self.get_meta_data()

        # STEP 1: Compute GWP forcing for contrails
        gwp_contrails = {
            h: total_ef * EFFICACY
            for h in HORIZONS
        }

        # STEP 2: Convert contrail forcing into CO₂‑equivalent (kg CO₂eq)
        co2eq_contrails = {
            h: gwp_contrails[h] / AGWP[h] / SURFACE_EARTH
            for h in HORIZONS
        }

        # STEP 3: Compute CO₂ GWP forcing (emissions multiplied by AGWP factor)
        gwp_co2 = {
            h: total_co2 * AGWP[h] * SURFACE_EARTH
            for h in HORIZONS
        }

        # Format results for output
        climate_impact_contrails = [
            {'horizon': h, 'GWP': gwp_contrails[h], 'CO2eq': co2eq_contrails[h]}
            for h in HORIZONS
        ]

        climate_impact_co2 = [
            {'horizon': h, 'GWP': gwp_co2[h], 'CO2eq': total_co2}
            for h in HORIZONS
        ]

        result['climate_impact'] = [
            {'species': 'CO2', 'value': climate_impact_co2},
            {'species': 'Contrails', 'value': climate_impact_contrails}
        ]

        self.climate_impact = result
        return self
        
    
    def eval(self) -> Self:
       
        # Global Processing Chain
        
            
        return (
            self
            ._parse_flight()
            ._interpolate()
            ._intersect_weather()
            ._performance()
            ._emissions()
            ._contrails()
           # ._gwp()
        )
    