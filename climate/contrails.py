from dataclasses import dataclass
import pandas as pd
from typing import Protocol, Dict, Any
from enum import Enum

from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.cocip import Cocip

class FlightWithContrailsImpact(Flight):
    
    @property
    def ef(self) -> pd.Series:
        if "ef" not in self:
            raise AttributeError("Flight has no 'ef' column")
        return self["ef"]
    
    
class ContrailsModel(Protocol):
    def __call__(self, flight: Flight) -> FlightWithContrailsImpact:
        ...
    
@dataclass(frozen=True)
class ContrailsParams:
    
    met: MetDataset
    rad: MetDataset
    contrails_params: Dict[str, Any]
    
class COCIP():
    
    def __init__(self,
                 params: ContrailsParams):
        
        self.params = params
        self.cocip_model = Cocip(met=self.params.met, 
                                 rad=self.params.rad, 
                                 params=self.params.contrails_params, 
                                 interpolation_use_indices=True)
        
    
    def __call__(self, flight: Flight) -> FlightWithContrailsImpact:
        
        return self.cocip_model.eval(source=flight)
    
class ContrailsModelType(Enum):
    """
    Enum that maps contrails model type descriptors to the actual class 
    """
    
    COCIP = COCIP

    def get(self, params: ContrailsParams | None = None) -> ContrailsModel:
        return self.value(params=params)