from __future__ import annotations

from importlib.resources import files
from dataclasses import dataclass
import tempfile
import os
import numpy as np
import toml
import xarray as xr

import openairclim as oac
from pycontrails import Flight

from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import OpenAirClimStepError, NonCO2Model
from pyneats.steps.climate_functions.views import FlightWithGlobalAGWP
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.core.physics import METRICS_HORIZONS
from pyneats.core.neats_default_parameters import (
    OPEN_AIRCLIM_LEVELS,
    OPEN_AIRCLIM_GRID_RES,
    OPEN_AIRCLIM_COMPUTATION_HORIZON,
)

@dataclass(frozen=True)
class OpenAirClimParams(ClimateParams):
    """Parameters for the Flight based OpenAirClim model.
    
    
    """
    tmp_base_dir_path: str = ""
    repo_dir_path: str = str(files("pyneats.resources").joinpath("repository"))
    base_toml_path: str = str(files("pyneats.resources").joinpath("openairclim.toml"))
    grid_res: float = OPEN_AIRCLIM_GRID_RES
    oac_levels: tuple[int, ...] = OPEN_AIRCLIM_LEVELS
    computation_horizon: int = OPEN_AIRCLIM_COMPUTATION_HORIZON
    horizons: tuple[int, ...] = METRICS_HORIZONS


def _create_worker_toml(base_toml_path, input_dir_name, output_dir_name, inventory_filename, horizon, year):
    """
    
    """
    with open(base_toml_path, 'r') as f:
        config = toml.load(f)

    # Simple local paths (because CWD will be the sandbox)
    config['inventories']['dir'] = f"{input_dir_name}/"
    config['inventories']['files'] = [inventory_filename]

    config['output']['dir'] = f"{output_dir_name}/"
    config['output']['name'] = "worker_result"
    
    # Point to the LOCAL symlink we will create
    config['background']['dir'] = "repository/"
    config['responses']['dir']  = "repository/"
    

    config['time']['range'] = [year, year + horizon +1 , 1]
    
    # Cleanup time settings
    if 'file' in config['time']:
        del config['time']['file']

    # Save to inputs folder
    toml_path = os.path.join(input_dir_name, "worker_config.toml")
    print("toml_path : ", toml_path)
    with open(toml_path, 'w') as f:
        toml.dump(config, f)
        
        
    return toml_path # Return relative path "inputs/worker_config.toml"

def _save_inventory(ds, filepath):
        # Calculate the absolute path based on the current working directory
        abs_path = os.path.abspath(filepath)
        
        print(f"DEBUG: Saving inventory to: {abs_path}")
        
        ds.to_netcdf(
            filepath, 
            engine="netcdf4", 
            encoding={v: {'zlib': True, 'complevel': 5} for v in ds.data_vars}
        )


