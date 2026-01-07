"""
Optimized fleet-level orchestration of NEATS climate computations.

This module provides `FastFleetRunner` - an optimized alternative to `FleetRunner`
that leverages vectorized operations for significant performance improvements.
"""

from __future__ import annotations

import gc
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, TypeVar

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from joblib.externals.loky import get_reusable_executor

from pycontrails import Flight, Fleet
from pycontrails.models.cocip import Cocip
from pycontrails.models.humidity_scaling import HumidityScaling

from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.performance.views import FlightWithPerformance
from pyneats.steps.weather.weather_provider import FlightWithWeather
from pyneats.core.steps_registry import build
from pyneats.runners.flight import RunnerConfig
from pyneats.steps.climate_metrics.report import FleetReport
from pyneats.steps.interpolation.protocol import TrajectoryInterpolator
from pyneats.steps.parsing.neats_io import neats_json_to_flights, split_df_into_flights
from pyneats.steps.parsing.neats_parser import NEATSFuel
from pyneats.steps.parsing.protocol import TrajectoryParser
from pyneats.steps.parsing.views import Flight4D
from pyneats.steps.performance import PerformanceModel
from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr
from pyneats.core.neats_default_parameters import DEFAULT_COCIP_KWARGS, DEFAULT_HUMIDITY_SCALING

logger = logging.getLogger(__name__)

# Type variables for generic processing
T = TypeVar("T")
U = TypeVar("U")

# ---------------------------
# Configuration
# ---------------------------


@dataclass(frozen=True)
class FastFleetRunnerParams:
    """Immutable configuration for the fast fleet runner"""

    # Required
    zarr_paths: ZarrPaths

    # Trajectory source (one required)
    trajectory_json_filepath: Optional[str] = None
    trajectory_dataframe: Optional[pd.DataFrame] = None

    # BADA coefficients
    bada_path: Optional[str] = None

    # Zarr read configuration
    zarr_read_chunks: Optional[Mapping[str, int]] = None

    # Step implementations and parameters
    runner_config: RunnerConfig = field(default_factory=RunnerConfig)

    # Parallelism configuration
    n_jobs: int = -1
    batch_size: int = 16

    # CoCiP parameters (backward compatibility)
    cocip_kwargs: Mapping[str, Any] = field(default_factory=lambda: DEFAULT_COCIP_KWARGS)

    # Humidity scaling after weather
    humidity_scaling: HumidityScaling | None = field(
        default_factory=lambda: DEFAULT_HUMIDITY_SCALING
    )

    # Critical columns for error detection in vectorized steps
    weather_critical_columns: Tuple[str, ...] = (
        "air_temperature",
        "specific_humidity",
        "geopotential",
        "potential_vorticity",
    )
    humidity_scaling_critical_columns: Tuple[str, ...] = ()
    cocip_critical_columns: Tuple[str, ...] = ()


# ---------------------------
# Per-process cache for performance model
# ---------------------------

_PERF_MODEL_CACHE: Optional[PerformanceModel] = None


