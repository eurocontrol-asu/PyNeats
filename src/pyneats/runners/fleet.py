
"""
Optimized Fleet Runner Module

Orchestrates fleet-level NEATS climate computations with vectorized operations for significant performance improvements.

Features
--------
- Single config object holding step names and params (RunnerConfig) plus fleet settings (FleetRunnerParams)
- Explicit, typed intermediate pipeline attributes (like FlightRunner)
- Decomposed pipeline into intermediate steps (like FlightRunner)
- Generic, registry-based step construction with per-process caching for joblib workers
- Continue-on-error behavior for per-flight steps, keeping vectorized steps fleet-level
"""

from __future__ import annotations

import gc
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Self, TypeVar, cast

import pandas as pd
from joblib import Parallel, delayed
from joblib.externals.loky import get_reusable_executor
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.humidity_scaling import HumidityScaling

from pyneats.core.compute_parameters import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_JOBLIB_PREFERENCE,
    DEFAULT_NJOBS,
)
from pyneats.core.neats_default_parameters import (
    DEFAULT_COCIP_KWARGS,
    DEFAULT_HUMIDITY_SCALING,
)
from pyneats.core.steps import Step, VectorizedStep
from pyneats.core.steps_registry import build
from pyneats.runners.flight import RunnerConfig
from pyneats.steps.climate_functions.cocip import CoCiPModel, ContrailsParams
from pyneats.steps.climate_functions.protocol import NonCO2Model
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
from pyneats.steps.climate_metrics.protocol import ClimateImpactModel
from pyneats.steps.climate_metrics.report import FleetReport
from pyneats.steps.climate_metrics.views import FlightWithClimateImpact
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.interpolation.protocol import TrajectoryInterpolator
from pyneats.steps.parsing.neats_io import neats_json_to_flights, split_df_into_flights
from pyneats.steps.parsing.protocol import TrajectoryParser
from pyneats.steps.parsing.views import Flight4D
from pyneats.steps.performance import PerformanceModel
from pyneats.steps.performance.views import FlightWithPerformance
from pyneats.steps.weather.weather_provider import (
    FlightWithWeather,
    PcHumidityScalingAdapter,
    WeatherProvider,
    WeatherProviderParams,
)
from pyneats.steps.weather.weather_store import (
    ZarrPaths,
    clear_dataset_cache,
    get_weather_from_zarr,
)
from pyneats.runners.runner import Runner

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Types
# -----------------------------------------------------------------------------

# Unbounded type vars for generic parallel processing (handles DataFrame inputs too)
T = TypeVar("T")
U = TypeVar("U")

# Type vars for Step interface (InT can be DataFrame|Flight, OutT must be Flight)
# These are used by _get_step_cached and make_step_func
InT = TypeVar("InT")  # Invariant, unbounded (parsers take DataFrame)
OutT = TypeVar("OutT", bound=Flight)  # Invariant, bound to Flight (Step protocol requires this)

# Flight-bounded type vars for vectorized steps and flight filtering
InFlightT = TypeVar("InFlightT", bound=Flight)
OutFlightT = TypeVar("OutFlightT", bound=Flight)
FlightT = TypeVar("FlightT", bound=Flight)


# -----------------------------------------------------------------------------
# Discriminated union for parallel step results (enables type narrowing)
# -----------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class StepSuccess(Generic[U]):
    """Successful step result with typed output."""

    index: int
    flight_id: str
    data: U


@dataclass(slots=True, frozen=True)
class StepFailure:
    """Failed step result with error info."""

    index: int
    flight_id: str
    error_msg: str


StepResult = StepSuccess[U] | StepFailure

# -----------------------------------------------------------------------------
# Config (RunnerConfig + fleet-specific fields)
# -----------------------------------------------------------------------------


