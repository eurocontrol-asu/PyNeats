
from datetime import datetime

from pyneats.pipeline.fleet import FleetRunner, FleetRunnerParams

# Read recipe inputs
WEATHER_PATH = "/path/to/DWD/files"
TRAJECTORIES_PATH = "/path/to/NM/files"


ASOFDATE = datetime(2025, 7, 9, 0, 0, 0)
TIME_OF_DAY = 0
SAMPLE = 10
FORECAST_WINDOW = 6
  

#Instantiate Fleet Object
global_fleet = FleetRunner(asofdate=ASOFDATE, 
                          timeofday=TIME_OF_DAY,
                          params=FleetRunnerParams(model_type='CTFM',
                                                   weather_folder=WEATHER_PATH,
                                                   trajectory_folder=TRAJECTORIES_PATH,
                                                   forecast_window=FORECAST_WINDOW,
                                                   sample=SAMPLE)
                         )


global_fleet.eval()

# Print results for the Fleet sample
for elem in global_fleet.results:
    
    print('*************')
    print(elem)
