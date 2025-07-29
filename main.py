
from pyneats.weather import DWDFactory, WeatherFactoryParams
from pyneats.fleet import NeatsFleet, NeatsFleetParams

from datetime import datetime


TRAJECTORIES_PATH = ""
WEATHER_PATH = ""

ASOFDATE = datetime(2025, 7, 9, 0, 0, 0)
TIME_OF_DAY = 0
SAMPLE = 10
FORECAST_WINDOW = 6


global_fleet = NeatsFleet(asofdate=ASOFDATE, 
                          timeofday=TIME_OF_DAY,
                          params=NeatsFleetParams('CTFM', WEATHER_PATH, TRAJECTORIES_PATH, FORECAST_WINDOW),
                          sample=SAMPLE)


