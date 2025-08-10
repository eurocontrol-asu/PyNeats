
from pyneats.weather import DWDFactory, WeatherFactoryParams
from pyneats.fleet import NeatsFleet, FleetRunner

from datetime import datetime


TRAJECTORIES_PATH = 'PATH/TO/TRAJECTORIES/FOLDER'
WEATHER_PATH = 'PATH/TO/TRAJECTORIES/FOLDER'

ASOFDATE = datetime(2025, 7, 9, 0, 0, 0)
TIME_OF_DAY = 0
SAMPLE = 10
FORECAST_WINDOW = 6


#Instantiate Fleet Object
global_fleet = NeatsFleet(asofdate=ASOFDATE, 
                          timeofday=TIME_OF_DAY,
                          params=FleetRunner('CTFM', WEATHER_PATH, TRAJECTORIES_PATH, FORECAST_WINDOW),
                          sample=SAMPLE)

# Print results for the Fleet sample
for elem in global_fleet.results:
    
    print('*************')
    print(elem)