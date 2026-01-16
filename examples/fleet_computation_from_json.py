import os

from pyneats.runners.fleet import FleetRunner, FleetRunnerParams
from pyneats.steps.weather.weather_store import ZarrPaths

# Read recipe inputs

ZARR_PATH = "/path/to/zarr/files"
met_store = os.path.join(ZARR_PATH, "met_cache", "icon_met.zarr")
rad_store = os.path.join(ZARR_PATH, "met_cache", "icon_rad.zarr")
wind_store = os.path.join(ZARR_PATH, "met_cache", "icon_wind.zarr")
zarr_paths = ZarrPaths(met_store=met_store, rad_store=rad_store, wind_store=wind_store)

JSON_FILEPATH = "/path/to/trajectories.json"

BADA_PATH = "/path/to/bada/files/"

n_jobs = 30
flight_chunk = 16

# Instantiate Fleet Object
params = FleetRunnerParams(
    trajectory_json_filepath=JSON_FILEPATH,
    zarr_paths=zarr_paths,
    njobs=n_jobs,
    bada_path=BADA_PATH,
)

runner = FleetRunner(params)
runner.eval()

# Print results for the Fleet sample
print("*************")
print("************* Fleet Meta-data **************")
print(runner.results["fleet_meta_data"])
print("*************")


for elem in runner.results["flight_results"]:
    print("*************")
    print(elem)