@register(NonCO2Model, "open_airclim") 
class OpenAirClimModel(
    BaseStep[
        FlightWithEmissions,
        FlightWithGlobalAGWP,
        OpenAirClimParams,
    ]
):
    """ implementation of the Method D climate function based on OpenAirClim
    """

    default_params = OpenAirClimParams


    def _flight_to_inventory(self,
                              flight: Flight):
        """
        
        """

        grid_res = self.default_params.grid_res
        df = flight.to_dataframe()

        df['nox'] = df['nox'].fillna(0)
        df['co2'] = df['co2'].fillna(0)
        df['h2o'] = df['h2o'].fillna(0)
        df['pressure_hpa'] = df['air_pressure'] / 100.0
        df['distance_km'] = df['segment_length'] / 1000.0

        df['lat_bin'] = np.floor(df['latitude'] / grid_res) * grid_res + (grid_res / 2)
        df['lon_bin'] = np.floor(df['longitude'] / grid_res) * grid_res + (grid_res / 2)
        
        
        def get_nearest_level(p):
            # Ensure levels are a numpy array for math and multi-element indexing
            levels_arr = np.asarray(self.default_params.oac_levels)
            
            # Calculate absolute differences via broadcasting
            diff = np.abs(p.values[:, None] - levels_arr[None, :])
            
            # Find the index of the minimum difference for each row
            indices = np.argmin(diff, axis=1)
            
            return levels_arr[indices]

        df['plev_bin'] = get_nearest_level(df['pressure_hpa'])

        grouped = df.groupby(['lat_bin', 'lon_bin', 'plev_bin']).agg({
            'fuel_burn': 'sum', 'nox': 'sum', 'co2': 'sum', 
            'h2o': 'sum', 'distance_km': 'sum'
        }).reset_index().rename(columns={
            'lat_bin': 'lat', 'lon_bin': 'lon', 'plev_bin': 'plev',
            'fuel_burn': 'fuel', 'nox': 'NOx', 'co2': 'CO2',
            'h2o': 'H2O', 'distance_km': 'distance'
        })

        ds = xr.Dataset.from_dataframe(grouped)
        year = df.iloc[0].time.year
        ds.attrs['Inventory_Year'] = year
        ds['plev'].attrs['units'] = 'hPa'
        ds['lat'].attrs['units'] = 'degrees_north'
        ds['lon'].attrs['units'] = 'degrees_east'
        ds['fuel'].attrs['units'] = 'kg'
        ds['NOx'].attrs['units'] = 'kg'
        ds['CO2'].attrs['units'] = 'kg'
        ds['H2O'].attrs['units'] = 'kg'
        ds['distance'].attrs['units'] = 'km'

        return ds

    def run(self, flight: FlightWithEmissions) -> FlightWithGlobalAGWP:


        # 1. Create Sandbox
        with tempfile.TemporaryDirectory(dir=self.default_params.tmp_base_dir_path) as temp_dir:

            # 2. SETUP SYMLINK FOR REPOSITORY
            # shared repository appears inside the sandbox
            local_repo_link = os.path.join(temp_dir, "repository")
            if not os.path.exists(local_repo_link):
                os.symlink(self.default_params.repo_dir_path, local_repo_link)
            
            # 3. CHANGE CWD TO SANDBOX
            original_cwd = os.getcwd()
            os.chdir(temp_dir)

            try:
                # 4. Create Subfolders
                os.makedirs("inputs", exist_ok=True)
                os.makedirs("outputs", exist_ok=True)

                # 5. Compute segment length which is needed for openairclim
                flight['segment_length'] = flight.segment_length()

                # 6. Generate Inventory
                inv_path = "inputs/emissions.nc"
                ds = self._flight_to_inventory(flight)
                _save_inventory(ds, inv_path)

                # 7. Generate TOML
                #  pass simple directory names since already inside temp_dir
                horizon = self.default_params.computation_horizon
                year = ds.attrs['Inventory_Year']
                toml_rel_path = _create_worker_toml(
                    self.default_params.base_toml_path, 
                    "inputs", 
                    "outputs", 
                    "emissions.nc",
                    horizon,
                    year,
                )

                # 8. RUN OPENAIRCLIM
                # sees "repository/" locally via symbolic link
                oac.run(toml_rel_path)

                # 9. Harvest Results
                result_nc = "outputs/worker_result_metrics.nc"
                if not os.path.exists(result_nc):
                    raise OpenAirClimStepError("ACCF requires both 'met' and 'surface' datasets.")

                with xr.load_dataset(result_nc) as metrics_ds:
                
                    # Define the horizons you want to extract
                    results = {}

                    for h in self.default_params.horizons:
                        var_name = f'AGWP_{h}_2025'

                        # Ensure the variable exists in the dataset to avoid KeyErrors
                        if var_name in metrics_ds:
                            raw_results = metrics_ds[var_name]

                            # Create a sub-dictionary for this horizon
                            results[f'AGWP_{h}'] = {
                                str(k): float(v)
                                for k, v in zip(raw_results["species"].values, raw_results.values)
                            }

                    flight.attrs["AGWP_20_O3"] = results['AGWP_20']['O3']
                    flight.attrs["AGWP_20_CH4"] = results['AGWP_20']['CH4'] + results['AGWP_20']['PMO']
                    flight.attrs["AGWP_20_H2O"] = results['AGWP_20']['H2O']
                    flight.attrs["AGWP_20_CONT"] = results['AGWP_20']['cont']

                    flight.attrs["AGWP_50_O3"] = results['AGWP_50']['O3']
                    flight.attrs["AGWP_50_CH4"] = results['AGWP_50']['CH4'] + results['AGWP_50']['PMO']
                    flight.attrs["AGWP_50_H2O"] = results['AGWP_50']['H2O']
                    flight.attrs["AGWP_50_CONT"] = results['AGWP_50']['cont']

                    flight.attrs["AGWP_100_O3"] = results['AGWP_100']['O3']
                    flight.attrs["AGWP_100_CH4"] = results['AGWP_100']['CH4'] + results['AGWP_100']['PMO']
                    flight.attrs["AGWP_100_H2O"] = results['AGWP_100']['H2O']
                    flight.attrs["AGWP_100_CONT"] = results['AGWP_100']['cont']

                    

            except Exception as e:
                self.logger.exception("Open_AirClim evaluation failed")
                raise OpenAirClimStepError(f"Open_AirClim evaluation failed: {e}") from e
            
            finally:
                # go back to original directory 
                os.chdir(original_cwd)

        return FlightWithGlobalAGWP.from_flight(flight)
    