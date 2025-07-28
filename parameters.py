from typing import Final, List


# Default value define in the official technical requirement file
DEFAULT_INTERPOLATION_TIME: Final[str] = "1min"
    
# DEFAULT WINDOW TO APPLY SG FILTER ON TRUE AIR SPEED TO SMOOTH TRAJECTORIES BEFORE PERFORMANCE EVALUATION
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = 7