def _get_perf_model(
    performance_name: str,
    performance_params: Mapping[str, Any],
) -> PerformanceModel:
    """
    Build PerformanceModel once per worker process.
    Each joblib worker gets its own cached instance.
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
# Generic worker function
# ---------------------------

ProcessorFunc = Callable[[T], U]


def _process_one(
    i: int,
    item: T,
    processor_func: ProcessorFunc,
    flight_id_extractor: Callable[[T], str],
) -> Tuple[bool, int, Optional[U], Optional[str], str]:
    """
    Generic processor for a single item with error handling.

    Args:
        i: Item index
        item: Item to process
        processor_func: Function to apply to the item
        flight_id_extractor: Function to extract flight_id from item

    Returns:
        (success, index, result_or_none, error_or_none, flight_id)
    """
    flight_id = flight_id_extractor(item)
    try:
        result = processor_func(item)
        return True, i, result, None, flight_id
    except Exception as e:
        return False, i, None, repr(e), flight_id


def _extract_flight_id(item: Any) -> str:
    """Extract flight_id from various flight-like objects."""
    if hasattr(item, "attrs"):
        return item.attrs.get("flight_id", "UNKNOWN")
    return "UNKNOWN"


# ---------------------------
# Specialized worker functions
# ---------------------------


def _make_parser(parser_name: str, parser_params: Mapping[str, Any]) -> ProcessorFunc:
    """Create a parser function."""

    def parser(f: pd.DataFrame) -> Flight4D:
        model = build(TrajectoryParser, parser_name, **parser_params)
        return model(f.copy())

    return parser


def _make_interpolator(
    interpolator_name: str, interpolator_params: Mapping[str, Any]
) -> ProcessorFunc:
    """Create an interpolator function."""

    def interpolator(f: Flight4D) -> Flight4D:
        model = build(TrajectoryInterpolator, interpolator_name, **interpolator_params)
        return model(f)

    return interpolator


def _make_performance_calculator(
    performance_name: str, performance_params: Mapping[str, Any]
) -> ProcessorFunc:
    """Create a performance calculator function."""

    def calculator(f: FlightWithWeather) -> FlightWithPerformance:
        model = _get_perf_model(performance_name, performance_params)
        return model(f)

    return calculator


def _make_emissions_calculator(
    emissions_name: str, emissions_params: Mapping[str, Any]
) -> ProcessorFunc:
    """Create an emissions calculator function."""

    def calculator(f: FlightWithPerformance) -> FlightWithEmissions:
        model = build(EmissionModel, emissions_name, **emissions_params)
        return model(f)

    return calculator


def _process_parallel_results(
    results: List[Tuple[bool, int, Any, Optional[str], str]],
    original_seq: List[Any],
    step_name: str,
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """
    Process results from parallel execution and separate successes from failures.

    Args:
        results: List of (success, index, result_or_none, error_or_none, flight_id) tuples
        original_seq: Original sequence of flights
        step_name: Name of the step for error messages

    Returns:
        Tuple of (successful_results, error_records)
    """
    successful = []
    error_records = []

    for ok, i, out, err, flight_id in sorted(results, key=lambda x: x[1]):
        if ok:
            successful.append(out)
        else:
            error_records.append(_create_error_record(original_seq[i], flight_id, step_name, err))
            logger.error(f"{step_name} failed for flight {flight_id} (index {i}): {err}")

    if error_records:
        logger.warning(f"{len(error_records)}/{len(original_seq)} flights failed at {step_name}")

    return successful, error_records


def _create_error_record(
    original_flight: Any,
    flight_id: str,
    step_name: str,
    error_msg: Optional[str],
) -> Dict[str, Any]:
    """Create a standardized error record."""
    attrs = original_flight.attrs if hasattr(original_flight, "attrs") else {}
    return {
        "flight_information": {
            "flight_id": flight_id,
            "departure_airport": attrs.get("departure_airport", "UNKNOWN"),
            "arrival_airport": attrs.get("arrival_airport", "UNKNOWN"),
            "aobt": attrs.get("aobt", "UNKNOWN"),
            "aircraft_type": attrs.get("aircraft_type", "UNKNOWN"),
            "engine_uid": attrs.get("engine_uid", "UNKNOWN"),
        },
        "error": f"Failed at {step_name}: {error_msg}",
    }


# ---------------------------
# FastFleetRunner
# ---------------------------


class FastFleetRunner:
    """
    Optimized fleet processing using vectorized operations.

    Key optimizations:
    1. Upfront weather loading - data loaded once and reused
    2. Fleet-level weather intersection - vectorized operations
    3. Fleet-level CoCiP - single evaluation call
    4. Parallel processing - joblib parallelization for per-flight steps
    5. Per-process caching - performance model cached per worker

    Attributes:
        params: Configuration parameters
        flights: List of parsed flight DataFrames
        results: Dictionary containing fleet metadata and per-flight results
    """

    def __init__(self, params: FastFleetRunnerParams) -> None:
        """Initialize FastFleetRunner with configuration."""
        self.params = params
        self.flights: Optional[List[pd.DataFrame]] = None
        self.results: Optional[Dict[str, Any]] = None
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate that required configuration is present."""
        if (
            self.params.trajectory_json_filepath is None
            and self.params.trajectory_dataframe is None
        ):
            raise ValueError("Must provide either trajectory_json_filepath or trajectory_dataframe")

    # ---------------------------
    # Public API
    # ---------------------------
    @staticmethod
    def _seq_to_fleet(seq: List[Flight]) -> Fleet:
        for s in seq:
            s["q_fuel"] = np.full(len(s), s.fuel.q_fuel)
            s["ei_h2o"] = np.full(len(s), s.fuel.ei_h2o)
            s.fuel = None 
            
        return Fleet.from_seq(seq)
    
    @staticmethod
    def _fleet_to_seq(fleet: Fleet) -> List[Flight]:
        seq = fleet.to_flight_list()
        
        for s in seq:
            del s["q_fuel"]
            del s["ei_h2o"]
            s.fuel = NEATSFuel.from_attrs(s.attrs)
            
        return seq
     
    def eval(self) -> "FastFleetRunner":
        """
        Execute the full optimized pipeline.

        Pipeline steps:
            1. Load trajectories
            2. Load weather data
            3-4. Parallel parsing and interpolation
            5-6. Fleet-level weather intersection and humidity scaling
            7-8. Parallel performance and emissions calculations
            9. Fleet-level CoCiP evaluation
            10. Extract and format results

        Returns:
            self (for method chaining)
        """
        logger.info("FastFleetRunner: Starting optimized pipeline")
        error_records: List[Dict[str, Any]] = []

        # Load data
        self._load_trajectories()
        met, rad, wind = self._load_weather()

        # Parallel per-flight steps
        seq = self.flights
        seq, errors = self._run_parallel_step(seq, "parsing", self._make_parser_func())
        error_records.extend(errors)

        seq, errors = self._run_parallel_step(seq, "interpolation", self._make_interpolator_func())
        error_records.extend(errors)

        # Fleet-level vectorized steps
        seq = self._fleet_weather_intersection(seq, met, wind)
        seq, errors = self._check_and_filter_failed_flights(
            seq, self.params.weather_critical_columns, "weather intersection"
        )
        error_records.extend(errors)

        seq = self._apply_humidity_scaling(seq)
        seq, errors = self._check_and_filter_failed_flights(
            seq, self.params.humidity_scaling_critical_columns, "humidity scaling"
        )
        error_records.extend(errors)

        # Parallel per-flight steps
        seq, errors = self._run_parallel_step(seq, "performance", self._make_performance_func())
        error_records.extend(errors)

        seq, errors = self._run_parallel_step(seq, "emissions", self._make_emissions_func())
        error_records.extend(errors)

        # Fleet-level CoCiP
        seq = self._fleet_cocip(seq, met, rad)
        seq, errors = self._check_and_filter_failed_flights(
            seq, self.params.cocip_critical_columns, "CoCiP evaluation"
        )
        error_records.extend(errors)

        # Extract results
        self._extract_results(seq, error_records)

        logger.info(
            f"FastFleetRunner: Pipeline complete - {len(seq)} successful, {len(error_records)} failed"
        )
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

        rows = [
            self._flatten_flight_result(payload)
            for payload in self.results.get("flight_results", [])
        ]

        return pd.DataFrame(rows)

    # ---------------------------
    # Internal pipeline helpers
    # ---------------------------

    def _load_weather(self) -> Tuple[Any, Any, Any]:
        """Load weather data from Zarr stores."""
        t0 = time.time()
        logger.info("Loading weather data from Zarr...")

        weather = get_weather_from_zarr(
            self.params.zarr_paths,
            chunks=self.params.zarr_read_chunks,
        )
        met, rad, wind = weather.met(), weather.rad(), weather.wind()

        logger.info(f"Weather loaded in {time.time() - t0:.2f}s")
        return met, rad, wind

    def _run_parallel_step(
        self,
        seq: List[T],
        step_name: str,
        processor_func: ProcessorFunc,
    ) -> Tuple[List[U], List[Dict[str, Any]]]:
        """
        Generic parallel processing step with error handling.

        Args:
            seq: Sequence of items to process
            step_name: Name of the step for logging
            processor_func: Function to apply to each item

        Returns:
            Tuple of (successful_results, error_records)
        """
        t0 = time.time()
        logger.info(f"{step_name.capitalize()} {len(seq)} flights (n_jobs={self.params.n_jobs})...")

        results = Parallel(
            n_jobs=self.params.n_jobs,
            prefer="processes",
            batch_size=self.params.batch_size,
        )(
            delayed(_process_one)(i, item, processor_func, _extract_flight_id)
            for i, item in enumerate(seq)
        )

        good_seq, error_records = _process_parallel_results(results, seq, step_name)

        # Cleanup
        get_reusable_executor().shutdown(wait=True)
        gc.collect()

        logger.info(f"{step_name.capitalize()} complete in {time.time() - t0:.2f}s")
        return good_seq, error_records

    def _check_and_filter_failed_flights(
        self,
        seq: List[Flight],
        critical_columns: Tuple[str, ...],
        step_name: str,
    ) -> Tuple[List[Flight], List[Dict[str, Any]]]:
        """
        Check for failed flights based on NaN values in critical columns.

        Flights fail if ALL values in ANY critical column are NaN or missing.

        Returns:
            Tuple of (successful_flights, error_records)
        """
        successful = []
        errors = []

        for flight in seq:
            df = flight.dataframe
            attrs = flight.attrs if hasattr(flight, "attrs") else {}
            flight_id = attrs.get("flight_id", "UNKNOWN")

            failure_message = self._check_critical_columns(df, critical_columns)

            if failure_message:
                errors.append(_create_error_record(flight, flight_id, step_name, failure_message))
                logger.warning(f"Flight {flight_id} failed at {step_name}: {failure_message}")
            else:
                successful.append(flight)

        if errors:
            logger.warning(f"{len(errors)}/{len(seq)} flights failed at {step_name}")

        return successful, errors

    @staticmethod
    def _check_critical_columns(
        df: pd.DataFrame, critical_columns: Tuple[str, ...]
    ) -> Optional[str]:
        """
        Check if any critical column is missing or all NaN.

        Returns:
            Error message if failed, None if passed
        """
        for col in critical_columns:
            if col not in df.columns:
                return f"{col} (missing)"
            if df[col].isna().all():
                return f"{col} (all NaN)"
        return None

    # ---------------------------
    # Trajectory loading
    # ---------------------------

    def _load_trajectories(self) -> None:
        """Load trajectories from configured source."""
        if self.params.trajectory_json_filepath is not None:
            self._load_trajectories_from_json()
        elif self.params.trajectory_dataframe is not None:
            self._load_trajectories_from_dataframe()
        else:
            raise RuntimeError("No trajectory source configured")

    def _load_trajectories_from_json(self) -> None:
        """Load trajectories from NEATS JSON file."""
        import json

        path = Path(str(self.params.trajectory_json_filepath))
        logger.info(f"Loading trajectories from {path}")

        with path.open("r", encoding="utf-8") as f:
            json_flights: List[Dict[str, Any]] = json.load(f)

        self.flights = neats_json_to_flights(json_flights)
        logger.info(f"Loaded {len(self.flights)} flights from JSON")

    def _load_trajectories_from_dataframe(self) -> None:
        """Load trajectories from DataFrame."""
        df: pd.DataFrame = self.params.trajectory_dataframe
        self.flights = split_df_into_flights(df)
        logger.info(f"Loaded {len(self.flights)} flights from DataFrame")

    # ---------------------------
    # Processor function factories
    # ---------------------------

    def _make_parser_func(self) -> ProcessorFunc:
        """Create parser function from config."""
        return _make_parser(
            self.params.runner_config.trajectory_parser,
            self.params.runner_config.params.get("trajectory_parser", {}),
        )

    def _make_interpolator_func(self) -> ProcessorFunc:
        """Create interpolator function from config."""
        return _make_interpolator(
            self.params.runner_config.interpolator,
            self.params.runner_config.params.get("interpolator", {}),
        )

    def _make_performance_func(self) -> ProcessorFunc:
        """Create performance function from config."""
        params = dict(self.params.runner_config.params.get("performance", {}))
        if self.params.bada_path is not None:
            params.update(
                {
                    "bada4_root_path": self.params.bada_path,
                    "bada3_root_path": self.params.bada_path,
                }
            )
        return _make_performance_calculator(self.params.runner_config.performance, params)

    def _make_emissions_func(self) -> ProcessorFunc:
        """Create emissions function from config."""
        return _make_emissions_calculator(
            self.params.runner_config.emissions,
            self.params.runner_config.params.get("emissions", {}),
        )

    # ---------------------------
    # Fleet-level vectorized operations
    # ---------------------------

    def _fleet_weather_intersection(
        self,
        seq: List[Flight4D],
        met: Any,
        wind: Any,
    ) -> List[Flight]:
        """Perform fleet-level weather intersection (vectorized)."""
        t0 = time.time()
        logger.info(f"Fleet-level weather intersection for {len(seq)} flights...")

        pyc_fleet = self._seq_to_fleet(seq)

        # Downselect weather data to fleet bounds
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

        # Vectorized intersection
        new_cols = self._intersect_weather_variables(pyc_fleet, ds_met, ds_wind)

        # Build Fleet with weather data
        df = pyc_fleet.dataframe.reset_index(drop=True)
        for k, v in new_cols.items():
            df[k] = v

        fleet_with_weather = Fleet(data=df, attrs=pyc_fleet.attrs, fl_attrs=pyc_fleet.fl_attrs)

        logger.info(f"Weather intersection complete in {time.time() - t0:.2f}s")
        return self._fleet_to_seq(fleet_with_weather)

    @staticmethod
    def _intersect_weather_variables(
        fleet: Fleet,
        ds_met: Any,
        ds_wind: Any,
    ) -> Dict[str, np.ndarray]:
        """Intersect weather variables with fleet trajectory."""
        var_map = {
            "eastward_wind": ("u_wind", True),
            "northward_wind": ("v_wind", True),
            "air_temperature": ("air_temperature", False),
            "specific_humidity": ("specific_humidity", False),
            "geopotential": ("geopotential", False),
            "potential_vorticity": ("potential_vorticity", False),
        }

        new_cols = {}

        for met_var, (out_col, is_wind) in var_map.items():
            if is_wind:
                if met_var in ds_wind:  # Prefer wind dataset for wind variables
                    dataset = ds_wind
                elif met_var in ds_met:
                    dataset = ds_met
                else:
                    raise KeyError(
                        f"required wind var '{met_var}' missing (looked in WIND then MET)"
                    )
            else:
                if met_var in ds_met:
                    dataset = ds_met
                else:
                    raise KeyError(f"required met var '{met_var}' missing in MET")

            vals = fleet.intersect_met(
                dataset[met_var],
                method="linear",
                use_indices=False,
            )

            if is_wind:
                vals = np.nan_to_num(vals, nan=0.0)

            new_cols[out_col] = vals

        return new_cols

    def _apply_humidity_scaling(self, seq: List[Flight]) -> List[Flight]:
        """Apply humidity scaling to fleet (vectorized)."""
        t0 = time.time()
        logger.info("Applying humidity scaling...")

        fleet = self._seq_to_fleet(seq)
        fleet = self.params.humidity_scaling.eval(fleet)

        logger.info(f"Humidity scaling complete in {time.time() - t0:.2f}s")
        return self._fleet_to_seq(fleet)

    def _fleet_cocip(self, seq: List[Flight], met: Any, rad: Any) -> List[Flight]:
        """Run CoCiP once on entire fleet (vectorized)."""
        t0 = time.time()
        logger.info(f"Fleet-level CoCiP evaluation for {len(seq)} flights...")

        cocip = Cocip(met=met, rad=rad, **self.params.cocip_kwargs)
        fleet = self._seq_to_fleet(seq)
        results_fleet = cocip.eval(source=fleet)

        logger.info(f"CoCiP evaluation complete in {time.time() - t0:.2f}s")
        return self._fleet_to_seq(results_fleet)

    # ---------------------------
    # Results extraction
    # ---------------------------

    def _extract_results(
        self,
        successful_flights: List[Flight],
        error_records: List[Dict[str, Any]],
    ) -> None:
        """Extract results from successful flights and merge with error records."""
        logger.info("Extracting results...")

        successful_results = [self._extract_flight_metrics(flight) for flight in successful_flights]

        self.results = {
            "fleet_meta_data": FleetReport.collect(),
            "flight_results": successful_results + error_records,
        }

        logger.info(
            f"Results extracted: {len(successful_results)} successful, "
            f"{len(error_records)} failed, {len(successful_results + error_records)} total"
        )

    @staticmethod
    def _extract_flight_metrics(flight: Flight) -> Dict[str, Any]:
        """Extract metrics from a single flight."""
        attrs = flight.attrs if hasattr(flight, "attrs") else {}
        df = flight.dataframe if hasattr(flight, "dataframe") else flight

        return {
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
                            "EAGWP_J_per_m2": float(np.nansum(df["fuel_burn"]))
                            if "fuel_burn" in df
                            else np.nan,
                            "CO2eq_kg": float(np.nansum(df["fuel_burn"]))
                            if "fuel_burn" in df
                            else np.nan,
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

    @staticmethod
    def _flatten_flight_result(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten a flight result into a single row."""
        # Handle error case
        if "error" in payload:
            fi = payload.get("flight_information", {}) or {}
            row = dict(fi)
            row["error"] = payload["error"]
            return row

        # Normal case
        fi = payload.get("flight_information", {}) or {}
        climate_metrics = payload.get("climate_metrics", []) or []

        row = dict(fi)

        # Expand climate metrics into wide columns
        for block in climate_metrics:
            species = block.get("species")
            for item in block.get("value", []):
                horizon = item.get("horizon")
                row[f"{species}_{horizon}_EAGWP_J_per_m2"] = item.get("EAGWP_J_per_m2")
                row[f"{species}_{horizon}_CO2eq_kg"] = item.get("CO2eq_kg")

        return row
