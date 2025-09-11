# fleet.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import copy
import gc
import logging
import os
from typing import Any, Final, List, Optional, Mapping, Iterable
import itertools

import pandas as pd
from joblib import Parallel, delayed

from pyneats.pipeline.flight import FlightRunner
from pyneats.steps.weather import (
    DWDFactory,
    WeatherFactoryParams,
    WeatherProviderProtocol,
)
from pyneats.steps.weather.weather_store import (
    ZarrPaths,              # central, shared definition
    get_weather_from_zarr,  # centralized Zarr opener (+ per-process cache)
)

logger = logging.getLogger(__name__)

DEFAULT_NJOBS: Final[int] = 5
DEFAULT_FLIGHT_CHUNK: Final[int] = 16  # tune 8–32


# ---------------------------
# Configuration holder
# ---------------------------

@dataclass(frozen=True)
class FleetRunnerParams:
    """
    Immutable container for fleet configuration.
    """
    model_type: str
    weather_folder: str
    trajectory_folder: str
    forecast_window: int  # hours
    sample: int = 0
    # If provided, enables parallel mode that opens weather lazily from Zarr in workers.
    zarr_paths: Optional[ZarrPaths] = None
    # Optional read-time chunks for workers opening zarr; leave None to keep native chunks
    zarr_read_chunks: Optional[Mapping[str, int]] = None


# ---------------------------
# Helpers
# ---------------------------

