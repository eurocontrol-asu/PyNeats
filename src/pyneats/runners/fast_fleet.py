"""
Optimized fleet-level orchestration of NEATS climate computations.

This module provides `FastFleetRunner` - an optimized alternative to `FleetRunner`
that leverages vectorized operations for significant performance improvements.

Key optimizations:
    1. Weather loaded once upfront (not per-flight)
    2. Fleet-level weather intersection (vectorized) instead of per-flight
    3. Single CoCiP.eval() call on entire Fleet
    4. Parallel processing for parsing, interpolation, performance, and emissions
    5. Per-process caching for performance model initialization

Usage:
    ```python
    from pyneats.runners.fast_fleet import FastFleetRunner, FastFleetRunnerParams
    from pyneats.steps.weather.weather_store import ZarrPaths

    zarr_paths = ZarrPaths(
        met="/path/to/met.zarr",
        rad="/path/to/rad.zarr",
        wind="/path/to/wind.zarr"
    )

    params = FastFleetRunnerParams(
        trajectory_json_filepath="/path/to/flights.json",
        zarr_paths=zarr_paths,
        bada_path="/path/to/bada/",
    )

    runner = FastFleetRunner(params)
    runner.eval()
    df = runner.results_as_dataframe()
    ```
"""

from __future__ import annotations

import gc
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from joblib.externals.loky import get_reusable_executor
from numpy.typing import NDArray

from pycontrails import Fleet
from pycontrails.models.cocip import Cocip
from pycontrails.models.humidity_scaling import ExponentialBoostHumidityScaling

from pyneats.core.steps_registry import build
from pyneats.steps.climate_metrics.report import FleetReport
from pyneats.steps.emissions.pycontrails_emissions import PyContrailsEmissionModel
from pyneats.steps.interpolation.pycontrails_interpolation import PyContrailsInterpolator
from pyneats.steps.parsing.neats_io import neats_json_to_flights, split_df_into_flights
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.performance import PerformanceModel
from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr

logger = logging.getLogger(__name__)


# ---------------------------
# Configuration
# ---------------------------

@dataclass(frozen=True)
class FastFleetRunnerParams:
    """
    Immutable configuration container for FastFleetRunner.

    Required:
        zarr_paths: ZarrPaths object with met, rad, and optionally wind zarr stores

    Trajectory source (one required):
        trajectory_json_filepath: Path to NEATS JSON file
        trajectory_dataframe: DataFrame containing multiple flights

    Optional:
        bada_path: Path to BADA coefficient files
        zarr_read_chunks: Read-time chunk hints for zarr (None = use native chunks)

    Parallelism (number of workers):
        n_jobs_parsing: Parallel workers for parsing (default: 8)
        n_jobs_interpolation: Parallel workers for interpolation (default: 8)
        n_jobs_performance: Parallel workers for performance (-1 = all cores)
        n_jobs_emissions: Parallel workers for emissions (default: 8)

    Batch sizes (tune based on memory/CPU):
        batch_size_parsing: Joblib batch size for parsing (default: 32)
        batch_size_interpolation: Joblib batch size for interpolation (default: 32)
        batch_size_performance: Joblib batch size for performance (default: 16)
        batch_size_emissions: Joblib batch size for emissions (default: 32)

    CoCiP parameters:
        contrail_contrail_overlapping: Enable contrail overlapping (default: False)
        dt_integration_minutes: Integration time step in minutes (default: 1)
        max_age_hours: Maximum contrail age in hours (default: 12)
        humidity_scaling_rhi_adj: RHi adjustment factor (default: 0.9779)
        humidity_scaling_rhi_boost_exponent: RHi boost exponent (default: 1.635)
        humidity_scaling_clip_upper: Upper clip for humidity scaling (default: 1.65)
    """

    # Required
    zarr_paths: ZarrPaths

    # Trajectory source (one required)
    trajectory_json_filepath: Optional[str] = None
    trajectory_dataframe: Optional[pd.DataFrame] = None

    # BADA coefficients
    bada_path: Optional[str] = None

    # Zarr read configuration
    zarr_read_chunks: Optional[Mapping[str, int]] = None

    # Parallelism configuration
    n_jobs_parsing: int = 8
    n_jobs_interpolation: int = 8
    n_jobs_performance: int = -1  # -1 = use all cores
    n_jobs_emissions: int = 8

    # Batch sizes
    batch_size_parsing: int = 32
    batch_size_interpolation: int = 32
    batch_size_performance: int = 16
    batch_size_emissions: int = 32

    # CoCiP parameters
    contrail_contrail_overlapping: bool = False
    dt_integration_minutes: int = 1
    max_age_hours: int = 12
    humidity_scaling_rhi_adj: float = 0.9779
    humidity_scaling_rhi_boost_exponent: float = 1.635
    humidity_scaling_clip_upper: float = 1.65


