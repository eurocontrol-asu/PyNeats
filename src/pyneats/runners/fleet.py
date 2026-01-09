"""
Optimized fleet-level orchestration of NEATS climate computations
that leverages vectorized operations for significant performance improvements.

- Single cfg object holding step names + params (RunnerConfig) + fleet settings (FastFleetRunnerConfig)
- Explicit, typed intermediate pipeline attributes (like FlightRunner)
- Decomposed pipeline into intermediate steps (like FlightRunner)
- Generic, registry-based step construction with per-process caching for joblib workers
- Continue-on-error behavior for per-flight steps, while keeping vectorized steps fleet-level
"""

from __future__ import annotations

import gc
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, TypeVar, cast

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from joblib.externals.loky import get_reusable_executor
from typing_extensions import Self

from pycontrails import Flight, Fleet
from pycontrails.models.cocip import Cocip
from pycontrails.models.humidity_scaling import HumidityScaling
from pycontrails.core.met import MetDataset

from pyneats.core.compute_parameters import (
    DEFAULT_NJOBS, 
    DEFAULT_BATCH_SIZE,
    DEFAULT_JOBLIB_PREFERENCE,
)

from pyneats.core.neats_default_parameters import (
    DEFAULT_COCIP_KWARGS,
    DEFAULT_HUMIDITY_SCALING,
    DEFAULT_LON_BUF,
    DEFAULT_LAT_BUF,
    DEFAULT_TIME_BUF,
    DEFAULT_LEVEL_BUF,
)

from pyneats.core.steps import Step  
from pyneats.core.steps_registry import build
from pyneats.runners.flight import RunnerConfig
from pyneats.steps.parsing.neats_parser import NEATSFuel

from pyneats.steps.climate_metrics.report import FleetReport

from pyneats.steps.parsing.neats_io import neats_json_to_flights, split_df_into_flights
from pyneats.steps.parsing.protocol import TrajectoryParser
from pyneats.steps.parsing.views import Flight4D

from pyneats.steps.interpolation.protocol import TrajectoryInterpolator

from pyneats.steps.weather.weather_provider import FlightWithWeather
from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr, clear_dataset_cache

from pyneats.steps.performance import PerformanceModel
from pyneats.steps.performance.views import FlightWithPerformance

from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.emissions.views import FlightWithEmissions

from pyneats.steps.climate_functions.protocol import NonCO2Model
from pyneats.steps.climate_functions.views import (
    FlightWithContrailsImpact,
    FlightWithNonCO2Impact
)

from pyneats.steps.climate_metrics.protocol import ClimateImpactModel
from pyneats.steps.climate_metrics.views import FlightWithClimateImpact




logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Types
# -----------------------------------------------------------------------------

T = TypeVar("T")
U = TypeVar("U")
ProcessorFunc = Callable[[T], U]

InT = TypeVar("InT", contravariant=True)
OutT = TypeVar("OutT", covariant=True)

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
    humidity_scaling: HumidityScaling | None = field(default_factory=
                                                     lambda: DEFAULT_HUMIDITY_SCALING)

    # Critical columns for vectorized-step failure detection
    weather_critical_columns: Tuple[str, ...] = (
        "air_temperature",
        "specific_humidity",
        "geopotential",
        "potential_vorticity",
    )
    humidity_scaling_critical_columns: Tuple[str, ...] = ()
    cocip_critical_columns: Tuple[str, ...] = ()

    def validate(self) -> None:
        if self.zarr_paths is None:
            raise ValueError("FastFleetRunnerConfig.zarr_paths is required")

        if self.trajectory_json_filepath is None and self.trajectory_dataframe is None:
            raise ValueError("Must provide either trajectory_json_filepath or trajectory_dataframe")


# -----------------------------------------------------------------------------
# Generic step cache (per-process) built on steps_registry.build()
# -----------------------------------------------------------------------------

# Each loky worker is a separate Python process => this cache is naturally per-process.
_STEP_CACHE: dict[tuple[type[Any], str, str], Any] = {}


def _get_step_cached(interface: type[Step[InT, OutT]],
                     name: str,
                     params: Mapping[str, Any]
                    ) -> Step[InT, OutT]:

    key = (interface, name.lower().strip())
    step = _STEP_CACHE.get(key)
    if step is None:
        step = build(interface, name, **dict(params))
        _STEP_CACHE[key] = step
    return cast(Step[InT, OutT], step)


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

