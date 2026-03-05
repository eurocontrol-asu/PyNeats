"""
Performance-Only Fleet Runner Module

Runs the standard fleet pipeline up through the performance step, then stops.
Does not compute emissions, contrails, or climate impact.

Classes
-------
FleetRunnerPerformanceOnly
    Stops after _performance() and serialises fuel_flow / aircraft_mass /
    true_airspeed trajectory vectors as JSON.
"""

from __future__ import annotations

import logging
import math
from typing import Any
from typing import Self

from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.climate_metrics.report import FleetReport
from pyneats.steps.weather.weather_store import clear_dataset_cache


logger = logging.getLogger(__name__)

__all__ = ["FleetRunnerPerformanceOnly"]

# Columns to extract from each FlightWithPerformance trajectory
_PERF_VECTOR_COLS = ("fuel_flow", "aircraft_mass", "true_airspeed", "engine_efficiency")

# Flight-level attrs included in the output
_META_ATTRS = (
    "flight_id",
    "departure_airport",
    "arrival_airport",
    "aobt",
    "aircraft_type",
    "engine_uid",
)


def _to_list_or_null(series: Any) -> list[float | None]:
    """Convert a pandas Series (or array-like) to a JSON-safe list."""
    result: list[float | None] = []
    for v in series:
        try:
            f = float(v)
            result.append(None if math.isnan(f) else f)
        except (TypeError, ValueError):
            result.append(None)
    return result


class FleetRunnerPerformanceOnly(FleetRunnerLargeEmitter):
    """
    Fleet runner that stops after the performance step.

    Runs: load → parse → interpolate → weather → performance → extract

    Skips: emissions, contrails, non-CO2, climate metrics.

    Output (``self.results``) follows the standard shape::

        {
            "fleet_meta_data": {...},
            "flight_results": [
                {
                    "flight_information": {
                        "flight_id": "...",
                        "departure_airport": "...",
                        "arrival_airport": "...",
                        "aobt": "...",
                        "aircraft_type": "...",
                        "engine_uid": "...",  # only if present
                    },
                    "performance": {
                        "timestamps": ["2025-01-01T10:00:00+00:00", ...],
                        "fuel_flow": [1.2, 1.3, null, ...],
                        "aircraft_mass": [70000.0, 69950.0, ...],
                        "true_airspeed": [240.0, 245.0, ...],
                        "engine_efficiency": [0.35, 0.36, null, ...],
                    },
                },
                ...,
            ],
        }

    Error records (flights that failed during parsing / weather / performance)
    are included in ``flight_results`` with an ``"error"`` key, exactly as in
    the full pipeline.
    """

    def __init__(self, cfg: FleetRunnerParams) -> None:
        super().__init__(cfg)

    # ------------------------------------------------------------------
    # No-op overrides for steps we do not run
    # ------------------------------------------------------------------

    def _emissions(self) -> Self:
        return self

    def _climate_impact(self) -> Self:
        return self

    def _climate_metrics(self) -> Self:
        return self

    # ------------------------------------------------------------------
    # Result extraction
    # ------------------------------------------------------------------

    def _extract_results(self) -> Self:
        # Aborted pipeline (all flights failed upstream)
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

        if self.fleet_with_performance is None:
            raise RuntimeError(
                "fleet_with_performance is None; did _performance() run successfully?"
            )

        successful_results: list[dict[str, Any]] = []

        for flight in self.fleet_with_performance:
            attrs = getattr(flight, "attrs", {}) or {}
            df = flight.dataframe

            # --- flight metadata ---
            flight_info: dict[str, Any] = {
                k: attrs[k] for k in _META_ATTRS if k in attrs
            }

            # --- trajectory vectors ---
            timestamps: list[str | None] = []
            if "time" in df.columns:
                for t in df["time"]:
                    try:
                        timestamps.append(t.isoformat())
                    except AttributeError:
                        timestamps.append(str(t) if t is not None else None)

            perf: dict[str, Any] = {"timestamps": timestamps}
            for col in _PERF_VECTOR_COLS:
                if col in df.columns:
                    perf[col] = _to_list_or_null(df[col])

            successful_results.append(
                {"flight_information": flight_info, "performance": perf}
            )

        self.results = {
            "fleet_meta_data": FleetReport.collect(),
            "flight_results": successful_results + self.error_records,
        }

        clear_dataset_cache()
        return self
