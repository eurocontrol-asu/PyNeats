from dataclasses import dataclass
from typing import Protocol
import pandas as pd
from enum import Enum

from pycontrails import Flight
from pycontrails.models.emissions import Emissions

class FlightWithEmissions(Flight):
    
    @property
    def nvpm_ei_m(self) -> pd.Series:
        if "nvpm_ei_m" not in self:
            raise AttributeError("Flight has no 'nvpm_ei_m' column")
        return self["nvpm_ei_m"]
    
    
class EmissionModel(Protocol):
    def __call__(self, flight: Flight) -> FlightWithEmissions:
        ...
    
    
class PyContrailsEmissionModel():
    
    def __init__(self):
        
        self.em = Emissions()
        
    
    def __call__(self, flight: Flight) -> FlightWithEmissions:
        
        return self.em.eval(source=flight)
        
        
class EurocontrolEmissionModel():
    
    def __call__(self, flight: Flight) -> FlightWithEmissions:
        # TODO: implement Eurocontrol Emission Model  logic here
        raise NotImplementedError("Eurocontrol Emission Model not yet implemented")
        
class EmissionModelType(Enum):
    """
    Enum that maps parser type descriptors to the actual class 
    """
    
    PyContrails = PyContrailsEmissionModel
    Eurocontrol = EurocontrolEmissionModel

    def get(self) -> EmissionModel:
        return self.value()