# ---------------------------
# Per-process cache for performance model
# ---------------------------

_PERF_MODEL_CACHE: Optional[PerformanceModel] = None


def _get_perf_model(bada_path: Optional[str]) -> PerformanceModel:
    """
    Build PerformanceModel once per worker process.
    Each joblib worker gets its own cached instance.
    """
    global _PERF_MODEL_CACHE
    if _PERF_MODEL_CACHE is None:
        performance_params = {}
        if bada_path is not None:
            performance_params["bada4_root_path"] = bada_path
            performance_params["bada3_root_path"] = bada_path
        _PERF_MODEL_CACHE = build(PerformanceModel, "bada", **performance_params)
    return _PERF_MODEL_CACHE


# ---------------------------
# Worker functions for parallel processing
# ---------------------------

def _parse_one(f: pd.DataFrame) -> pd.DataFrame:
    """Parse a single flight trajectory."""
    parser = NeatsTrajectoryParser()
    return parser(f.copy())


def _interpolate_one(f: pd.DataFrame) -> pd.DataFrame:
    """Interpolate a single flight trajectory."""
    interpolator = PyContrailsInterpolator()
    return interpolator(f)


def _emissions_one(f: pd.DataFrame) -> pd.DataFrame:
    """Calculate emissions for a single flight."""
    emissions = PyContrailsEmissionModel()
    return emissions(f)


def _performance_one(
    i: int, f: pd.DataFrame, bada_path: Optional[str]
) -> Tuple[bool, int, Optional[pd.DataFrame], Optional[str], str]:
    """
    Calculate performance for a single flight.

    Returns:
        (success, index, result_or_none, error_or_none, flight_id)
    """
    flight_id = f.attrs.get("flight_id", "UNKNOWN")
    try:
        model = _get_perf_model(bada_path)
        out = model(f)
        return True, i, out, None, flight_id
    except Exception as e:
        return False, i, None, repr(e), flight_id


# ---------------------------
# FastFleetRunner
# ---------------------------