def _extract_flight_id(item: Any) -> str:
    if hasattr(item, "attrs"):
        return getattr(item, "attrs", {}).get("flight_id", "UNKNOWN")
    return "UNKNOWN"


def _process_one(
    i: int,
    item: T,
    processor_func: ProcessorFunc[T, U],
    flight_id_extractor: Callable[[T], str],
) -> Tuple[bool, int, Optional[U], Optional[str], str]:
    
    flight_id = flight_id_extractor(item)
    try:
        out = processor_func(item)
        return True, i, out, None, flight_id
    except Exception as e:
        return False, i, None, repr(e), flight_id


def _create_error_record(
    original_flight: Any,
    flight_id: str,
    step_name: str,
    error_msg: Optional[str],
) -> Dict[str, Any]:
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
    results: List[Tuple[bool, int, Any, Optional[str], str]],
    original_seq: List[Any],
    step_name: str,
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    successful: List[Any] = []
    errors: List[Dict[str, Any]] = []

    for ok, i, out, err, flight_id in sorted(results, key=lambda x: x[1]):
        if ok:
            successful.append(out)
        else:
            errors.append(_create_error_record(original_seq[i], flight_id, step_name, err))
            logger.error("%s failed for flight %s (index %d): %s", step_name, flight_id, i, err)

    if errors:
        logger.warning("%d/%d flights failed at %s", len(errors), len(original_seq), step_name)

    return successful, errors


# -----------------------------------------------------------------------------
# FastFleetRunner (FlightRunner-like shape)
# -----------------------------------------------------------------------------