# NOTE:
# - This mirrors FlightRunner’s “cfg carries step names + params” philosophy.
# - We add fleet-only concerns here.
# - kw_only=True avoids dataclass field ordering issues when subclassing.
@dataclass(kw_only=True)
class FleetRunnerParams(RunnerConfig):
    """Fleet runner configuration, extending the FlightRunner-style RunnerConfig."""

    # Required fleet resource
    zarr_paths: ZarrPaths

    # Trajectory source (exactly one required)
    trajectory_json_filepath: str | None = None
    trajectory_dataframe: pd.DataFrame | None = None

    # Optional BADA coefficients path
    bada_path: str | None = None

    # Zarr read configuration
    zarr_read_chunks: Mapping[str, int] | None = None

    # Parallelism configuration (joblib)
    njobs: int = DEFAULT_NJOBS
    batch_size: int = DEFAULT_BATCH_SIZE
    prefer: str = DEFAULT_JOBLIB_PREFERENCE

    # Memory / executor behavior:
    # - If True, mimics your original runner behavior.
    # - If False, loky pool stays alive across steps
    shutdown_executor_between_steps: bool = True
    gc_collect_between_steps: bool = True

    # CoCiP (pycontrails) parameters
    cocip_kwargs: Mapping[str, Any] = field(default_factory=lambda: DEFAULT_COCIP_KWARGS)

    # Humidity scaling after weather intersection
    humidity_scaling: HumidityScaling | None = field(
        default_factory=lambda: DEFAULT_HUMIDITY_SCALING
    )

    # Critical columns for vectorized-step failure detection
    weather_critical_columns: tuple[str, ...] = (
        "air_temperature",
        "specific_humidity",
        "geopotential",
        "potential_vorticity",
    )
    humidity_scaling_critical_columns: tuple[str, ...] = ()
    cocip_critical_columns: tuple[str, ...] = ()

    def validate(self) -> None:

        if self.zarr_paths is None:
            raise ValueError("FastFleetRunnerConfig.zarr_paths is required")

        if self.trajectory_json_filepath is None and self.trajectory_dataframe is None:
            raise ValueError("Must provide either trajectory_json_filepath or trajectory_dataframe")


# -----------------------------------------------------------------------------
# Generic step cache (per-process) built on steps_registry.build()
# -----------------------------------------------------------------------------

# Each  worker is a separate Python process => cache is per-process.
#
# Cache key is (interface, name) only - params are NOT included.
# This means the first params used for a given (interface, name) pair are cached,
# and subsequent calls with different params will return the cached step.
#
# This is intentional for FleetRunner's use case where each step type is created
# once per process with fixed params. If you need different params for the same
# step type, consider including a params hash in the key.

_STEP_CACHE: dict[tuple[type[Any], str], Any] = {}


def _get_step_cached(
    interface: type[Step[InT, OutT]], name: str, params: Mapping[str, Any]
) -> Step[InT, OutT]:
    key = (interface, name.lower().strip())
    step = _STEP_CACHE.get(key)
    if step is None:
        step = build(interface, name, **dict(params))
        _STEP_CACHE[key] = step
    # Return the cached/built step
    return step


def make_step_func(
    interface: type[Step[InT, OutT]],
    name: str,
    params: Mapping[str, Any],
    *,
    copy_input: bool = False,
) -> Callable[[InT], OutT]:
    """Return a callable (InT -> OutT) using registry build() + per-process cache."""

    def fn(x: InT) -> OutT:
        step = _get_step_cached(interface, name, params)
        if copy_input and hasattr(x, "copy"):
            x = cast(Any, x).copy(deep=False)
        return step(x)

    return fn


# -----------------------------------------------------------------------------
# Error handling helpers (fleet continues on error)
# -----------------------------------------------------------------------------


def _process_one(
    i: int,
    item: T,
    processor_func: Callable[[T], U],
) -> StepResult[U]:
    """
    Process a single item and return a discriminated union result.

    Returns StepSuccess[U] on success, StepFailure on error.
    This enables type-safe result processing without casts.
    """
    # Extract flight_id inline (simplifies API, always same logic)
    flight_id = (
        getattr(item, "attrs", {}).get("flight_id", "UNKNOWN")
        if hasattr(item, "attrs")
        else "UNKNOWN"
    )
    try:
        out = processor_func(item)
        return StepSuccess(index=i, flight_id=flight_id, data=out)
    except Exception as e:
        return StepFailure(index=i, flight_id=flight_id, error_msg=repr(e))


def _create_error_record(
    original_flight: Any,
    flight_id: str,
    step_name: str,
    error_msg: str,
) -> dict[str, Any]:
    """Create a structured error record for a failed flight."""
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


