import os
import pandas as pd

from pyneats.steps.weather.weather_store import ZarrPaths
from pyneats.runners.fleet import FleetRunnerParams, FleetRunner


# Read recipe inputs

ZARR_PATH = "/path/to/zarr/files"
met_store  = os.path.join(ZARR_PATH, "met_cache", "icon_met.zarr")
rad_store  = os.path.join(ZARR_PATH, "met_cache", "icon_rad.zarr")
wind_store = os.path.join(ZARR_PATH, "met_cache", "icon_wind.zarr")  # set to None if you don't have it
zarr_paths=ZarrPaths(met_store=met_store,
                     rad_store=rad_store,
                     wind_store=wind_store)


# Required minimal DataFrame schema (per-trajectory DataFrame) with mandatory columns.
#
#   Column name        Type              Description
#   -------------------------------------------------------------
#   latitude           float             Geodetic latitude (deg)
#   longitude          float             Geodetic longitude (deg)
#   time               datetime64[ns]    Timestamp of waypoint
#   altitude           float/int         Altitude (meters)
#   flight_id          str               Unique flight identifier
#   departure_airport  str               ICAO ADEP
#   arrival_airport    str               ICAO ADES
#   model_type         str               Source of trajectory ("NM", etc.)
#   aobt               datetime64[ns]    Actual off-block time
#   aircraft_type      str               ICAO aircraft type
#
# Example row:
#   49.208056 | -2.195556 | 2025-07-09 16:58:00 | 3 | FPO724P | EGJJ | LFPG | NM | 2025-07-09T16:52Z | B737

TRAJECTORY_MINIMAL_SCHEMA = [
    "latitude",
    "longitude",
    "time",
    "altitude",
    "flight_id",
    "departure_airport",
    "arrival_airport",
    "model_type",
    "aobt",
    "aircraft_type",
]

trajectory_dataframe = pd.DataFrame({col: pd.Series(dtype="object") for col in TRAJECTORY_MINIMAL_SCHEMA})

BADA_PATH = "/path/to/bada/files/"

n_jobs = 30
flight_chunk = 16

#Instantiate Fleet Object
params = FleetRunnerParams(    
    trajectory_dataframe = trajectory_dataframe,
    zarr_paths=zarr_paths,
    njobs=n_jobs,
    flight_chunk=flight_chunk,
    bada_path=BADA_PATH,
)

runner = FleetRunner(params)
runner.eval()

# Print results for the Fleet sample
print('*************')
print('************* Fleet Meta-data **************')
print(runner.results['fleet_meta_data'])
print('*************')

for elem in runner.results['flight_results']:
    
    print('*************')
    print(elem)
