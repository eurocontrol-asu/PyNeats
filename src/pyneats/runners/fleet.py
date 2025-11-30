# fleet.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import gc
import logging
import os
from typing import Any, Final, List, Optional, Mapping, Iterable, cast, Dict
import json
from itertools import chain
import itertools
import pandas as pd
from joblib import Parallel, delayed

from pyneats.runners.flight import FlightRunner

from pyneats.steps.weather.weather_store import (
    ZarrPaths,              # central, shared definition
    get_weather_from_zarr,  # centralized Zarr opener (+ per-process cache)
)

from pyneats.steps.parsing.neats_io import (
    neats_json_to_flights,
    split_df_into_flights,
)

from pyneats.steps.climate_metrics.report import FleetReport

logger = logging.getLogger(__name__)

DEFAULT_NJOBS: Final[int] = 30
DEFAULT_FLIGHT_CHUNK: Final[int] = 16  # tune 8–32
DEFAULT_BATCH_SIZE: Final[int] = 4  # joblib batch size
DEFAULT_SAMPLE: Final[int] = 0 # 0 = all flights

# ---------------------------
# Configuration holder
# ---------------------------

@dataclass(frozen=True)
class FleetRunnerParams:
    """
    Immutable container for fleet configuration.
    """
    #weather_folder: str
    trajectory_json_filepath: Optional[str] = None
    trajectory_dataframe: Optional[pd.DataFrame] = None
    sample: int = DEFAULT_SAMPLE
    batch_size: int = DEFAULT_BATCH_SIZE # joblib batch size
    # If provided, enables parallel mode that opens weather lazily from Zarr in workers.
    zarr_paths: Optional[ZarrPaths] = None
    # Optional read-time chunks for workers opening zarr; leave None to keep native chunks
    zarr_read_chunks: Optional[Mapping[str, int]] = None
    njobs: int = DEFAULT_NJOBS,
    flight_chunk: int = DEFAULT_FLIGHT_CHUNK,
    bada_path: Optional[str] = None,


# ---------------------------
# Helpers
# ---------------------------


def _split_chunks(seq: List[Any], k: int) -> Iterable[List[Any]]:
    it = iter(seq)
    while True:
        batch = list(itertools.islice(it, k))
        if not batch:
            break
        yield batch


# ---------------------------
# Fleet runner
# ---------------------------

class FleetRunner:
    """
    Processes a fleet of flights:
      - Sequential mode (default): build WeatherProvider once and loop.
      - Parallel mode (if params.zarr_paths is provided and njobs > 1):
        each worker opens Zarr via weather_store.get_weather_from_zarr,
        which handles consolidation auto-detect + per-process caching.
    """

    flights: Optional[List[pd.DataFrame]] = None
    results: Optional[List[dict[str, Any]]] = None

    def __init__(
        self,
        params: FleetRunnerParams,
    ) -> None:
        self.params = params
        self.njobs = max(1, self.params.njobs)
        self.flight_chunk = max(1, self.params.flight_chunk)
        self.raw_trajectories = None
        self.results  = None

    # ----- public API -----
    def eval(self) -> "FleetRunner":
        """Run: load trajectories → weather (sequential only) → process flights."""
        self._get_trajectories()

        logger.info("Fleet: running in PARALLEL (n_jobs=%d)...", self.njobs)
        self._process_parallel()

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
                    key_agwp = f"{species}_{horizon}_AGWP_J_per_m2"
                    key_co2eq = f"{species}_{horizon}_CO2eq_kg"

                    row[key_agwp] = item.get("AGWP_J_per_m2")
                    row[key_co2eq] = item.get("CO2eq_kg")

            rows.append(row)

        return pd.DataFrame(rows)

    # ----- mode selection -----
    def _use_parallel(self) -> bool:
        return self.params.zarr_paths is not None and self.njobs > 1

    

    # ----- parallel path -----
    def _process_parallel(self) -> None:
        
        if self.flights is None:
            raise RuntimeError("Flights not loaded.")
        zp = self.params.zarr_paths
        assert zp is not None  # guarded by _use_parallel()

        # Avoid BLAS oversubscription; let processes do the parallelism
        for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                  "NUMEXPR_NUM_THREADS", "BLOSC_NTHREADS"):
            os.environ.setdefault(v, "1")


        chunks = self.params.zarr_read_chunks  # None → keep native zarr chunks

        def _process_chunk(flight_dfs: list[pd.DataFrame]) -> list[dict[str, Any]]:
            # This call uses weather_store's per-process cache transparently
            wp = get_weather_from_zarr(zp, chunks=chunks)
            out = []
            for df_flight in flight_dfs:
                try:
                    neats_flight = FlightRunner(weather=wp, bada_path=self.params.bada_path)
                    neats_flight.source = df_flight
                    neats_flight.eval()
                    output = neats_flight.flight_with_climate_impact.attrs['climate_impact']
                    out.append(output)

                except Exception as e:
                    fid = df_flight["flight_id"].iloc[0] if "flight_id" in df_flight else "UNKNOWN"
                    logger.error("[worker] Error processing flight %s: %s", fid, e)
                    out.append({"meta": {"flight_id": fid}, "error": str(e)})
                    
            gc.collect()
            return out

        flight_chunks = list(_split_chunks(self.flights, self.flight_chunk))
        logger.info("Submitting %d chunks (~%d flights/chunk) to %d workers …",
                    len(flight_chunks), self.flight_chunk, self.njobs)

        raw: Any = Parallel(
            n_jobs=self.njobs,
            prefer="processes",
            batch_size=self.params.batch_size,  
            verbose=10,
        )(delayed(_process_chunk)(c) for c in flight_chunks)
        nested = cast(list[list[dict[str, Any]]], raw)

        self.results = list(chain.from_iterable(nested))

        self.results = {
            "fleet_meta_data": FleetReport.collect(),
            "flight_results" : self.results,}


    # ----- load trajectories (shared) -----

    def _get_trajectories(self) -> None:
        
        if self.params.trajectory_json_filepath is not None:
           self._get_trajectories_from_json()
        elif self.params.trajectory_dataframe is not None:
            self._get_trajectories_from_dataframe()
        else:
            logger.info("No trajectory source provided in FleetRunnerParams.")


    def _get_trajectories_from_dataframe(self) -> None:

        try:
            df = self.params.trajectory_dataframe
            self.flights = split_df_into_flights(df)
            logger.info("Loaded %d trajectories from DataFrame", len(self.flights))
        except Exception as e:
            logger.error("Error loading trajectory DataFrame: %s", e)


    def _get_trajectories_from_json(self) -> None:

        path = Path(self.params.trajectory_json_filepath)

        try:
            with path.open("r", encoding="utf-8") as f:
                json_flights: List[Dict[str, Any]] = json.load(f)
                self.flights = neats_json_to_flights(json_flights)
                logger.info("Loaded %d trajectories from %s", len(self.flights), path)
        except FileNotFoundError:
            logger.error("Trajectory file not found: %s", path)
            self.flights = pd.DataFrame()
        
