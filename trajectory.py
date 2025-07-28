from typing import Protocol, Dict, Any, Final
from dataclasses import dataclass, field
import pandas as pd
from enum import Enum

from pycontrails import Flight

METERS_TO_FEETS: Final[float] = 0.3048

class TrajectoryParser(Protocol):
    """
    Callable that takes a dataframe and returns a Pycontrails Flight object
    """
    def __call__(self, source: pd.DataFrame) -> Flight:
        ...

        
        
######################################################################
#                                                                    #
#       PARSER FOR FTFM, RTFM and CTFM Trajectories from NM          #
#                                                                    #
######################################################################        
        
@dataclass(frozen=True)
class NMTrajectoryParserParams:
    
    """
    Configuration for parsing NM flights from raw DataFrame.
    """
    
    mapping_4d: Dict[str, str] = field(default_factory=lambda: {
        "LAT": "latitude",
        "LON": "longitude",
        "TIME_OVER": "time",
        "FLIGHT_LEVEL": "altitude",
    })
        
    #date_format: str = "%d/%m/%Y %H:%M:%S"
    date_format: str = '%Y-%m-%d %H:%M:%S'
        
    attrs_mapping: Dict[str, str] = field(default_factory=lambda: {
        "flight_id": "AIRCRAFT_ID",
        "aircraft_type": "AIRCRAFT_TYPE_ICAO_ID",
        "callsign": "REGISTRATION",
        "departure_airport": "ADEP",
        "arrival_airport": "ADES",
        "aobt": "time"
    })
        
        
        
class NMTrajectoryParser:
    
    """
    Callable Class that encapsulates the parsing logic of NM Flights
    """
    
    def __init__(self, params: NMTrajectoryParserParams | None = None):
        self.params = params or NMTrajectoryParserParams()

    def __call__(self, source: pd.DataFrame) -> Flight:
        
        df = source.rename(columns=self.params.mapping_4d)

        # Convert FL altitude to feet
        df.altitude = df.altitude * 100 * METERS_TO_FEETS

        # Drop any rows with missing coords or time
        required = list(self.params.mapping_4d.values())
        df = df.dropna(subset=required)

        # Parse time column, sort and drop duplicates
        df["time"] = pd.to_datetime(
            df["time"],
            format=self.params.date_format,
            dayfirst=True,
            errors="coerce",
        ).dropna()

        df = (
            df.sort_values("time")
              .drop_duplicates(subset="time", keep="first")
              .reset_index(drop=True)
        )
        
        # actual mapping towards columns expected by PyContrails
        attrs = {
            key: df[col].iloc[0]
            for key, col in self.params.attrs_mapping.items()
            if col in df.columns
        }

        return Flight(data=df[required], attrs=attrs)

    
    
######################################################################
#                                                                    #
#       OPENSKY PARSER TO BE IMPLEMENTED                             #
#                                                                    #
######################################################################    

class OpenSkyParser:
    """
    Callable Class that parses OpenSky ADS-B data 
    """
    
    def __init__(self):
        ...

    def __call__(self, flight: Flight) -> Flight:
        # TODO: implement OpenSky Parser  logic here
        raise NotImplementedError("OpenSky Parser not yet implemented")
    
    
class TrajectoryParserType(Enum):
    """
    Enum that maps parser type descriptors to the actual class 
    """
    
    NM = NMTrajectoryParser
    OpenSky = OpenSkyParser

    def get(self, params: Any | None = None) -> TrajectoryParser:
        return self.value(params=params)