def _process_parallel_results(
    results: list[StepResult[U]],
    original_seq: list[T],
    step_name: str,
) -> tuple[list[U], list[dict[str, Any]]]:
    """
    Process parallel step results using discriminated union pattern.

    Type narrowing via isinstance allows returning typed list[U] without cast.
    """
    successful: list[U] = []
    errors: list[dict[str, Any]] = []

    for res in sorted(results, key=lambda x: x.index):
        if isinstance(res, StepSuccess):
            # Type narrowing: res.data is U
            successful.append(res.data)
        else:
            # res is StepFailure
            errors.append(
                _create_error_record(
                    original_seq[res.index], res.flight_id, step_name, res.error_msg
                )
            )
            logger.error(
                "%s failed for flight %s (index %d): %s",
                step_name,
                res.flight_id,
                res.index,
                res.error_msg,
            )

    if errors:
        logger.warning("%d/%d flights failed at %s", len(errors), len(original_seq), step_name)

    return successful, errors


# -----------------------------------------------------------------------------
# FastFleetRunner (FlightRunner-like shape)
# -----------------------------------------------------------------------------


class FleetRunner(Runner):
    """
    Fast fleet pipeline with FlightRunner-like structure.

    Intermediate outputs are stored as explicit attributes to mirror FlightRunner:
      - self.source_flights
      - self.parsed_flights
      - self.interpolated_flights
      - self.fleet_with_weather
      - self.fleet_with_performance
      - self.fleet_with_emissions
      - self.fleet_with_contrails

    This runner keeps "continue-on-error" semantics: per-flight failures are
    recorded and filtered out rather than aborting the whole run.
    """

    parser: Callable[[pd.DataFrame], Flight4D]
    interpolator: Callable[[Flight4D], Flight4D]
    performance: Callable[[FlightWithWeather], FlightWithPerformance]
    emission: Callable[[FlightWithPerformance], FlightWithEmissions]

    def __init__(self, cfg: FleetRunnerParams) -> None:
        self.cfg = cfg
        self.cfg.validate()

        # ---- Weather datasets (loaded once) ---------------------------------
        self.met: MetDataset | None = None
        self.rad: MetDataset | None = None
        self.wind: MetDataset | None = None

        # ---- Pipeline elements’ outputs -----------------
        self.source_fleet: list[pd.DataFrame] | None = None
        self.parsed_fleet: list[Flight4D] | None = None
        self.interpolated_fleet: list[Flight4D] | None = None
        self.fleet_with_weather: list[FlightWithWeather] | None = None
        self.fleet_with_performance: list[FlightWithPerformance] | None = None
        self.fleet_with_emissions: list[FlightWithEmissions] | None = None
        self.fleet_with_nonco2: list[FlightWithNonCO2Impact] | None = None
        self.fleet_with_climate_impact: list[FlightWithClimateImpact] | None = None

        # Error aggregation (continue-on-error)
        self.error_records: list[dict[str, Any]] = []

        # Pipeline abort flag - set to True when all flights fail at a step
        # This enables early termination in Runner.eval()
        self._pipeline_aborted: bool = False

        # Final output
        self.results: dict[str, Any] | None = None

        # ---- Step callables (registry-based, process-cached) -----------------
        self.parser = make_step_func(
            TrajectoryParser,  # type: ignore[type-abstract]
            self.cfg.trajectory_parser,
            self._params("trajectory_parser"),
            copy_input=True,  # DataFrame safety
        )

        self.interpolator = make_step_func(
            TrajectoryInterpolator,  # type: ignore[type-abstract]
            self.cfg.interpolator,
            self._params("interpolator"),
        )

        self.performance = make_step_func(
            PerformanceModel,  # type: ignore[type-abstract]
            self.cfg.performance,
            self._params("performance", extra=self._bada_params()),
        )

        self.emission = make_step_func(
            EmissionModel,  # type: ignore[type-abstract]
            self.cfg.emissions,
            self._params("emissions"),
        )

        self.non_co2_model = make_step_func(
            NonCO2Model,  # type: ignore[type-abstract]
            self.cfg.non_co2_model,
            self._params("non_co2_model"),
        )

        self.climate_impact = make_step_func(
            ClimateImpactModel,  # type: ignore[type-abstract]
            self.cfg.climate_impact,
            self._params("climate_impact"),
        )

        # ---- Vectorized step objects (created in _load_weather) --------------
        self.weather_step: WeatherProvider | None = None
        

    # -------------------------------------------------------------------------
    # Param handling (FlightRunner-like)
    # -------------------------------------------------------------------------

    def _params(self, key: str, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return a defensive copy of cfg.params[key] merged with optional extra params."""
        base = dict(self.cfg.params.get(key, {}))
        if extra:
            base.update(dict(extra))
        return base

    def _bada_params(self) -> dict[str, Any]:
        if self.cfg.bada_path is None:
            return {}
        return {
            "bada4_root_path": self.cfg.bada_path,
            "bada3_root_path": self.cfg.bada_path,
        }

    # -------------------------------------------------------------------------
    # FleetRunner stages (FlightRunner-like step decomposition)
    # -------------------------------------------------------------------------

    def _load_data(self) -> Self:
        return (
            self._load_trajectories()  # pylint: disable=protected-access
            ._load_weather()  # pylint: disable=protected-access
        )
     
    def _load_trajectories(self) -> Self:
        if self.cfg.trajectory_json_filepath is not None:
            path = Path(self.cfg.trajectory_json_filepath)
            logger.info("Loading trajectories from %s", path)
            with path.open("r", encoding="utf-8") as f:
                json_flights: list[dict[str, Any]] = json.load(f)
            self.source_fleet = neats_json_to_flights(json_flights)
            logger.info("Loaded %d flights from JSON", len(self.source_fleet))
            return self

        if self.cfg.trajectory_dataframe is not None:
            logger.info("Loading trajectories from DataFrame")
            self.source_fleet = split_df_into_flights(self.cfg.trajectory_dataframe)
            logger.info("Loaded %d flights from DataFrame", len(self.source_fleet))
            return self

        raise RuntimeError("No trajectory source configured)")

    def _load_weather(self) -> Self:
        logger.info("Loading weather data from Zarr...")

        weather = get_weather_from_zarr(self.cfg.zarr_paths, chunks=self.cfg.zarr_read_chunks)
        self.met, self.rad, self.wind = weather.met(), weather.rad(), weather.wind()

        # Create vectorized steps now that weather datasets are available
        logger.info("Initializing vectorized steps (weather, CoCiP)...")

        # Weather intersection step
        # Wrap HumidityScaling (pycontrails) with adapter for HumidityScalingModel protocol
        humidity_model = (
            PcHumidityScalingAdapter(self.cfg.humidity_scaling)
            if self.cfg.humidity_scaling is not None
            else None
        )
        weather_params = WeatherProviderParams(
            humidity_scaling=humidity_model,
            **self._params("weather_intersection"),
        )
        self.weather_step = WeatherProvider(
            met=self.met, rad=self.rad, wind=self.wind, params=weather_params
        )

        # CoCiP step
        cocip_params = ContrailsParams(
            met=self.met, rad=self.rad, cocip_kwargs=self.cfg.cocip_kwargs
        )
        self.cocip_step = CoCiPModel(params=cocip_params)

        return self

    def _parse_flight(self) -> Self:

        if self.source_fleet is None:
            raise RuntimeError("source_flights must be loaded before _parse_flights()")

        self.parsed_fleet, errs = self._run_parallel_step(self.source_fleet, "parsing", self.parser)
        self.error_records.extend(errs)

        self.source_fleet = None  # free memory (FlightRunner-style)

        return self

    def _interpolate(self) -> Self:

        if self.parsed_fleet is None:
            raise RuntimeError("parsed_flights must be set before _interpolate()")

        self.interpolated_fleet, errs = self._run_parallel_step(
            self.parsed_fleet, "interpolation", self.interpolator
        )
        self.error_records.extend(errs)

        self.parsed_fleet = None  # free memory


        return self

    def _intersect_weather(self) -> Self:

        if self.interpolated_fleet is None:
            raise RuntimeError("interpolated_flights must be set before _intersect_weather()")
        if self.weather_step is None:
            raise RuntimeError("weather_step must be initialized before _intersect_weather()")

        # Run vectorized weather intersection
        flights = self._run_vectorized_step(
            self.interpolated_fleet,
            "weather intersection",
            self.weather_step,
            self.cfg.weather_critical_columns,
        )

        # Check humidity scaling failures (separate from weather intersection)
        flights, errs = self._check_and_filter_failed_flights(
            flights,
            self.cfg.humidity_scaling_critical_columns,
            "humidity scaling",
        )
        self.error_records.extend(errs)

        self.fleet_with_weather = flights
        self.interpolated_fleet = None  # free memory

        return self

    def _performance(self) -> Self:

        if self.fleet_with_weather is None:
            raise RuntimeError("fleet_with_weather must be set before _performance()")

        self.fleet_with_performance, errs = self._run_parallel_step(
            self.fleet_with_weather, "performance", self.performance
        )
        self.error_records.extend(errs)

        self.fleet_with_weather = None  # free memory


        return self

    def _emissions(self) -> Self:

        if self.fleet_with_performance is None:
            raise RuntimeError("_performance must be set before _emissions()")

        self.fleet_with_emissions, errs = self._run_parallel_step(
            self.fleet_with_performance, "emissions", self.emission
        )
        self.error_records.extend(errs)

        self.fleet_with_performance = None  # free memory


        return self
    
    def _climate_impact(self) -> Self:
        """Abstract method."""
        raise NotImplementedError
    
    def _climate_metrics(self) -> Self:

        if self.fleet_with_nonco2 is None:
            raise RuntimeError("_nonco2 must be set before _climate_metrics()")

        self.fleet_with_climate_impact, errs = self._run_parallel_step(
            self.fleet_with_nonco2, "climate_impact", self.climate_impact
        )
        self.error_records.extend(errs)

        self.fleet_with_nonco2 = None  # free memory


        return self

    def _extract_results(self) -> Self:
        # Case 1: Pipeline aborted (all flights failed at some step)
        # Return only errors in standard format - this is expected behavior
        if self._pipeline_aborted:
            logger.warning(
                "Pipeline aborted - returning %d error records only",
                len(self.error_records),
            )
            self.results = {
                "fleet_meta_data": FleetReport.collect(),
                "flight_results": self.error_records,
            }
            clear_dataset_cache()
            return self

        # Case 2: Programming error - _extract_results called without running pipeline
        # This should never happen in normal flow, so we still raise
        if self.fleet_with_climate_impact is None:
            raise RuntimeError("climate_impact must be set before _extract_results()")

        # Case 3: Normal case - some or all flights succeeded
        successful_results = [f.attrs["climate_impact"] for f in self.fleet_with_climate_impact]

        self.results = {
            "fleet_meta_data": FleetReport.collect(),
            "flight_results": successful_results + self.error_records,
        }

        clear_dataset_cache()

        return self
    

    def results_as_dataframe(self) -> pd.DataFrame:
        """
        Flatten self.results into one row per flight.
        Climate metrics are expanded into wide columns:
            <species>_<horizon>_AGWP_J_per_m2
            <species>_<horizon>_CO2eq_kg
        """
        rows: list[dict[str, Any]] = []

        if self.results is None:
            return pd.DataFrame(rows)

        for payload in self.results.get("flight_results") or []:
            # -------- Error case --------
            if "error" in payload:
                fi = payload.get("flight_information", {}) or {}
                row = dict(fi)
                row["error"] = payload["error"]
                rows.append(row)
                continue

            # -------- Normal case --------
            fi = payload.get("flight_information", {}) or {}
            climate_metrics = payload.get("climate_metrics", []) or []

            row = dict(fi)  # start with all flight-information fields

            # Expand each species/horizon into wide fields
            for block in climate_metrics:
                species = block.get("species")
                for item in block.get("value") or []:
                    horizon = item.get("horizon")

                    # Column names such as CO2_20_AGWP_J_per_m2
                    key_agwp = f"{species}_{horizon}_EAGWP_J_per_m2"
                    key_co2eq = f"{species}_{horizon}_CO2eq_kg"

                    row[key_agwp] = item.get("EAGWP_J_per_m2")
                    row[key_co2eq] = item.get("CO2eq_kg")

            rows.append(row)

        return pd.DataFrame(rows)

    # -------------------------------------------------------------------------
    # Parallel runner (generic)
    # -------------------------------------------------------------------------

    def _run_vectorized_step(
        self,
        flights: list[InFlightT],
        step_name: str,
        step: VectorizedStep[InFlightT, OutFlightT],
        critical_columns: tuple[str, ...],
    ) -> list[OutFlightT]:
        """
        Run a vectorized step with error handling.

        Args:
            flights: List of input flights (must be Flight subclass)
            step_name: Name of the step (for logging/error messages)
            step: Step instance implementing VectorizedStep protocol
            critical_columns: Columns to check for failures

        Returns:
            List of successful output flights (type-safe, no cast needed)

        Note:
            Sets `_pipeline_aborted = True` if all flights fail after filtering.
            Returns empty list if input is empty (prevents Fleet.from_seq crash).
        """
        # Guard: empty input - skip step to prevent Fleet.from_seq([]) crash
        if not flights:
            logger.warning("Skipping %s: no flights to process", step_name)
            return []

        # Call step's run_fleet() method (typed via VectorizedStep protocol)
        result_flights = step.run_fleet(flights)

        # Check for critical column failures and filter
        successful, errs = self._check_and_filter_failed_flights(
            result_flights,
            critical_columns,
            step_name,
        )
        self.error_records.extend(errs)

        # Auto-abort if all flights failed
        if not successful and flights:
            logger.warning(
                "All %d flights failed at %s - aborting pipeline",
                len(flights),
                step_name,
            )
            self._pipeline_aborted = True

        return successful

    def _run_parallel_step(
        self,
        seq: list[T],
        step_name: str,
        processor_func: Callable[[T], U],
    ) -> tuple[list[U], list[dict[str, Any]]]:
        """
        Run a step in parallel across all items using joblib.

        Returns typed results without cast thanks to discriminated union pattern.

        Note:
            Sets `_pipeline_aborted = True` if all items fail.
            Returns empty lists if input is empty.
        """
        # Guard: empty input - skip step
        if not seq:
            logger.warning("Skipping %s: no flights to process", step_name)
            return [], []

        t0 = time.time()
        logger.info(
            "%s %d flights (n_jobs=%s)...",
            step_name.capitalize(),
            len(seq),
            self.cfg.njobs,
        )

        results: list[StepResult[U]] = Parallel(
            n_jobs=self.cfg.njobs,
            prefer=self.cfg.prefer,
            batch_size=self.cfg.batch_size,
        )(delayed(_process_one)(i, item, processor_func) for i, item in enumerate(seq))

        # Type-safe processing via discriminated union
        good_seq, error_records = _process_parallel_results(results, seq, step_name)

        if self.cfg.shutdown_executor_between_steps:
            get_reusable_executor().shutdown(wait=True)

        if self.cfg.gc_collect_between_steps:
            gc.collect()

        # Auto-abort if all flights failed
        if not good_seq and seq:
            logger.warning(
                "All %d flights failed at %s - aborting pipeline",
                len(seq),
                step_name,
            )
            self._pipeline_aborted = True

        logger.info("%s complete in %.2fs", step_name.capitalize(), time.time() - t0)
        return good_seq, error_records


    # -------------------------------------------------------------------------
    # Validation / filtering
    # -------------------------------------------------------------------------

    def _check_and_filter_failed_flights(
        self,
        seq: list[FlightT],
        critical_columns: tuple[str, ...],
        step_name: str,
    ) -> tuple[list[FlightT], list[dict[str, Any]]]:
        """
        Filter out flights that failed based on critical column checks.

        Generic over FlightT (bound to Flight) to preserve input type in output.
        """
        if not critical_columns:
            return seq, []

        successful: list[FlightT] = []
        errors: list[dict[str, Any]] = []

        for flight in seq:
            df = flight.dataframe
            flight_id = getattr(flight, "attrs", {}).get("flight_id", "UNKNOWN")

            msg = self._check_critical_columns(df, critical_columns)
            if msg:
                errors.append(_create_error_record(flight, flight_id, step_name, msg))
                logger.warning("Flight %s failed at %s: %s", flight_id, step_name, msg)
            else:
                successful.append(flight)

        if errors:
            logger.warning("%d/%d flights failed at %s", len(errors), len(seq), step_name)

        return successful, errors

    @staticmethod
    def _check_critical_columns(df: pd.DataFrame, critical_columns: tuple[str, ...]) -> str | None:
        for col in critical_columns:
            if col not in df.columns:
                return f"{col} (missing)"
            if df[col].isna().all():
                return f"{col} (all NaN)"
        return None

