"""
OpenAirClim Climate Function Module.

Implements the Method D climate function based on OpenAirClim for computing non-CO₂
aviation climate impacts including ozone (O₃), methane (CH₄), water vapor (H₂O),
and contrail cirrus effects across multiple time horizons (20, 50, 100 years).

The module wraps the openairclim library (0.20.0, pinned in pyproject.toml) to
compute Absolute Global Warming Potential (AGWP) metrics for flight emissions,
using a grid-based inventory approach with temporary workspace management.
The configuration is ``pyneats/resources/openairclim.toml`` and the response and
background data are ``pyneats/resources/repository`` (openairclim repository
data 0.2.0).

See Also
--------
openairclim : https://github.com/dlr-pa/oac
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
from pyneats.core.neats_default_parameters import OPEN_AIRCLIM_REFERENCE_YEAR
from pyneats.core.physics import METRICS_HORIZONS
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.climate_functions.params import ClimateParams
from pyneats.steps.climate_functions.protocol import NonCO2Model
from pyneats.steps.climate_functions.protocol import OpenAirClimStepError
from pyneats.steps.climate_functions.views import FlightWithGlobalAGWP
from pyneats.steps.emissions.views import FlightWithEmissions


# Aircraft identifier openairclim assigns when the inventory has no "ac"
# coordinate (see openairclim.toml [aircraft] types = ["DEFAULT"]). Results
# are read for this identifier, not "TOTAL": openairclim's own metrics file
# only holds "TOTAL", and with rel_to_base = true openairclim >= 0.15 adds
# the whole base fleet's contrails to "TOTAL".
OAC_AIRCRAFT_ID = "DEFAULT"


@dataclass(frozen=True)
class OpenAirClimParams(ClimateParams):
    tmp_base_dir_path: str = ""
    repo_dir_path: str = str(files("pyneats.resources").joinpath("repository"))
    base_toml_path: str = str(files("pyneats.resources").joinpath("openairclim.toml"))
    base_inventory_path: str | None = str(
        files("pyneats.resources").joinpath("ELK_aviation_2025_res5deg_flat.nc")
    )
    grid_res: float = OPEN_AIRCLIM_GRID_RES  # [degrees] lat/lon bin size
    oac_levels: tuple[int, ...] = OPEN_AIRCLIM_LEVELS  # [hPa]
    computation_horizon: int = OPEN_AIRCLIM_COMPUTATION_HORIZON  # [years]
    reference_year: int = OPEN_AIRCLIM_REFERENCE_YEAR  # emission year of every flight
    horizons: tuple[int, ...] = METRICS_HORIZONS  # [years]


def prepare_tmp_base_dir(path: str) -> None:
    """Create the OpenAirClim temp folder and check that it can be used.

    Every small-emitter flight opens a temporary folder inside ``path``. The
    runners call this once at start-up, so a missing parent is created and an
    unusable path fails before any flight is computed instead of failing every
    flight at the last step. ``""`` means the current working directory.

    Raises:
        ValueError: The folder cannot be created or written to. The message
            names the path.
    """
    try:
        if path:
            os.makedirs(path, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=path):
            pass
    except OSError as e:
        raise ValueError(
            f"OpenAirClim temp folder tmp_base_dir_path={path!r} cannot be "
            f"created or written to: {e}"
        ) from e


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

    ``year`` is the reference year (``OpenAirClimParams.reference_year``),
    which is also the inventory year. ``time.range`` covers every year from
    ``year`` to ``year + horizon`` [years] and ``metrics.t_0`` is ``[year]``,
    so every metric window [t_0, t_0 + H) starts with the emission and is
    the AGWP window read by ``OpenAirClimModel.run`` (see ``_harvest_agwp``).
    With ``rel_to_base``, openairclim also requires the inventory year to be
    the base inventory year (2025 for the bundled ELK inventory), which the
    reference year satisfies (audit item O4, see
    docs/internal/pyneats_units_audit.md).
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
    config["metrics"]["t_0"] = [year]

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


def _harvest_agwp(
    results_nc: str, t_0: int, horizons: tuple[int, ...], ac: str = OAC_AIRCRAFT_ID
) -> dict[int, dict[str, float]]:
    """Integrate openairclim RF time series into AGWP per species.

    ``AGWP_H = sum_{t in [t_0, t_0 + H)} RF(t) * dt`` [W m-2 yr] with
    dt = 1 year (openairclim requires a time step of 1), which is
    openairclim's own AGWP (``core/calc_metric.py``) applied to the results
    of aircraft identifier ``ac``. openairclim's ``*_metrics.nc`` only holds
    "TOTAL", which includes the base fleet's contrails when ``rel_to_base``
    is set.

    Returns:
        ``{H: {species: AGWP}}`` for every ``RF_<species>`` variable.

    Raises:
        OpenAirClimStepError: The results do not cover [t_0, t_0 + H).
    """
    out: dict[int, dict[str, float]] = {}
    with xr.load_dataset(results_nc) as ds:
        rf_vars = [v for v in ds.data_vars if str(v).startswith("RF_")]
        for h in horizons:
            window = ds.sel(ac=ac, time=slice(t_0, t_0 + h - 1))
            if window.sizes["time"] != h:
                raise OpenAirClimStepError(
                    f"openairclim results cover {window.sizes['time']} of the "
                    f"{h} years in [{t_0}, {t_0 + h})"
                )
            out[h] = {
                str(v)[len("RF_") :]: float(window[v].astype("float64").sum())
                for v in rf_vars
            }
    return out


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
        """Bin the flight into an openairclim emission inventory.

        Variables are sums over waypoints in each (lat, lon, plev) cell:
        ``fuel`` (``fuel_burn``), ``CO2``, ``H2O`` and ``NOx`` (pycontrails
        ``co2``/``h2o``/``nox``) in kg, from per-segment masses; ``distance``
        in km (``segment_length`` m / 1000). ``plev`` is the nearest
        ``oac_levels`` entry to ``air_pressure`` (Pa / 100, i.e. hPa);
        ``lat``/``lon`` are bin centres in degrees. ``Inventory_Year`` is
        ``reference_year``, whatever the flight date; openairclim treats the
        inventory as that year's emissions (no time-evolution file).

        NaN NOx, CO2 and H2O (e.g. NOx outside the met domain) are filled
        with 0. NOx is the pycontrails NOx mass (expressed as NO2 by ICAO
        EDB convention), matching ``[species] nox = "NO2"`` in the bundled
        ``openairclim.toml`` (decision A.2, Ramon + Philippe 2026-10-28).
        The openairclim 0.20 default is ``"NO"``, which would scale the NOx
        responses by 46/30, so the setting must stay explicit.
        """
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
        year = self.params.reference_year
        flight_year = df.iloc[0].time.year
        if flight_year != year:
            self.logger.debug(
                "Flight dated %s emitted in the OpenAirClim reference year %s",
                flight_year,
                year,
            )
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
        """Run openairclim on the flight inventory (Method D).

        Sets ``flight.attrs["AGWP_{H}_{O3,CH4,PMO,H2O,CONT}"]`` for H = 20, 50 and
        100 years, in W m-2 yr (openairclim "W m-2 year"), without efficacy.
        The values are the flight's own share (aircraft ``OAC_AIRCRAFT_ID``),
        integrated from openairclim's RF over the window starting at
        ``metrics.t_0``, the reference year (see ``_create_worker_toml`` and
        ``_harvest_agwp``). ``AGWP_{H}_CH4`` excludes PMO, which is stored
        separately in ``AGWP_{H}_PMO``; GWPMetrics applies each its own
        efficacy and adds them into the "CH4" output entry.

        Raises:
            OpenAirClimStepError: ``base_inventory_path`` is set but the file
                does not exist (``None`` runs without a base inventory), or
                openairclim fails.
        """
        # A configured base inventory that is missing is an error, not a
        # silent run without it: rel_to_base changes the contrail result.
        # None is the explicit opt-out. Resolved before the chdir below.
        base_inventory_path = self.params.base_inventory_path
        if base_inventory_path is not None:
            base_inventory_path = os.path.abspath(base_inventory_path)
            if not os.path.isfile(base_inventory_path):
                raise OpenAirClimStepError(
                    "OpenAirClim base inventory not found: "
                    f"base_inventory_path={self.params.base_inventory_path!r}. "
                    "Set base_inventory_path=None to run without a base inventory."
                )

        # The runners create the folder at start-up; direct users of the model
        # (and worker processes) get it created here.
        if self.params.tmp_base_dir_path:
            os.makedirs(self.params.tmp_base_dir_path, exist_ok=True)
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
                if base_inventory_path is not None:
                    base_inv_filename = os.path.basename(base_inventory_path)
                    os.symlink(
                        base_inventory_path,
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

                # 9. Harvest Results (the flight's own share, see _harvest_agwp)
                result_nc = "outputs/worker_result.nc"
                if not os.path.exists(result_nc):
                    raise OpenAirClimStepError("openairclim produced no results file")
                with open(toml_rel_path) as f:
                    t_0 = int(toml.load(f)["metrics"]["t_0"][0])
                results = _harvest_agwp(result_nc, t_0, tuple(self.params.horizons))

                # Assign Attributes
                for h in [20, 50, 100]:
                    flight.attrs[f"AGWP_{h}_O3"] = results[h]["O3"]
                    flight.attrs[f"AGWP_{h}_CH4"] = results[h]["CH4"]
                    flight.attrs[f"AGWP_{h}_PMO"] = results[h]["PMO"]
                    flight.attrs[f"AGWP_{h}_H2O"] = results[h]["H2O"]
                    flight.attrs[f"AGWP_{h}_CONT"] = results[h]["cont"]

            except Exception as e:
                self.logger.exception("Open_AirClim evaluation failed")
                raise OpenAirClimStepError(
                    f"Open_AirClim evaluation failed: {e}"
                ) from e

            finally:
                # 10. ALWAYS restore original directory
                os.chdir(original_cwd)

        return FlightWithGlobalAGWP.from_flight(flight)
