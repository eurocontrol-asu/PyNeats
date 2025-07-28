from enum import Enum
from typing import Protocol
from dataclasses import dataclass
from pycontrails import Flight

from pyneats.parameters import DEFAULT_INTERPOLATION_TIME

@dataclass(frozen=True)
class TrajectoryInterpolationParams:
    """
    Parameters for trajectory interpolation.
    """
    
    interpolation_time: str = DEFAULT_INTERPOLATION_TIME
        
        

class TrajectoryInterpolator(Protocol):
    """
    Callable that takes a Flight and returns an interpolated Flight.
    """
    def __call__(self, flight: Flight) -> Flight:
        ...
        
######################################################################
#                                                                    #
#       ENCAPSULATION OF PYCONTRAILS INTERPOLATOR                    #
#                                                                    #
######################################################################
        
class PyContrailsInterpolator:
    """
    Callable Class that encapsulate the 'great circle distance linear interpolator from PyContrails'
    """
    
    def __init__(self, params: TrajectoryInterpolationParams | None = None):
        self.params = params or TrajectoryInterpolationParams()

    def __call__(self, flight: Flight) -> Flight:
        return flight.resample_and_fill(self.params.interpolation_time)


    
######################################################################
#                                                                    #
#       BADA INTERPOLATOR/TRAJECTORY PREDICTOR  TO BE IMPLEMENTED    #
#                                                                    #
######################################################################


class BADATrajectoryPredictor:
    """
    Callable Class that aims to use BADA physics to 'reconstruct' 4D trajectory after parsing flight phases 
    """
    
    def __init__(self, params: TrajectoryInterpolationParams | None = None):
        self.params = params or TrajectoryInterpolationParams()

    def __call__(self, flight: Flight) -> Flight:
        # TODO: implement BADA prediction logic here
        raise NotImplementedError("BADA trajectory predictor not yet implemented")
        
        
    
class InterpolatorType(Enum):
    """
    Enum that maps interpolator type descriptors to the actual class 
    """
    
    PYCONTRAILS = PyContrailsInterpolator
    BADA = BADATrajectoryPredictor

    def get(self, params: TrajectoryInterpolationParams | None = None) -> TrajectoryInterpolator:
        return self.value(params=params)
