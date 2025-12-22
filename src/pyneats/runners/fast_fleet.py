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
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from joblib.externals.loky import get_reusable_executor
from numpy.typing import NDArray

from pycontrails import Flight, Fleet
from pycontrails.models.humidity_scaling import ExponentialBoostHumidityScaling

from pyneats.core.steps_registry import build
from pyneats.core.neats_default_parameters import DEFAULT_CONTRAILS_MODEL
from pyneats.runners.flight import RunnerConfig
from pyneats.steps.climate_metrics.report import FleetReport
from pyneats.steps.climate_functions.protocol import ContrailsModel
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.interpolation.protocol import TrajectoryInterpolator
from pyneats.steps.parsing.neats_io import neats_json_to_flights, split_df_into_flights
from pyneats.steps.parsing.protocol import TrajectoryParser
from pyneats.steps.parsing.views import Flight4D
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
        runner_config: RunnerConfig specifying step implementations and params (default: RunnerConfig())

    RunnerConfig fields used by FastFleetRunner:
        - trajectory_parser: Used for parallel parsing step
        - interpolator: Used for parallel interpolation step
        - performance: Used for parallel performance step
        - emissions: Used for vectorized emissions step
        - contrails_model: Used for vectorized contrails step
        - params: Custom parameters for all above steps

    RunnerConfig fields NOT used (FastFleetRunner uses hardcoded implementations):
        - non_co2_model: Not used (FastFleetRunner doesn't compute non-CO2 impacts)
        - climate_impact: Not used (FastFleetRunner doesn't compute climate metrics)

    Note: FastFleetRunner uses hardcoded vectorized implementations for:
        - Weather intersection (not configurable, optimized for fleet-level)
        - Humidity scaling (not configurable, uses ExponentialBoostHumidityScaling)

    Parallelism (number of workers):
        n_jobs_parsing: Parallel workers for parsing (default: 8)
        n_jobs_interpolation: Parallel workers for interpolation (default: 8)
        n_jobs_performance: Parallel workers for performance (-1 = all cores)

    Batch sizes (tune based on memory/CPU):
        batch_size_parsing: Joblib batch size for parsing (default: 32)
        batch_size_interpolation: Joblib batch size for interpolation (default: 32)
        batch_size_performance: Joblib batch size for performance (default: 16)

    CoCiP parameters (backward compatibility - prefer using runner_config.params):
        contrail_contrail_overlapping: Enable contrail overlapping (default: False)
        dt_integration_minutes: Integration time step in minutes (default: 1)
        max_age_hours: Maximum contrail age in hours (default: 12)
        humidity_scaling_rhi_adj: RHi adjustment factor (default: 0.9779)
        humidity_scaling_rhi_boost_exponent: RHi boost exponent (default: 1.635)
        humidity_scaling_clip_upper: Upper clip for humidity scaling (default: 1.65)

    Error detection for vectorized steps:
        weather_critical_columns: Columns to check for NaN after weather intersection
        humidity_scaling_critical_columns: Columns to check after humidity scaling
        emissions_critical_columns: Columns to check after emissions calculation
        cocip_critical_columns: Columns to check after CoCiP evaluation
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

    # Step implementations and parameters (shared with FlightRunner)
    runner_config: RunnerConfig = field(default_factory=RunnerConfig)

    # Parallelism configuration
    n_jobs_parsing: int = 8
    n_jobs_interpolation: int = 8
    n_jobs_performance: int = -1  # -1 = use all cores

    # Batch sizes
    batch_size_parsing: int = 32
    batch_size_interpolation: int = 32
    batch_size_performance: int = 16

    # CoCiP parameters (backward compatibility - prefer using runner_config.params)
    contrail_contrail_overlapping: bool = False
    dt_integration_minutes: int = 1
    max_age_hours: int = 12
    humidity_scaling_rhi_adj: float = 0.9779
    humidity_scaling_rhi_boost_exponent: float = 1.635
    humidity_scaling_clip_upper: float = 1.65

    # Critical columns for error detection in vectorized steps
    weather_critical_columns: Tuple[str, ...] = ("air_temperature", "specific_humidity")
    humidity_scaling_critical_columns: Tuple[str, ...] = ("specific_humidity",)
    emissions_critical_columns: Tuple[str, ...] = ("fuel_burn", "nvpm_ei_n")
    cocip_critical_columns: Tuple[str, ...] = ("ef",)


# ---------------------------
# Per-process cache for performance model
# ---------------------------

_PERF_MODEL_CACHE: Optional[PerformanceModel] = None


def _get_perf_model(
    performance_name: str,
    performance_params: Dict[str, Any],
) -> PerformanceModel:
    """
    Build PerformanceModel once per worker process.
    Each joblib worker gets its own cached instance.

    Args:
        performance_name: Registry name for the performance model
        performance_params: Parameters to pass to the performance model
    """
    global _PERF_MODEL_CACHE
    if _PERF_MODEL_CACHE is None:
        _PERF_MODEL_CACHE = build(
            PerformanceModel,
            performance_name,
            **performance_params,
        )
    return _PERF_MODEL_CACHE


# ---------------------------
# Worker functions for parallel processing
# ---------------------------

def _parse_one(f: pd.DataFrame, parser_name: str, parser_params: Dict[str, Any]) -> Flight4D:
    """Parse a single flight trajectory."""
    parser = build(TrajectoryParser, parser_name, **parser_params)
    return parser(f.copy())


def _interpolate_one(f: Flight4D, interpolator_name: str, interpolator_params: Dict[str, Any]) -> Flight4D:
    """Interpolate a single flight trajectory."""
    interpolator = build(TrajectoryInterpolator, interpolator_name, **interpolator_params)
    return interpolator(f)


def _performance_one(
    i: int,
    f: Flight,
    performance_name: str,
    performance_params: Dict[str, Any],
) -> Tuple[bool, int, Optional[Flight], Optional[str], str]:
    """
    Calculate performance for a single flight.

    Args:
        i: Flight index
        f: Flight object
        performance_name: Registry name for the performance model
        performance_params: Parameters to pass to the performance model

    Returns:
        (success, index, result_or_none, error_or_none, flight_id)
    """
    flight_id = f.attrs.get("flight_id", "UNKNOWN")
    try:
        model = _get_perf_model(performance_name, performance_params)
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
            6. Fleet-level humidity scaling (vectorized)
            7. Parallel performance calculations
            8. Fleet-level emissions calculations (vectorized)
            9. Fleet-level CoCiP evaluation (vectorized)
            10. Extract and format results

        Returns:
            self (for method chaining)
        """
        logger.info("FastFleetRunner: Starting optimized pipeline")

        # Initialize error tracking
        error_records: List[Dict[str, Any]] = []

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

        # Step 5: Fleet-level weather intersection (vectorized)
        seq = self._fleet_weather_intersection(seq, met, wind)
        # Check for failures after weather intersection
        seq, errors = self._check_and_filter_failed_flights(
            seq,
            self.params.weather_critical_columns,
            "weather intersection"
        )
        error_records.extend(errors)

        # Step 6: Fleet-level humidity scaling (vectorized)
        seq = self._apply_humidity_scaling(seq)
        # Check for failures after humidity scaling
        seq, errors = self._check_and_filter_failed_flights(
            seq,
            self.params.humidity_scaling_critical_columns,
            "humidity scaling"
        )
        error_records.extend(errors)

        # Step 7: Parallel performance
        seq, perf_errors = self._parallel_performance(seq)
        error_records.extend(perf_errors)

        # Step 8: Fleet-level emissions (vectorized)
        seq = self._fleet_emissions(seq)
        # Check for failures after emissions
        seq, errors = self._check_and_filter_failed_flights(
            seq,
            self.params.emissions_critical_columns,
            "emissions calculation"
        )
        error_records.extend(errors)

        # Step 9: Fleet-level CoCiP (vectorized)
        fleet_with_contrails = self._fleet_cocip(seq, met, rad)

        # Step 10: Check for CoCiP failures and extract results
        flight_list = fleet_with_contrails.to_flight_list()
        flight_list, errors = self._check_and_filter_failed_flights(
            flight_list,
            self.params.cocip_critical_columns,
            "CoCiP evaluation"
        )
        error_records.extend(errors)

        # Step 11: Extract results (both successful and errors)
        self._extract_results(flight_list, error_records)

        logger.info(f"FastFleetRunner: Pipeline complete - {len(flight_list)} successful, {len(error_records)} failed")
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

    def _check_and_filter_failed_flights(
        self,
        seq: List[Union[Flight, Flight4D, pd.DataFrame]],
        critical_columns: Tuple[str, ...],
        step_name: str,
    ) -> Tuple[List[Union[Flight, Flight4D, pd.DataFrame]], List[Dict[str, Any]]]:
        """
        Check for failed flights based on NaN values in critical columns.

        Flights are considered failed if ALL values in ANY critical column are NaN
        or if the column is missing entirely.

        Args:
            seq: List of Flight/Flight4D objects or DataFrames to check
            critical_columns: Tuple of column names to check for NaN
            step_name: Name of the pipeline step (for error messages)

        Returns:
            Tuple of (successful_flights, error_records)
            - successful_flights: List of flights that passed validation
            - error_records: List of error dicts for failed flights
        """
        successful = []
        errors = []

        for flight in seq:
            # Get dataframe and attrs (handle Flight, Flight4D, pd.DataFrame)
            if isinstance(flight, pd.DataFrame):
                df = flight
                attrs = getattr(flight, "attrs", {})
            else:
                df = flight.dataframe if hasattr(flight, "dataframe") else flight.data
                attrs = flight.attrs if hasattr(flight, "attrs") else {}

            # Check if any critical column has ALL NaN values or is missing
            has_failure = False
            failed_columns = []

            for col in critical_columns:
                if col not in df.columns:
                    has_failure = True
                    failed_columns.append(f"{col} (missing)")
                elif df[col].isna().all():
                    has_failure = True
                    failed_columns.append(f"{col} (all NaN)")

            if has_failure:
                # Extract flight info for error record
                flight_id = attrs.get("flight_id", "UNKNOWN")
                error_record = {
                    "flight_information": {
                        "flight_id": flight_id,
                        "departure_airport": attrs.get("departure_airport", "UNKNOWN"),
                        "arrival_airport": attrs.get("arrival_airport", "UNKNOWN"),
                        "aobt": attrs.get("aobt", "UNKNOWN"),
                        "aircraft_type": attrs.get("aircraft_type", "UNKNOWN"),
                        "engine_uid": attrs.get("engine_uid", "UNKNOWN"),
                    },
                    "error": f"Failed at {step_name}: {', '.join(failed_columns)}"
                }
                errors.append(error_record)
                logger.warning(f"Flight {flight_id} failed at {step_name}: {', '.join(failed_columns)}")
            else:
                successful.append(flight)

        if errors:
            logger.warning(f"{len(errors)}/{len(seq)} flights failed at {step_name}")

        return successful, errors

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

    def _parallel_parsing(self) -> List[Flight4D]:
        """Parse trajectories in parallel."""
        if self.flights is None:
            raise RuntimeError("Flights not loaded")

        t0 = time.time()
        logger.info(f"Parsing {len(self.flights)} flights (n_jobs={self.params.n_jobs_parsing})...")

        # Get step name and params from RunnerConfig
        parser_name = self.params.runner_config.trajectory_parser
        parser_params = self.params.runner_config.params.get("trajectory_parser", {})

        seq = Parallel(
            n_jobs=self.params.n_jobs_parsing,
            prefer="processes",
            batch_size=self.params.batch_size_parsing,  # type: ignore[arg-type]
        )(delayed(_parse_one)(f, parser_name, parser_params) for f in self.flights)

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"Parsing complete in {time.time() - t0:.2f}s")
        return seq  # type: ignore[return-value]

    def _parallel_interpolation(self, seq: List[Flight4D]) -> List[Flight4D]:
        """Interpolate trajectories in parallel."""
        t0 = time.time()
        logger.info(f"Interpolating {len(seq)} flights (n_jobs={self.params.n_jobs_interpolation})...")

        # Get step name and params from RunnerConfig
        interpolator_name = self.params.runner_config.interpolator
        interpolator_params = self.params.runner_config.params.get("interpolator", {})

        seq = Parallel(
            n_jobs=self.params.n_jobs_interpolation,
            prefer="processes",
            batch_size=self.params.batch_size_interpolation,  # type: ignore[arg-type]
        )(delayed(_interpolate_one)(f, interpolator_name, interpolator_params) for f in seq)

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"Interpolation complete in {time.time() - t0:.2f}s")
        return seq  # type: ignore[return-value]

    def _fleet_weather_intersection(
        self,
        seq: List[Flight4D],
        met: Any,
        wind: Any,
    ) -> List[Flight]:
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

    def _apply_humidity_scaling(self, seq: List[Flight]) -> List[Flight]:
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

    def _parallel_performance(self, seq: List[Flight]) -> Tuple[List[Flight], List[Dict[str, Any]]]:
        """
        Calculate performance in parallel with per-process caching.

        Returns:
            Tuple of (successful_flights, error_records)
        """
        t0 = time.time()
        logger.info(f"Performance calculations for {len(seq)} flights (n_jobs={self.params.n_jobs_performance})...")

        # Get step name and params from RunnerConfig
        performance_name = self.params.runner_config.performance
        performance_params = self.params.runner_config.params.get("performance", {})

        # Add BADA path to params if provided
        if self.params.bada_path is not None:
            performance_params = dict(performance_params)  # Make a copy
            performance_params.update({
                "bada4_root_path": self.params.bada_path,
                "bada3_root_path": self.params.bada_path,
            })

        to_run = list(enumerate(seq))

        results = Parallel(
            n_jobs=self.params.n_jobs_performance,
            prefer="processes",
            batch_size=self.params.batch_size_performance,  # type: ignore[arg-type]
        )(delayed(_performance_one)(i, f, performance_name, performance_params) for i, f in to_run)

        # Collect successful results and create error records
        good_seq = []
        error_records = []

        for ok, i, out, err, flight_id in sorted(results, key=lambda x: x[1]):
            if ok:
                good_seq.append(out)
            else:
                # Get flight attrs from original sequence
                original_flight = seq[i]
                attrs = original_flight.attrs if hasattr(original_flight, "attrs") else {}

                error_record = {
                    "flight_information": {
                        "flight_id": flight_id,
                        "departure_airport": attrs.get("departure_airport", "UNKNOWN"),
                        "arrival_airport": attrs.get("arrival_airport", "UNKNOWN"),
                        "aobt": attrs.get("aobt", "UNKNOWN"),
                        "aircraft_type": attrs.get("aircraft_type", "UNKNOWN"),
                        "engine_uid": attrs.get("engine_uid", "UNKNOWN"),
                    },
                    "error": f"Failed at performance calculation: {err}"
                }
                error_records.append(error_record)
                logger.error(
                    f"Performance calculation failed for flight {flight_id} (index {i}): {err}"
                )

        if error_records:
            logger.warning(f"{len(error_records)}/{len(seq)} flights failed performance calculations")

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"Performance calculations complete in {time.time() - t0:.2f}s ({len(good_seq)}/{len(seq)} succeeded)")
        return good_seq, error_records

    def _fleet_emissions(self, seq: List[Flight]) -> List[Flight]:
        """
        Calculate emissions for entire fleet (vectorized).

        This is an optimization: instead of calculating emissions per-flight,
        we create a Fleet and use PyContrails' vectorized operations.
        """
        t0 = time.time()
        logger.info(f"Fleet-level emissions calculation for {len(seq)} flights...")

        # Build emissions model using registry pattern (like FlightRunner)
        emissions_params = self.params.runner_config.params.get("emissions", {})
        emissions = build(
            EmissionModel,
            self.params.runner_config.emissions,
            **emissions_params,
        )

        # Create Fleet and evaluate
        fleet = Fleet.from_seq(seq)
        fleet_with_emissions = emissions.eval(fleet)

        logger.info(f"Emissions calculations complete in {time.time() - t0:.2f}s")
        return fleet_with_emissions.to_flight_list()

    def _fleet_cocip(
        self,
        seq: List[Flight],
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

        # Build contrails model params using registry pattern (like FlightRunner)
        # Start with custom params from RunnerConfig
        contrail_params = dict(self.params.runner_config.params.get("contrails_model", {}))

        # Add required met/rad datasets
        contrail_params.update({
            "met": met,
            "rad": rad,
        })

        # For backward compatibility: if using default "cocip" model and no custom cocip_kwargs provided,
        # build default cocip_kwargs from FastFleetRunnerParams fields
        if self.params.runner_config.contrails_model == DEFAULT_CONTRAILS_MODEL and "cocip_kwargs" not in contrail_params:
            cocip_kwargs = {
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
            contrail_params["cocip_kwargs"] = cocip_kwargs

        # Build using registry (allows different contrails models, not just CoCiP)
        contrails_model = build(
            ContrailsModel,
            self.params.runner_config.contrails_model,
            **contrail_params,
        )

        fleet = Fleet.from_seq(seq)
        results_fleet = contrails_model.eval(source=fleet)

        logger.info(f"CoCiP evaluation complete in {time.time() - t0:.2f}s")
        return results_fleet

    def _extract_results(
        self,
        successful_flights: List[Flight],
        error_records: List[Dict[str, Any]]
    ) -> None:
        """
        Extract results from successful flights and merge with error records.

        Args:
            successful_flights: List of flights that completed successfully
            error_records: List of error records from failed flights

        This matches the FleetRunner.results format for compatibility.
        """
        logger.info("Extracting results...")

        # Extract results from successful flights
        successful_results = []

        for flight in successful_flights:
            attrs = flight.attrs if hasattr(flight, "attrs") else {}
            df = flight.dataframe if hasattr(flight, "dataframe") else flight

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
            successful_results.append(payload)

        # Merge successful results with error records
        all_results = successful_results + error_records

        self.results = {
            "fleet_meta_data": FleetReport.collect(),
            "flight_results": all_results,
        }

        logger.info(
            f"Results extracted: {len(successful_results)} successful, "
            f"{len(error_records)} failed, {len(all_results)} total"
        )
