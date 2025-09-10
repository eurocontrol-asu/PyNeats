
from datetime import datetime
import os

from pyneats.steps.weather.weather_store import ZarrPaths
from pyneats.pipeline.fleet import FleetRunnerParams, FleetRunner

# Read recipe inputs
WEATHER_PATH = "/path/to/DWD/files"
TRAJECTORIES_PATH = "/path/to/NM/files"
ZARR_PATH = "/path/to/zarr/files"

met_store  = os.path.join(ZARR_PATH, "met_cache", "icon_met.zarr")
rad_store  = os.path.join(ZARR_PATH, "met_cache", "icon_rad.zarr")
wind_store = os.path.join(ZARR_PATH, "met_cache", "icon_wind.zarr")  # set to None if you don't have it
zarr_read_chunks={"time":1, "level":10, "latitude":256, "longitude":256}

ASOFDATE = datetime(2025, 7, 9, 0, 0, 0)
TIME_OF_DAY = 0
SAMPLE = 10
FORECAST_WINDOW = 36
MODEL_TYPE = "CTFM"

#Instantiate Fleet Object
params = FleetRunnerParams(
    model_type=MODEL_TYPE,
    weather_folder=WEATHER_PATH,      
    trajectory_folder=TRAJECTORIES_PATH,
    forecast_window=FORECAST_WINDOW,
    sample=SAMPLE,
    zarr_paths=ZarrPaths(
        met_store=met_store,
        rad_store=rad_store,
        wind_store=wind_store,           
    ),
    zarr_read_chunks=zarr_read_chunks
)


runner = FleetRunner(ASOFDATE, TIME_OF_DAY, params, njobs=30, flight_chunk=16)
runner.eval()

# Print results for the Fleet sample
for elem in runner.results:
    
    print('*************')
    print(elem)
