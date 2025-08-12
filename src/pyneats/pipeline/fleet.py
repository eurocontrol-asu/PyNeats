# fleet.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import copy
import gc
import logging
import os
from typing import Any, Final, List

import pandas as pd

from pyneats.pipeline.flight import FlightRunner
from pyneats.steps.weather import DWDFactory, WeatherFactoryParams, WeatherProviderProtocol

logger = logging.getLogger(__name__)

NJOBS: Final[int] = 5


# ---------------------------
# Small configuration holder
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
    sample: int


# ---------------------------
# Helpers
# ---------------------------
def _extract_climate_payload(neats_flight: FlightRunner, df_flight: pd.DataFrame) -> dict[str, Any]:
    """
    Return a standalone dict with the climate payload from a processed FlightRunner.
    Ensures FLIGHT_ID is present in meta for easy grouping later.
    """
    current = neats_flight.current
    if current is None or "climate_impact" not in getattr(current, "attrs", {}):
        raise RuntimeError("No climate_impact found on the processed flight.")
    payload = copy.deepcopy(current.attrs["climate_impact"])
    fid = df_flight["FLIGHT_ID"].iloc[0] if "FLIGHT_ID" in df_flight else "UNKNOWN"
    payload.setdefault("meta", {})
    payload["meta"].setdefault("FLIGHT_ID", fid)
    return payload


def split_list(lst: List[Any], n: int) -> List[List[Any]]:
    """Split list `lst` into `n` nearly equal-sized chunks."""
    if n <= 0:
        return [lst]
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]



# ---------------------------
# Fleet runner
# ---------------------------
class FleetRunner:
    """
    Processes a fleet of flights (sequentially here; you can parallelize by chunking).
    One heavy weather object is built once and reused across flights.
    """

    def __init__(
        self,
        asofdate: datetime,
        timeofday: int,
        params: FleetRunnerParams,
        njobs: int = NJOBS,
    ) -> None:
        self.asofdate = asofdate
        self.timeofday = timeofday
        self.params = params
        self.njobs = njobs

        self.weather: WeatherProviderProtocol | None = None
        self.raw_trajectories: pd.DataFrame | None = None
        self.flights: List[pd.DataFrame] | None = None
        self.results: list[dict[str, Any]] | None = None

    # ----- public API -----
    def eval(self) -> "FleetRunner":
        """
        Run: load weather → load trajectories → process flights.
        Results end up in `self.results` (list of climate payload dicts).
        """
        self._get_weather()
        self._get_trajectories()
        self._process_loop()
        return self

    def results_as_dataframe(self) -> pd.DataFrame:
        """
        Flatten self.results into a tidy DataFrame:
        columns: FLIGHT_ID, species, horizon, GWP, CO2eq, error?
        """
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

    # ----- internals -----
    def _process_loop(self) -> None:
        if self.flights is None:
            raise RuntimeError("Flights not loaded. Call eval() which sets it up.")
        if self.weather is None:
            raise RuntimeError("Weather not loaded. Call eval() which sets it up.")

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

    def _get_weather(self) -> None:
        """
        Load weather data (heavy object) once, in the main process.
        """
        logger.info("Loading weather from %s", self.params.weather_folder)
        factory = DWDFactory(WeatherFactoryParams(data_dir=self.params.weather_folder))
        self.weather = factory(self.asofdate, self.timeofday)

    def _get_trajectories(self) -> None:
        self._get_raw_trajectories()
        self._filter_flights()

    def _get_raw_trajectories(self) -> None:
        filename = f"Flights_{self.asofdate.strftime('%Y%m%d')}.csv"
        file_path = os.path.join(self.params.trajectory_folder, filename)
        try:
            df = pd.read_csv(
                file_path,
                sep=";",
                decimal=",",
                dayfirst=True,
            )
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
        # Filter by model type
        df_model = df[df["MODEL_TYPE"] == self.params.model_type].copy()

        # Build FLIGHT_ID
        flight_id_cols = ["AIRCRAFT_ID", "ADEP", "ADES", "REGISTRATION"]
        df_model["FLIGHT_ID"] = df_model[flight_id_cols].astype(str).agg("_".join, axis=1)

        # Parse times
        timeover_parsed = pd.to_datetime(
            df_model["TIME_OVER"],
            format="%Y-%m-%d %H:%M:%S",
            errors="coerce",
        )
        df_model_sel = df_model.assign(TIMEOVER_PARSED=timeover_parsed)

        # First waypoint per flight → approximate departure time
        first_departure = (
            df_model_sel
            .sort_values(["FLIGHT_ID", "TIMEOVER_PARSED"])
            .groupby("FLIGHT_ID", as_index=False)
            .first()[["FLIGHT_ID", "TIMEOVER_PARSED"]]
            .rename(columns={"TIMEOVER_PARSED": "DEPARTURE_TIME"})
        )

        # Keep flights starting in the forecast window
        valid_flights = first_departure[
            (first_departure["DEPARTURE_TIME"] >= window_start) &
            (first_departure["DEPARTURE_TIME"] < window_end)
        ]["FLIGHT_ID"]

        selected = df_model[df_model["FLIGHT_ID"].isin(valid_flights)]

        # Optional sampling
        if self.params.sample!=0:
            sample_ids = valid_flights.head(self.params.sample)
            selected = selected[selected["FLIGHT_ID"].isin(sample_ids)]

        # One DataFrame per flight
        self.flights = [group for _, group in selected.groupby("FLIGHT_ID")]
        logger.info("Selected %d flights in window [%s, %s).",
                    len(self.flights), window_start, window_end)
