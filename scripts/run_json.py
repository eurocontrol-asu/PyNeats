"""
Run the NEATS climate-impact pipeline on ADS-B trajectory data.

Supports two execution modes:
  fleet  — FleetRunnerLargeEmitter (vectorized, parallel, fault-tolerant)
  flight — FlightRunnerLargeEmitter per flight in a loop (sequential)

Usage
-----
    python scripts/run_json.py \
        --input  data/neats_from_parquet.json \
        --weather-path /path/to/weather \
        --bada-path /path/to/bada \
        --mode fleet
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.flight import RunnerConfig
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.runners.large_emitter import FlightRunnerLargeEmitter
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.weather.weather_store import ZarrPaths
from pyneats.steps.weather.weather_store import get_weather_from_zarr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_zarr_paths(weather_path: Path) -> ZarrPaths:
    """Create ZarrPaths from weather directory."""
    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"

    if not met_store.is_dir():
        raise FileNotFoundError(f"Met store not found: {met_store}")
    if not rad_store.is_dir():
        raise FileNotFoundError(f"Rad store not found: {rad_store}")
    if not wind_store.is_dir():
        log.warning("Wind store not found: %s (optional)", wind_store)
        wind_store = None  # type: ignore[assignment]

    return ZarrPaths(met_store, rad_store, wind_store)


def _print_summary(
    runner_name: str,
    total: int,
    succeeded: int,
    errors: list[dict[str, Any]],
) -> None:
    """Print a summary report (shared by both modes)."""
    print()
    print("=" * 60)
    print(f"{runner_name} — Results")
    print("=" * 60)
    print(f"  Input flights:     {total}")
    print(f"  Succeeded:         {succeeded}")
    print(f"  Failed:            {len(errors)}")
    if total > 0:
        print(f"  Success rate:      {succeeded / total * 100:.1f}%")
    print("=" * 60)

    if errors:
        print()
        print("Failed flights:")
        print("-" * 60)
        for err in errors:
            fid = err.get("flight_id", "unknown")
            msg = err.get("error", err.get("error_msg", str(err)))
            step = err.get("step_name", "")
            detail = f"step={step:<20}  {msg}" if step else msg
            print(f"  {fid:<15}  {detail}")


# ---------------------------------------------------------------------------
# Fleet mode
# ---------------------------------------------------------------------------


def run_fleet(
    input_flights: list[dict[str, Any]],
    input_path: Path,
    zarr_paths: ZarrPaths,
    bada_path: str,
) -> None:
    """Run all flights through FleetRunnerLargeEmitter (vectorized batch)."""
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(input_path),
        zarr_paths=zarr_paths,
        bada_path=bada_path,
        params={},
    )

    runner = FleetRunnerLargeEmitter(cfg)
    log.info("Starting FleetRunnerLargeEmitter.eval() ...")
    runner.eval()

    succeeded = (
        len(runner.fleet_with_climate_impact)
        if runner.fleet_with_climate_impact
        else 0
    )
    errors = list(runner.error_records) if runner.error_records else []

    _print_summary("FleetRunnerLargeEmitter", len(input_flights), succeeded, errors)

    if runner.results:
        print()
        print("Fleet metadata:")
        print(runner.results.get("fleet_meta_data", {}))


# ---------------------------------------------------------------------------
# Flight mode
# ---------------------------------------------------------------------------


def run_flight_loop(
    input_flights: list[dict[str, Any]],
    zarr_paths: ZarrPaths,
    bada_path: str,
) -> None:
    """Run each flight individually through FlightRunnerLargeEmitter."""
    # 1. Load weather once (shared across all flights)
    weather = get_weather_from_zarr(zarr_paths)
    log.info("Weather loaded for flight-mode execution")

    # 2. Convert JSON dicts → list[pd.DataFrame]
    flight_dfs = neats_json_to_flights(input_flights)
    log.info("Converted %d flights from JSON", len(flight_dfs))

    # 3. Loop over flights
    succeeded = 0
    errors: list[dict[str, Any]] = []

    cfg = RunnerConfig(
        params={
            "performance": {
                "bada4_root_path": bada_path,
                "bada3_root_path": bada_path,
            },
        },
    )

    for i, df in enumerate(flight_dfs):
        fid = df.attrs.get("flight_id", f"flight_{i}")
        log.info("[%d/%d] Processing %s ...", i + 1, len(flight_dfs), fid)
        try:
            runner = FlightRunnerLargeEmitter(
                weather=weather,
                source=df,
                cfg=cfg,
                bada_path=bada_path,
            )
            runner.eval()
            succeeded += 1
            log.info("[%d/%d] %s — OK", i + 1, len(flight_dfs), fid)
        except Exception as exc:
            log.error("[%d/%d] %s — FAILED: %s", i + 1, len(flight_dfs), fid, exc)
            errors.append({"flight_id": fid, "error": str(exc)})

    # 4. Print summary
    _print_summary("FlightRunnerLargeEmitter", len(flight_dfs), succeeded, errors)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the NEATS pipeline on ADS-B trajectory data.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/neats_from_parquet.json"),
        help="Path to the input NEATS JSON file.",
    )
    parser.add_argument(
        "--weather-path",
        type=Path,
        required=True,
        help="Path to weather data directory (containing icon_met.zarr, icon_rad.zarr).",
    )
    parser.add_argument(
        "--bada-path",
        type=Path,
        required=True,
        help="Path to BADA data directory.",
    )
    parser.add_argument(
        "--mode",
        choices=["fleet", "flight"],
        default="fleet",
        help="Execution mode: 'fleet' (vectorized batch) or 'flight' (sequential loop).",
    )
    args = parser.parse_args()

    # --- Validate inputs ---
    if not args.input.is_file():
        log.error("Input file not found: %s", args.input)
        sys.exit(1)

    with open(args.input) as f:
        input_flights = json.load(f)
    log.info("Loaded %d flights from %s", len(input_flights), args.input)

    # --- Set up weather paths ---
    zarr_paths = create_zarr_paths(args.weather_path)
    log.info("Weather path: %s", args.weather_path)
    log.info("BADA path: %s", args.bada_path)

    # --- Dispatch ---
    if args.mode == "fleet":
        run_fleet(input_flights, args.input, zarr_paths, str(args.bada_path))
    else:
        run_flight_loop(input_flights, zarr_paths, str(args.bada_path))


if __name__ == "__main__":
    main()