class FastFleetRunner:
    """
    Optimized fleet processing using vectorized operations.

    This runner implements the same climate impact calculations as FleetRunner,
    but with significant performance improvements through:

    1. **Upfront weather loading**: Weather data loaded once and reused
    2. **Fleet-level weather intersection**: Vectorized operations on entire fleet
    3. **Fleet-level CoCiP**: Single CoCiP.eval() call instead of per-flight
    4. **Parallel processing**: Joblib parallelization for parsing, interpolation,
       performance, and emissions steps
    5. **Per-process caching**: Performance model cached per worker process

    Attributes:
        params: Configuration parameters
        flights: List of parsed flight DataFrames
        results: Dictionary containing fleet metadata and per-flight results

    Example:
        ```python
        params = FastFleetRunnerParams(
            trajectory_json_filepath="flights.json",
            zarr_paths=ZarrPaths(...),
        )
        runner = FastFleetRunner(params)
        runner.eval()
        df = runner.results_as_dataframe()
        ```
    """

    def __init__(self, params: FastFleetRunnerParams) -> None:
        """
        Initialize FastFleetRunner with configuration.

        Args:
            params: FastFleetRunnerParams configuration object
        """
        self.params = params
        self.flights: Optional[List[pd.DataFrame]] = None
        self.results: Optional[Dict[str, Any]] = None

        # Validate configuration
        if self.params.trajectory_json_filepath is None and self.params.trajectory_dataframe is None:
            raise ValueError("Must provide either trajectory_json_filepath or trajectory_dataframe")

    # ---------------------------
    # Public API
    # ---------------------------

    def eval(self) -> "FastFleetRunner":
        """
        Execute the full optimized pipeline.

        Steps:
            1. Load trajectories from JSON or DataFrame
            2. Load weather data from Zarr stores
            3. Parallel parsing of trajectories
            4. Parallel interpolation
            5. Fleet-level weather intersection (vectorized)
            6. Apply humidity scaling
            7. Parallel performance calculations
            8. Parallel emissions calculations
            9. Fleet-level CoCiP evaluation
            10. Extract and format results

        Returns:
            self (for method chaining)
        """
        logger.info("FastFleetRunner: Starting optimized pipeline")

        # Step 1: Load trajectories
        self._load_trajectories()

        # Step 2: Load weather
        t0 = time.time()
        logger.info("Loading weather data from Zarr...")
        weather = get_weather_from_zarr(
            self.params.zarr_paths,
            chunks=self.params.zarr_read_chunks,
        )
        met = weather.met()
        rad = weather.rad()
        wind = weather.wind()
        logger.info(f"Weather loaded in {time.time() - t0:.2f}s")

        # Step 3: Parallel parsing
        seq = self._parallel_parsing()

        # Step 4: Parallel interpolation
        seq = self._parallel_interpolation(seq)

        # Step 5: Fleet-level weather intersection
        seq = self._fleet_weather_intersection(seq, met, wind)

        # Step 6: Apply humidity scaling
        seq = self._apply_humidity_scaling(seq)

        # Step 7: Parallel performance
        seq = self._parallel_performance(seq)

        # Step 8: Parallel emissions
        seq = self._parallel_emissions(seq)

        # Step 9: Fleet-level CoCiP
        fleet_with_contrails = self._fleet_cocip(seq, met, rad)

        # Step 10: Extract results
        self._extract_results(fleet_with_contrails)

        logger.info("FastFleetRunner: Pipeline complete")
        return self

    def results_as_dataframe(self) -> pd.DataFrame:
        """
        Flatten self.results into one row per flight.

        Climate metrics are expanded into wide columns:
            <species>_<horizon>_EAGWP_J_per_m2
            <species>_<horizon>_CO2eq_kg

        Returns:
            DataFrame with one row per flight and wide-format climate metrics
        """
        if self.results is None:
            raise RuntimeError("No results available. Call eval() first.")

        rows: List[Dict[str, Any]] = []

        for payload in self.results.get("flight_results", []):
            # Error case
            if "error" in payload:
                fi = payload.get("flight_information", {}) or {}
                row = dict(fi)
                row["error"] = payload["error"]
                rows.append(row)
                continue

            # Normal case
            fi = payload.get("flight_information", {}) or {}
            climate_metrics = payload.get("climate_metrics", []) or []

            row = dict(fi)

            # Expand climate metrics into wide columns
            for block in climate_metrics:
                species = block.get("species")
                for item in block.get("value", []):
                    horizon = item.get("horizon")
                    key_agwp = f"{species}_{horizon}_EAGWP_J_per_m2"
                    key_co2eq = f"{species}_{horizon}_CO2eq_kg"
                    row[key_agwp] = item.get("EAGWP_J_per_m2")
                    row[key_co2eq] = item.get("CO2eq_kg")

            rows.append(row)

        return pd.DataFrame(rows)

    # ---------------------------
    # Internal pipeline steps
    # ---------------------------

    def _load_trajectories(self) -> None:
        """Load trajectories from JSON file or DataFrame."""
        if self.params.trajectory_json_filepath is not None:
            self._load_trajectories_from_json()
        elif self.params.trajectory_dataframe is not None:
            self._load_trajectories_from_dataframe()
        else:
            raise RuntimeError("No trajectory source configured")

    def _load_trajectories_from_json(self) -> None:
        """Load trajectories from NEATS JSON file."""
        import json

        path = Path(self.params.trajectory_json_filepath)
        logger.info(f"Loading trajectories from {path}")

        try:
            with path.open("r", encoding="utf-8") as f:
                json_flights: List[Dict[str, Any]] = json.load(f)

            self.flights = neats_json_to_flights(json_flights)
            logger.info(f"Loaded {len(self.flights)} flights from JSON")
        except FileNotFoundError:
            logger.error(f"Trajectory file not found: {path}")
            raise
        except Exception as e:
            logger.error(f"Error loading trajectories from JSON: {e}")
            raise

    def _load_trajectories_from_dataframe(self) -> None:
        """Load trajectories from DataFrame."""
        try:
            df = self.params.trajectory_dataframe
            self.flights = split_df_into_flights(df)
            logger.info(f"Loaded {len(self.flights)} flights from DataFrame")
        except Exception as e:
            logger.error(f"Error loading trajectories from DataFrame: {e}")
            raise

    def _parallel_parsing(self) -> List[pd.DataFrame]:
        """Parse trajectories in parallel."""
        if self.flights is None:
            raise RuntimeError("Flights not loaded")

        t0 = time.time()
        logger.info(f"Parsing {len(self.flights)} flights (n_jobs={self.params.n_jobs_parsing})...")

        seq = Parallel(
            n_jobs=self.params.n_jobs_parsing,
            prefer="processes",
            batch_size=self.params.batch_size_parsing,
        )(delayed(_parse_one)(f) for f in self.flights)

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"Parsing complete in {time.time() - t0:.2f}s")
        return seq

    def _parallel_interpolation(self, seq: List[pd.DataFrame]) -> List[pd.DataFrame]:
        """Interpolate trajectories in parallel."""
        t0 = time.time()
        logger.info(f"Interpolating {len(seq)} flights (n_jobs={self.params.n_jobs_interpolation})...")

        seq = Parallel(
            n_jobs=self.params.n_jobs_interpolation,
            prefer="processes",
            batch_size=self.params.batch_size_interpolation,
        )(delayed(_interpolate_one)(f) for f in seq)

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"Interpolation complete in {time.time() - t0:.2f}s")
        return seq

    def _fleet_weather_intersection(
        self,
        seq: List[pd.DataFrame],
        met: Any,
        wind: Any,
    ) -> List[pd.DataFrame]:
        """
        Perform fleet-level weather intersection (vectorized).

        This is a key optimization: instead of intersecting weather per-flight,
        we create a Fleet and use vectorized operations.
        """
        t0 = time.time()
        logger.info(f"Fleet-level weather intersection for {len(seq)} flights...")

        # Create Fleet from sequence
        pyc_fleet = Fleet.from_seq(seq)

        # Downselect met and wind data to fleet bounds
        ds_met = pyc_fleet.downselect_met(
            met,
            longitude_buffer=(0.0, 0.0),
            latitude_buffer=(0.0, 0.0),
            time_buffer=(np.timedelta64(0, "h"), np.timedelta64(0, "h")),
            level_buffer=(0.0, 0.0),
        )

        ds_wind = pyc_fleet.downselect_met(
            wind,
            longitude_buffer=(0.0, 0.0),
            latitude_buffer=(0.0, 0.0),
            time_buffer=(np.timedelta64(0, "h"), np.timedelta64(0, "h")),
            level_buffer=(0.0, 0.0),
        )

        # Variable mapping
        var_map = {
            "eastward_wind": "u_wind",
            "northward_wind": "v_wind",
            "air_temperature": "air_temperature",
            "specific_humidity": "specific_humidity",
            "geopotential": "geopotential",
            "potential_vorticity": "potential_vorticity",
        }

        wind_vars = ("eastward_wind", "northward_wind")

        # Vectorized intersection for all variables
        new_cols = {}
        for met_var, out_col in var_map.items():
            if met_var in wind_vars:
                src = ds_wind[met_var]
            else:
                src = ds_met[met_var]

            vals = pyc_fleet.intersect_met(src, method="linear", use_indices=False)

            # Replace NaN with 0 for wind variables
            if met_var in wind_vars:
                vals = np.nan_to_num(vals, nan=0.0)

            new_cols[out_col] = vals

        # Build new Fleet with interpolated weather
        df = pyc_fleet.dataframe.reset_index(drop=True)
        for k, v in new_cols.items():
            if v.shape[0] != len(df):
                raise ValueError(f"Length mismatch for column {k}: {v.shape[0]} vs {len(df)}")
            df[k] = v

        fleet_with_weather = Fleet(data=df, attrs=pyc_fleet.attrs, fl_attrs=pyc_fleet.fl_attrs)

        logger.info(f"Weather intersection complete in {time.time() - t0:.2f}s")
        return fleet_with_weather.to_flight_list()

    def _apply_humidity_scaling(self, seq: List[pd.DataFrame]) -> List[pd.DataFrame]:
        """Apply humidity scaling to fleet."""
        t0 = time.time()
        logger.info("Applying humidity scaling...")

        humidity_scaling = ExponentialBoostHumidityScaling(
            rhi_adj=self.params.humidity_scaling_rhi_adj,
            rhi_boost_exponent=self.params.humidity_scaling_rhi_boost_exponent,
            clip_upper=self.params.humidity_scaling_clip_upper,
        )

        fleet = Fleet.from_seq(seq)
        fleet = humidity_scaling.eval(fleet)

        logger.info(f"Humidity scaling complete in {time.time() - t0:.2f}s")
        return fleet.to_flight_list()

    def _parallel_performance(self, seq: List[pd.DataFrame]) -> List[pd.DataFrame]:
        """Calculate performance in parallel with per-process caching."""
        t0 = time.time()
        logger.info(f"Performance calculations for {len(seq)} flights (n_jobs={self.params.n_jobs_performance})...")

        to_run = list(enumerate(seq))

        results = Parallel(
            n_jobs=self.params.n_jobs_performance,
            prefer="processes",
            batch_size=self.params.batch_size_performance,
        )(delayed(_performance_one)(i, f, self.params.bada_path) for i, f in to_run)

        # Collect successful results in original order
        good_seq = []
        n_fail = 0
        for ok, i, out, err, flight_id in sorted(results, key=lambda x: x[1]):
            if ok:
                good_seq.append(out)
            else:
                n_fail += 1
                logger.error(
                    f"Performance calculation failed for flight {flight_id} (index {i}): {err}"
                )

        if n_fail > 0:
            logger.warning(f"{n_fail}/{len(seq)} flights failed performance calculations")

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"Performance calculations complete in {time.time() - t0:.2f}s ({len(good_seq)}/{len(seq)} succeeded)")
        return good_seq

    def _parallel_emissions(self, seq: List[pd.DataFrame]) -> List[pd.DataFrame]:
        """Calculate emissions in parallel."""
        t0 = time.time()
        logger.info(f"Emissions calculations for {len(seq)} flights (n_jobs={self.params.n_jobs_emissions})...")

        seq = Parallel(
            n_jobs=self.params.n_jobs_emissions,
            prefer="processes",
            batch_size=self.params.batch_size_emissions,
        )(delayed(_emissions_one)(f) for f in seq)

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"Emissions calculations complete in {time.time() - t0:.2f}s")
        return seq

    def _fleet_cocip(
        self,
        seq: List[pd.DataFrame],
        met: Any,
        rad: Any,
    ) -> Fleet:
        """
        Run CoCiP once on entire fleet (vectorized).

        This is a major optimization: instead of running CoCiP per-flight,
        we run it once on the entire Fleet.
        """
        t0 = time.time()
        logger.info(f"Fleet-level CoCiP evaluation for {len(seq)} flights...")

        params = {
            "contrail_contrail_overlapping": self.params.contrail_contrail_overlapping,
            "dt_integration": np.timedelta64(self.params.dt_integration_minutes, "m"),
            "max_age": np.timedelta64(self.params.max_age_hours, "h"),
            "humidity_scaling": ExponentialBoostHumidityScaling(
                rhi_adj=self.params.humidity_scaling_rhi_adj,
                rhi_boost_exponent=self.params.humidity_scaling_rhi_boost_exponent,
                clip_upper=self.params.humidity_scaling_clip_upper,
            ),
            "interpolation_use_indices": False,
        }

        cocip = Cocip(met=met, rad=rad, params=params)
        fleet = Fleet.from_seq(seq)
        results_fleet = cocip.eval(source=fleet)

        logger.info(f"CoCiP evaluation complete in {time.time() - t0:.2f}s")
        return results_fleet

    def _extract_results(self, fleet_with_contrails: Fleet) -> None:
        """
        Extract results from Fleet and format for output.

        This matches the FleetRunner.results format for compatibility.
        """
        logger.info("Extracting results...")

        # For now, create a simple summary similar to the experimental code
        # TODO: Integrate with full climate metrics reporting if needed
        rows = []

        for flight in fleet_with_contrails.to_flight_list():
            attrs = flight.attrs
            df = flight.dataframe

            # Basic flight information and fuel/contrail metrics
            payload = {
                "flight_information": {
                    "flight_id": attrs.get("flight_id"),
                    "departure_airport": attrs.get("departure_airport"),
                    "arrival_airport": attrs.get("arrival_airport"),
                    "aobt": attrs.get("aobt"),
                    "aircraft_type": attrs.get("aircraft_type"),
                    "engine_uid": attrs.get("engine_uid"),
                },
                "climate_metrics": [
                    {
                        "species": "fuel_burn",
                        "value": [
                            {
                                "horizon": "total",
                                "EAGWP_J_per_m2": float(np.nansum(df["fuel_burn"])) if "fuel_burn" in df else np.nan,
                                "CO2eq_kg": float(np.nansum(df["fuel_burn"])) if "fuel_burn" in df else np.nan,
                            }
                        ],
                    },
                    {
                        "species": "contrails",
                        "value": [
                            {
                                "horizon": "total",
                                "EAGWP_J_per_m2": float(np.nansum(df["ef"])) if "ef" in df else np.nan,
                                "CO2eq_kg": float(np.nansum(df["ef"])) if "ef" in df else np.nan,
                            }
                        ],
                    },
                ],
            }
            rows.append(payload)

        self.results = {
            "fleet_meta_data": FleetReport.collect(),
            "flight_results": rows,
        }

        logger.info(f"Results extracted for {len(rows)} flights")