def _extract_climate_payload(neats_flight: FlightRunner, df_flight: pd.DataFrame) -> dict[str, Any]:
    current = neats_flight.current
    if current is None or "climate_impact" not in getattr(current, "attrs", {}):
        raise RuntimeError("No climate_impact found on the processed flight.")
    payload = copy.deepcopy(current.attrs["climate_impact"])
    fid = df_flight["FLIGHT_ID"].iloc[0] if "FLIGHT_ID" in df_flight else "UNKNOWN"
    payload.setdefault("meta", {})
    payload["meta"].setdefault("FLIGHT_ID", fid)
    return payload

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

    def __init__(
        self,
        asofdate: datetime,
        timeofday: int,
        params: FleetRunnerParams,
        njobs: int = DEFAULT_NJOBS,
        flight_chunk: int = DEFAULT_FLIGHT_CHUNK,
    ) -> None:
        self.asofdate = asofdate
        self.timeofday = timeofday
        self.params = params
        self.njobs = max(1, njobs)
        self.flight_chunk = max(1, flight_chunk)

        self.weather: WeatherProviderProtocol | None = None
        self.raw_trajectories: pd.DataFrame | None = None
        self.flights: List[pd.DataFrame] | None = None
        self.results: list[dict[str, Any]] | None = None

    # ----- public API -----
    def eval(self) -> "FleetRunner":
        """Run: load trajectories → weather (sequential only) → process flights."""
        self._get_trajectories()
        if self._use_parallel():
            logger.info("Fleet: running in PARALLEL (n_jobs=%d)...", self.njobs)
            self._process_parallel()
        else:
            logger.info("Fleet: running SEQUENTIALLY...")
            self._get_weather()
            self._process_sequential()
        return self

    def results_as_dataframe(self) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for payload in (self.results or []):
            if "error" in payload:
                rows.append({
                    "FLIGHT_ID": payload.get("meta", {}).get("FLIGHT_ID", "UNKNOWN"),
                    "species": "ERROR",
                    "horizon": None,
                    "GWP": None,
                    "CO2eq": None,
                    "error": payload["error"],
                })
                continue

            fid = payload.get("meta", {}).get("FLIGHT_ID", "UNKNOWN")
            for block in payload.get("results", []):
                species = block.get("species")
                for item in block.get("value", []):
                    rows.append({
                        "FLIGHT_ID": fid,
                        "species": species,
                        "horizon": item.get("horizon"),
                        "GWP": item.get("GWP"),
                        "CO2eq": item.get("CO2eq"),
                    })
        return pd.DataFrame(rows)

    # ----- mode selection -----
    def _use_parallel(self) -> bool:
        return self.params.zarr_paths is not None and self.njobs > 1

    # ----- sequential path -----
    def _process_sequential(self) -> None:
        if self.flights is None:
            raise RuntimeError("Flights not loaded.")
        if self.weather is None:
            raise RuntimeError("Weather not loaded.")

        self.results = []
        logger.info("Processing %d flights …", len(self.flights))
        for df_flight in self.flights:
            try:
                neats_flight = FlightRunner(weather=self.weather)
                neats_flight.source = df_flight
                neats_flight.eval()
                self.results.append(_extract_climate_payload(neats_flight, df_flight))
            except Exception as e:
                fid = df_flight["FLIGHT_ID"].iloc[0] if "FLIGHT_ID" in df_flight else "UNKNOWN"
                logger.error("Error processing flight %s: %s", fid, e)
                self.results.append({"meta": {"FLIGHT_ID": fid}, "error": str(e)})
            finally:
                gc.collect()

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

        # Time window slicing (reduces dask graph size in workers)
        window_start = (self.asofdate + timedelta(hours=self.timeofday)).strftime("%Y-%m-%d %H:%M:%S")
        window_end = (self.asofdate + timedelta(hours=self.timeofday + self.params.forecast_window)).strftime("%Y-%m-%d %H:%M:%S")
        chunks = self.params.zarr_read_chunks  # None → keep native zarr chunks

        def _process_chunk(flight_dfs: list[pd.DataFrame]) -> list[dict[str, Any]]:
            # This call uses weather_store's per-process cache transparently
            wp = get_weather_from_zarr(zp, t0=window_start, t1=window_end, chunks=chunks)
            #out: list[dict[str, Any]] = []
            out = []
            for df_flight in flight_dfs:
                try:
                    neats_flight = FlightRunner(weather=wp)
                    neats_flight.source = df_flight
                    neats_flight.eval()
                    out.append(_extract_climate_payload(neats_flight, df_flight))
                    #out.append([df_flight["FLIGHT_ID"].iloc[0]] + list(neats_flight.flight_with_contrails.to_dataframe()[['fuel_flow','fuel_burn','ef']].sum()))

                except Exception as e:
                    fid = df_flight["FLIGHT_ID"].iloc[0] if "FLIGHT_ID" in df_flight else "UNKNOWN"
                    logger.error("[worker] Error processing flight %s: %s", fid, e)
                    out.append({"meta": {"FLIGHT_ID": fid}, "error": str(e)})
                    #out.append([fid, 'ERROR', 'ERROR', str(e)])
            gc.collect()
            return out

        flight_chunks = list(_split_chunks(self.flights, self.flight_chunk))
        logger.info("Submitting %d chunks (~%d flights/chunk) to %d workers …",
                    len(flight_chunks), self.flight_chunk, self.njobs)

        nested = Parallel(
            n_jobs=self.njobs,
            prefer="processes",
            batch_size=1,   # we already chunked
            verbose=10,
        )(delayed(_process_chunk)(chunk) for chunk in flight_chunks)

        self.results = [r for sub in nested for r in sub]

    # ----- load weather (sequential only) -----
    def _get_weather(self) -> None:
        logger.info("Loading weather from %s", self.params.weather_folder)
        factory = DWDFactory(WeatherFactoryParams(data_dir=self.params.weather_folder))
        self.weather = factory(self.asofdate, self.timeofday)

    # ----- load trajectories (shared) -----
    def _get_trajectories(self) -> None:
        self._get_raw_trajectories()
        self._filter_flights()

    def _get_raw_trajectories(self) -> None:
        filename = f"Flights_{self.asofdate.strftime('%Y%m%d')}.csv"
        file_path = os.path.join(self.params.trajectory_folder, filename)
        try:
            df = pd.read_csv(file_path, sep=";", decimal=",", dayfirst=True)
            logger.info("Loaded %d trajectory rows from %s", len(df), file_path)
        except FileNotFoundError:
            logger.error("Trajectory file not found: %s", file_path)
            df = pd.DataFrame()
        self.raw_trajectories = df

    def _filter_flights(self) -> None:
        if self.raw_trajectories is None or self.raw_trajectories.empty:
            logger.warning("No trajectories loaded; nothing to process.")
            self.flights = []
            return

        window_start = self.asofdate + timedelta(hours=self.timeofday)
        window_end = window_start + timedelta(hours=self.params.forecast_window)

        df = self.raw_trajectories
        df_model = df[df["MODEL_TYPE"] == self.params.model_type].copy()
        #df_model = df_model[df_model["AIRCRAFT_TYPE_ICAO_ID"]=="A320"].copy()

        flight_id_cols = ["AIRCRAFT_ID", "ADEP", "ADES", "REGISTRATION"]
        df_model["FLIGHT_ID"] = df_model[flight_id_cols].astype(str).agg("_".join, axis=1)

        #timeover_parsed = pd.to_datetime(df_model["TIME_OVER"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
        #df_model_sel = df_model.assign(TIMEOVER_PARSED=timeover_parsed)

        #first_departure = (
        #    df_model_sel
        #    .sort_values(["FLIGHT_ID", "TIMEOVER_PARSED"])
        #    .groupby("FLIGHT_ID", as_index=False)
        #    .first()[["FLIGHT_ID", "TIMEOVER_PARSED"]]
        #    .rename(columns={"TIMEOVER_PARSED": "DEPARTURE_TIME"})
        #)

        #valid_flights = first_departure[
        #    (first_departure["DEPARTURE_TIME"] >= window_start) &
        #    (first_departure["DEPARTURE_TIME"] < window_end)
        #]["FLIGHT_ID"]

        valid_flights = df_model["FLIGHT_ID"].drop_duplicates()
        selected = df_model[df_model["FLIGHT_ID"].isin(valid_flights)]


        if self.params.sample:
            sample_ids = valid_flights.head(self.params.sample)
            selected = selected[selected["FLIGHT_ID"].isin(sample_ids)]

        self.flights = [group for _, group in selected.groupby("FLIGHT_ID")]
        logger.info("Selected %d flights in window [%s, %s).",
                    len(self.flights), window_start, window_end)