class FleetRunner:
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
        self.source_fleet: List[pd.DataFrame] | None = None
        self.parsed_fleet: List[Flight4D] | None = None
        self.interpolated_fleet: List[Flight4D] | None = None
        self.fleet_with_weather: List[FlightWithWeather] | None = None
        self.fleet_with_performance: List[FlightWithPerformance] | None = None
        self.fleet_with_emissions: List[FlightWithEmissions] | None = None
        self.fleet_with_contrails: List[FlightWithContrailsImpact] | None = None 
        self.fleet_with_nonco2: List[FlightWithNonCO2Impact] | None = None
        self.fleet_with_climate_impact: List[FlightWithClimateImpact] | None = None

        # Error aggregation (continue-on-error)
        self.error_records: List[Dict[str, Any]] = []

        # Final output
        self.results: Dict[str, Any] | None = None

        # ---- Step callables (registry-based, process-cached) -----------------
        self.parser = make_step_func(
            TrajectoryParser,
            self.cfg.trajectory_parser,
            self._params("trajectory_parser"),
            #self.cfg.params.get("trajectory_parser", {}),
            copy_input=True,  # DataFrame safety
        )

        self.interpolator = make_step_func(
            TrajectoryInterpolator,
            self.cfg.interpolator,
            self._params("interpolator"),
            #self.cfg.params.get("interpolator", {}),
        )

        self.performance = make_step_func(
            PerformanceModel,
            self.cfg.performance,
            self._params("performance", extra=self._bada_params()),
            #self.cfg.params.get("performance", {}),
        )

        self.emission = make_step_func(
            EmissionModel,
            self.cfg.emissions,
            self._params("emissions"),
            #self.cfg.params.get("emissions", {}),
        )

        self.non_co2_model = make_step_func(
            NonCO2Model,
            self.cfg.non_co2_model,
            #self.cfg.params.get("non_co2_model", {}),
            self._params("non_co2_model"),
        )

        self.climate_impact = make_step_func(
            ClimateImpactModel,
            self.cfg.climate_impact,
            self._params("climate_impact"),
        )

    # -------------------------------------------------------------------------
    # Param handling (FlightRunner-like)
    # -------------------------------------------------------------------------

    def _params(self, key: str, *, extra: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        """Return a defensive copy of cfg.params[key] merged with optional extra params."""
        base = dict(self.cfg.params.get(key, {}))
        if extra:
            base.update(dict(extra))
        return base

    def _bada_params(self) -> Dict[str, Any]:
        if self.cfg.bada_path is None:
            return {}
        return {
            "bada4_root_path": self.cfg.bada_path,
            "bada3_root_path": self.cfg.bada_path,
        }

    # -------------------------------------------------------------------------
    # FleetRunner stages (FlightRunner-like step decomposition)
    # -------------------------------------------------------------------------

    def _load_trajectories(self) -> Self:
        if self.cfg.trajectory_json_filepath is not None:
            path = Path(self.cfg.trajectory_json_filepath)
            logger.info("Loading trajectories from %s", path)
            with path.open("r", encoding="utf-8") as f:
                json_flights: List[Dict[str, Any]] = json.load(f)
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

        return self

    def _parse_flights(self) -> Self:

        start = time.time()

        if self.source_fleet is None:
            raise RuntimeError("source_flights must be loaded before _parse_flights()")

        self.parsed_fleet, errs = self._run_parallel_step(self.source_fleet, "parsing", self.parser)
        self.error_records.extend(errs)

        self.source_fleet = None  # free memory (FlightRunner-style)

        end = time.time()
        print("_parse_flights time", end - start)
        return self

    def _interpolate(self) -> Self:
        
        start = time.time()

        if self.parsed_fleet is None:
            raise RuntimeError("parsed_flights must be set before _interpolate()")

        self.interpolated_fleet, errs = self._run_parallel_step(self.parsed_fleet,
                                                     "interpolation",
                                                     self.interpolator)
        self.error_records.extend(errs)

        self.parsed_fleet = None  # free memory

        end = time.time()
        print("_interpolate time", end - start)

        return self

    def _intersect_weather(self) -> Self:

        start = time.time()

        if self.interpolated_fleet is None:
            raise RuntimeError("interpolated_flights must be set before _intersect_weather()")
        if self.met is None or self.wind is None:
            raise RuntimeError("weather must be loaded before _intersect_weather()")

        flights = self._fleet_weather_intersection(self.interpolated_fleet, self.met, self.wind)
        flights, errs = self._check_and_filter_failed_flights(
            flights,
            self.cfg.weather_critical_columns,
            "weather intersection",
        )
        self.error_records.extend(errs)

        self.fleet_with_weather = cast(List[FlightWithWeather], flights)
        self.interpolated_fleet = None  # free memory

        self.fleet_with_weather = self._apply_humidity_scaling(self.fleet_with_weather)
        self.fleet_with_weather, errs = self._check_and_filter_failed_flights(
            self.fleet_with_weather,
            self.cfg.humidity_scaling_critical_columns,
            "humidity scaling",
        )

        self.error_records.extend(errs)
        self.fleet_with_weather = cast(List[FlightWithWeather], self.fleet_with_weather)


        end = time.time()
        print("_intersect_weather time", end - start)
        
        return self

    def _performance(self) -> Self:

        start = time.time()

        if self.fleet_with_weather is None:
            raise RuntimeError("fleet_with_weather must be set before _performance()")

        self.fleet_with_performance, errs = self._run_parallel_step(self.fleet_with_weather,
                                             "performance",
                                             self.performance)
        self.error_records.extend(errs)

        self.fleet_with_weather = None  # free memory

        end = time.time()
        print("_performance time", end - start)

        return self

    def _emissions(self) -> Self:

        start = time.time()

        if self.fleet_with_performance is None:
            raise RuntimeError("_performance must be set before _emissions()")

        self.fleet_with_emissions, errs = self._run_parallel_step(self.fleet_with_performance,
                                             "emissions",
                                             self.emission)
        self.error_records.extend(errs)

        self.fleet_with_performance = None  # free memory

        end = time.time()
        print("_emissions time", end - start)

        return self

    def _contrails(self) -> Self:

        start = time.time()

        if self.fleet_with_emissions is None:
            raise RuntimeError("_emissions must be set before _contrails()")
        if self.met is None or self.rad is None:
            raise RuntimeError("weather must be loaded before _contrails()")

        flights: List[FlightWithContrailsImpact] = self._fleet_cocip(self.fleet_with_emissions,
                                                                     self.met,
                                                                     self.rad)
        flights, errs = self._check_and_filter_failed_flights(
            flights,
            self.cfg.cocip_critical_columns,
            "CoCiP evaluation",
        )
        self.error_records.extend(errs)

        self.fleet_with_contrails = flights
        self.fleet_with_emissions = None  # free memory

        end = time.time()
        print("_contrails time", end - start)
        return self
    
    def _nonco2(self) -> Self:

        start = time.time()

        if self.fleet_with_contrails is None:
            raise RuntimeError("_contrails must be set before _nonco2()")

        self.fleet_with_nonco2, errs = self._run_parallel_step(self.fleet_with_contrails,
                                             "non_co2_model",
                                             self.non_co2_model)
        self.error_records.extend(errs)

        self.fleet_with_contrails = None  # free memory

        end = time.time()
        print("_nonco2 time", end - start)

        return self
    
    def _climate_metrics(self) -> Self:

        start = time.time()

        if self.fleet_with_nonco2 is None:
            raise RuntimeError("_nonco2 must be set before _climate_metrics()")
        
        self.fleet_with_climate_impact, errs = self._run_parallel_step(self.fleet_with_nonco2,
                                             "climate_impact",
                                             self.climate_impact)
        self.error_records.extend(errs)

        self.fleet_with_nonco2 = None  # free memory

        end = time.time()
        print("_climate_metrics time", end - start)

        return self
    
    def _extract_results(self) -> Self:

        start = time.time()
        
        if self.fleet_with_climate_impact is None:
            raise RuntimeError("climate_impact must be set before _extract_results()")

        successful_results = [f.attrs['climate_impact'] for f in self.fleet_with_climate_impact]

        self.results = {
            "fleet_meta_data": FleetReport.collect(),
            "flight_results": successful_results + self.error_records,
        }

        end = time.time()
        print("_extract_results time", end - start)

        return self


    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------


    @staticmethod
    def _seq_to_fleet(seq: List[Flight]) -> Fleet:

        for s in seq:
            s.attrs['columns'] = set(s.data.keys())
            s["q_fuel"] = np.full(len(s), s.fuel.q_fuel)
            s["ei_h2o"] = np.full(len(s), s.fuel.ei_h2o)
            s.fuel = None

        fleet : Fleet = Fleet.from_seq(seq)
        fleet.attrs['columns'] = set(fleet.data.keys())
        return fleet
    
    @staticmethod
    def _fleet_to_seq(fleet: Fleet) -> List[Flight]:
        
        fleet_columns = fleet.attrs.pop('columns')
        seq = fleet.to_flight_list()
        
        for s in seq:
            flight_columns = s.attrs.pop('columns')
            columns_to_delete = fleet_columns.difference(flight_columns)

            for c in columns_to_delete:
                s.data.pop(c)
            s.fuel = NEATSFuel.from_attrs(s.attrs)

        return seq
    
    def eval(self) -> Self:
        """
        Run the full fast fleet pipeline.

        Mirrors FlightRunner chaining style, but preserves fleet semantics:
        - per-flight failures are recorded and filtered rather than raising and aborting.
        """
        logger.info("FastFleetRunner: starting pipeline")

        return (
            self._load_trajectories() # pylint: disable=protected-access
            ._load_weather() # pylint: disable=protected-access
            ._parse_flights() # pylint: disable=protected-access
            ._interpolate() # pylint: disable=protected-access
            ._intersect_weather() # pylint: disable=protected-access
            ._performance() # pylint: disable=protected-access
            ._emissions() # pylint: disable=protected-access
            ._contrails() # pylint: disable=protected-access
            ._nonco2() # pylint: disable=protected-access
            ._climate_metrics() # pylint: disable=protected-access
            ._extract_results() # pylint: disable=protected-access
            ._clean_memory()  # pylint: disable=protected-access
        )

    def _clean_memory(self) -> Self:

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

        for payload in (self.results['flight_results'] or []):
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
                for item in (block.get("value") or []):
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

    def _run_parallel_step(
        self,
        seq: List[T],
        step_name: str,
        processor_func: Callable[[T], U],
    ) -> Tuple[List[U], List[Dict[str, Any]]]:
        t0 = time.time()
        logger.info("%s %d flights (n_jobs=%s)...", step_name.capitalize(), len(seq), self.cfg.njobs)

        results = Parallel(
            n_jobs=self.cfg.njobs,
            prefer=self.cfg.prefer,
            batch_size=self.cfg.batch_size,
        )(
            delayed(_process_one)(i, item, processor_func, _extract_flight_id)
            for i, item in enumerate(seq)
        )

        good_seq, error_records = _process_parallel_results(results, seq, step_name)

        if self.cfg.shutdown_executor_between_steps:
            get_reusable_executor().shutdown(wait=True)

        if self.cfg.gc_collect_between_steps:
            gc.collect()

        logger.info("%s complete in %.2fs", step_name.capitalize(), time.time() - t0)
        return cast(List[U], good_seq), error_records

    # -------------------------------------------------------------------------
    # Vectorized fleet operations
    # -------------------------------------------------------------------------

    def _fleet_weather_intersection(self, seq: List[Flight4D], met: Any, wind: Any) -> List[Flight]:
        t0 = time.time()
        logger.info("Fleet-level weather intersection for %d flights...", len(seq))

        pyc_fleet = self._seq_to_fleet(seq)

        ds_met = pyc_fleet.downselect_met(
            met,
            longitude_buffer=DEFAULT_LON_BUF,
            latitude_buffer=DEFAULT_LAT_BUF,
            time_buffer=DEFAULT_TIME_BUF,
            level_buffer=DEFAULT_LEVEL_BUF,
        )

        ds_wind = pyc_fleet.downselect_met(
            wind,
            longitude_buffer=DEFAULT_LON_BUF,
            latitude_buffer=DEFAULT_LAT_BUF,
            time_buffer=DEFAULT_TIME_BUF,
            level_buffer=DEFAULT_LEVEL_BUF,
        )

        new_cols = self._intersect_weather_variables(pyc_fleet, ds_met, ds_wind)

        df = pyc_fleet.dataframe.reset_index(drop=True)
        for k, v in new_cols.items():
            df[k] = v

        fleet_with_weather = Fleet(data=df, attrs=pyc_fleet.attrs, fl_attrs=pyc_fleet.fl_attrs)

        logger.info("Weather intersection complete in %.2fs", time.time() - t0)
        return self._fleet_to_seq(fleet_with_weather)

    @staticmethod
    def _intersect_weather_variables(fleet: Fleet,
                                     ds_met: Any,
                                     ds_wind: Any) -> Dict[str, np.ndarray]:
        var_map = {
            "eastward_wind": ("u_wind", True),
            "northward_wind": ("v_wind", True),
            "air_temperature": ("air_temperature", False),
            "specific_humidity": ("specific_humidity", False),
            "geopotential": ("geopotential", False),
            "potential_vorticity": ("potential_vorticity", False),
        }

        new_cols: Dict[str, np.ndarray] = {}

        for met_var, (out_col, is_wind) in var_map.items():
            if is_wind:
                if met_var in ds_wind:
                    dataset = ds_wind
                elif met_var in ds_met:
                    dataset = ds_met
                else:
                    raise KeyError(f"required wind var '{met_var}' missing (looked in WIND then MET)")
            else:
                if met_var in ds_met:
                    dataset = ds_met
                else:
                    raise KeyError(f"required met var '{met_var}' missing in MET")

            vals = fleet.intersect_met(dataset[met_var], method="linear", use_indices=False)
            if is_wind:
                vals = np.nan_to_num(vals, nan=0.0)

            new_cols[out_col] = vals

        return new_cols

    def _apply_humidity_scaling(self, seq: List[FlightWithWeather]) -> List[FlightWithWeather]:
        if self.cfg.humidity_scaling is None:
            return seq

        t0 = time.time()
        logger.info("Applying humidity scaling...")

        fleet = self._seq_to_fleet(seq)
        fleet = self.cfg.humidity_scaling.eval(fleet)

        logger.info("Humidity scaling complete in %.2fs", time.time() - t0)
        return self._fleet_to_seq(fleet)

    def _fleet_cocip(
        self,
        seq: List[FlightWithEmissions],
        met: Any,
        rad: Any,
    ) -> List[FlightWithContrailsImpact]:
        
        logger.info("Fleet-level CoCiP evaluation for %d flights...", len(seq))

        cocip = Cocip(met=met, rad=rad, **self.cfg.cocip_kwargs)
        fleet = self._seq_to_fleet(seq)
        results_fleet = cocip.eval(source=fleet)

        out = self._fleet_to_seq(results_fleet)

        # Zero-copy validation + type narrowing
        typed = [FlightWithContrailsImpact.from_flight(f) for f in out]

        return typed

    # -------------------------------------------------------------------------
    # Validation / filtering
    # -------------------------------------------------------------------------

    def _check_and_filter_failed_flights(
        self,
        seq: List[Flight],
        critical_columns: Tuple[str, ...],
        step_name: str,
    ) -> Tuple[List[Flight], List[Dict[str, Any]]]:
        if not critical_columns:
            return seq, []

        successful: List[Flight] = []
        errors: List[Dict[str, Any]] = []

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
    def _check_critical_columns(df: pd.DataFrame, critical_columns: Tuple[str, ...]) -> Optional[str]:
        for col in critical_columns:
            if col not in df.columns:
                return f"{col} (missing)"
            if df[col].isna().all():
                return f"{col} (all NaN)"
        return None

    