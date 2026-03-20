"""
OpenAirClim Climate Function Module.

Implements the Method D climate function based on OpenAirClim for computing non-CO₂
aviation climate impacts including ozone (O₃), methane (CH₄), water vapor (H₂O),
and contrail cirrus effects across multiple time horizons (20, 50, 100 years).

The module wraps the open-airclim library to compute Absolute Global Warming Potential
(AGWP) metrics for flight emissions, using a grid-based inventory approach with
temporary workspace management.

See Also
--------
open_airclim : https://github.com/openclimatefix/open-airclim
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from importlib.resources import files

import numpy as np
import openairclim as oac
import toml
import xarray as xr
from pycontrails import Flight

from pyneats.core.neats_default_parameters import OPEN_AIRCLIM_COMPUTATION_HORIZON
from pyneats.core.neats_default_parameters import OPEN_AIRCLIM_GRID_RES
from pyneats.core.neats_default_parameters import OPEN_AIRCLIM_LEVELS
from pyneats.core.physics import METRICS_HORIZONS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import NonCO2Model
from pyneats.steps.climate_functions.protocol import OpenAirClimStepError
from pyneats.steps.climate_functions.views import FlightWithGlobalAGWP
from pyneats.steps.emissions.views import FlightWithEmissions


@dataclass(frozen=True)
class OpenAirClimParams(ClimateParams):
    tmp_base_dir_path: str = ""
    repo_dir_path: str = str(files("pyneats.resources").joinpath("repository"))
    base_toml_path: str = str(files("pyneats.resources").joinpath("openairclim.toml"))
    base_inventory_path: str | None = str(
        files("pyneats.resources").joinpath("ELK_aviation_2025_res5deg_flat.nc")
    )
    grid_res: float = OPEN_AIRCLIM_GRID_RES
    oac_levels: tuple[int, ...] = OPEN_AIRCLIM_LEVELS
    computation_horizon: int = OPEN_AIRCLIM_COMPUTATION_HORIZON
    horizons: tuple[int, ...] = METRICS_HORIZONS


def _create_worker_toml(
    base_toml_path,
    input_dir_name,
    output_dir_name,
    inventory_filename,
    horizon,
    year,
    base_inventory_filename=None,
):
    """
    Generate OpenAirClim configuration file for a computation worker.
    """
    with open(base_toml_path) as f:
        config = toml.load(f)

    # Simple local paths (because CWD will be the sandbox)
    config["inventories"]["dir"] = f"{input_dir_name}/"
    config["inventories"]["files"] = [inventory_filename]

    if base_inventory_filename:
        config["inventories"]["rel_to_base"] = True
        config["inventories"]["base"] = {
            "dir": f"{input_dir_name}/",
            "files": [base_inventory_filename],
        }
    else:
        config["inventories"]["rel_to_base"] = False
        if "base" in config["inventories"]:
            del config["inventories"]["base"]

    config["output"]["dir"] = f"{output_dir_name}/"
    config["output"]["name"] = "worker_result"

    # Point to the LOCAL symlink we will create
    config["background"]["dir"] = "repository/"
    config["responses"]["dir"] = "repository/"

    config["time"]["range"] = [year, year + horizon + 1, 1]

    # Cleanup time settings
    if "file" in config["time"]:
        del config["time"]["file"]

    # Save to inputs folder
    toml_path = os.path.join(input_dir_name, "worker_config.toml")
    with open(toml_path, "w") as f:
        toml.dump(config, f)

    return toml_path


def _save_inventory(ds, filepath):
    """Save emissions inventory dataset to NetCDF file."""
    ds.to_netcdf(
        filepath,
        engine="netcdf4",
        encoding={v: {"zlib": True, "complevel": 5} for v in ds.data_vars},
    )


@register(NonCO2Model, "open_airclim")
class OpenAirClimModel(
    BaseStep[
        FlightWithEmissions,
        FlightWithGlobalAGWP,
        OpenAirClimParams,
    ]
):
    default_params = OpenAirClimParams

    def _flight_to_inventory(self, flight: Flight) -> xr.Dataset:
        grid_res = self.params.grid_res
        df = flight.to_dataframe()

        df["nox"] = df["nox"].fillna(0)
        df["co2"] = df["co2"].fillna(0)
        df["h2o"] = df["h2o"].fillna(0)
        df["pressure_hpa"] = df["air_pressure"] / 100.0
        df["distance_km"] = df["segment_length"] / 1000.0

        df["lat_bin"] = np.floor(df["latitude"] / grid_res) * grid_res + (grid_res / 2)
        df["lon_bin"] = np.floor(df["longitude"] / grid_res) * grid_res + (grid_res / 2)

        def get_nearest_level(p):
            levels_arr = np.asarray(self.params.oac_levels)
            diff = np.abs(p.values[:, None] - levels_arr[None, :])
            indices = np.argmin(diff, axis=1)
            return levels_arr[indices]

        df["plev_bin"] = get_nearest_level(df["pressure_hpa"])

        grouped = (
            df.groupby(["lat_bin", "lon_bin", "plev_bin"])
            .agg(
                {
                    "fuel_burn": "sum",
                    "nox": "sum",
                    "co2": "sum",
                    "h2o": "sum",
                    "distance_km": "sum",
                }
            )
            .reset_index()
            .rename(
                columns={
                    "lat_bin": "lat",
                    "lon_bin": "lon",
                    "plev_bin": "plev",
                    "fuel_burn": "fuel",
                    "nox": "NOx",
                    "co2": "CO2",
                    "h2o": "H2O",
                    "distance_km": "distance",
                }
            )
        )

        ds = xr.Dataset.from_dataframe(grouped)
        year = df.iloc[0].time.year
        ds.attrs["Inventory_Year"] = year
        ds["plev"].attrs["units"] = "hPa"
        ds["lat"].attrs["units"] = "degrees_north"
        ds["lon"].attrs["units"] = "degrees_east"
        ds["fuel"].attrs["units"] = "kg"
        ds["NOx"].attrs["units"] = "kg"
        ds["CO2"].attrs["units"] = "kg"
        ds["H2O"].attrs["units"] = "kg"
        ds["distance"].attrs["units"] = "km"

        return ds

    def run(self, flight: FlightWithEmissions) -> FlightWithGlobalAGWP:
        with tempfile.TemporaryDirectory(dir=self.params.tmp_base_dir_path) as temp_dir:
            # 1. SETUP SYMLINK FOR REPOSITORY (Must be done before chdir if using absolute source paths)
            local_repo_link = os.path.join(temp_dir, "repository")
            if not os.path.exists(local_repo_link):
                os.symlink(self.params.repo_dir_path, local_repo_link)

            # 2. CHANGE CWD TO SANDBOX
            original_cwd = os.getcwd()
            os.chdir(temp_dir)

            try:
                # 3. Create Subfolders
                os.makedirs("inputs", exist_ok=True)
                os.makedirs("outputs", exist_ok=True)

                # 4. Symlink Base Inventory
                base_inv_filename = None
                if self.params.base_inventory_path and os.path.exists(
                    self.params.base_inventory_path
                ):
                    base_inv_filename = os.path.basename(
                        self.params.base_inventory_path
                    )
                    os.symlink(
                        self.params.base_inventory_path,
                        os.path.join("inputs", base_inv_filename),
                    )

                # 5. Compute segment length
                flight["segment_length"] = flight.segment_length()

                # 6. Generate Inventory
                inv_path = "inputs/emissions.nc"
                ds = self._flight_to_inventory(flight)
                _save_inventory(ds, inv_path)

                # 7. Generate TOML
                horizon = self.params.computation_horizon
                year = ds.attrs["Inventory_Year"]
                toml_rel_path = _create_worker_toml(
                    self.params.base_toml_path,
                    "inputs",
                    "outputs",
                    "emissions.nc",
                    horizon,
                    year,
                    base_inv_filename,
                )

                # 8. RUN OPENAIRCLIM
                oac.run(toml_rel_path)

                # 9. Harvest Results
                result_nc = "outputs/worker_result_metrics.nc"
                if not os.path.exists(result_nc):
                    raise OpenAirClimStepError(
                        "ACCF requires both 'met' and 'surface' datasets."
                    )

                with xr.load_dataset(result_nc) as metrics_ds:
                    results = {}
                    for h in self.params.horizons:
                        var_name = f"AGWP_{h}_2025"
                        if var_name in metrics_ds:
                            raw_results = metrics_ds[var_name]
                            results[f"AGWP_{h}"] = {
                                str(k): float(v)
                                for k, v in zip(
                                    raw_results["species"].values, raw_results.values
                                )
                            }

                    # Assign Attributes
                    for h in [20, 50, 100]:
                        flight.attrs[f"AGWP_{h}_O3"] = results[f"AGWP_{h}"]["O3"]
                        flight.attrs[f"AGWP_{h}_CH4"] = (
                            results[f"AGWP_{h}"]["CH4"] + results[f"AGWP_{h}"]["PMO"]
                        )
                        flight.attrs[f"AGWP_{h}_H2O"] = results[f"AGWP_{h}"]["H2O"]
                        flight.attrs[f"AGWP_{h}_CONT"] = results[f"AGWP_{h}"]["cont"]

            except Exception as e:
                self.logger.exception("Open_AirClim evaluation failed")
                raise OpenAirClimStepError(
                    f"Open_AirClim evaluation failed: {e}"
                ) from e

            finally:
                # 10. ALWAYS restore original directory
                os.chdir(original_cwd)

        return FlightWithGlobalAGWP.from_flight(flight)
