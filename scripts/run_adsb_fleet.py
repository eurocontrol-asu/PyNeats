"""
Run FleetRunnerLargeEmitter on ADS-B trajectory data.

Loads a NEATS-format JSON file (e.g. produced by parquet_to_neats_json.py)
and runs the full NEATS climate-impact pipeline. Prints a summary of how
many flights computed successfully vs. failed.

Usage
-----
    python scripts/run_adsb_fleet.py \
        --input  data/neats_from_parquet.json \
        --weather-path /path/to/weather \
        --bada-path /path/to/bada
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.weather.weather_store import ZarrPaths

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run FleetRunnerLargeEmitter on ADS-B trajectory data.",
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
    args = parser.parse_args()

    # --- 1. Validate inputs ---
    if not args.input.is_file():
        log.error("Input file not found: %s", args.input)
        sys.exit(1)

    with open(args.input) as f:
        input_flights = json.load(f)
    total_input = len(input_flights)
    log.info("Loaded %d flights from %s", total_input, args.input)

    # --- 2. Set up paths ---
    zarr_paths = create_zarr_paths(args.weather_path)
    log.info("Weather path: %s", args.weather_path)
    log.info("BADA path: %s", args.bada_path)

    # --- 3. Run pipeline ---
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(args.input),
        zarr_paths=zarr_paths,
        bada_path=str(args.bada_path),
        params={},
    )

    runner = FleetRunnerLargeEmitter(cfg)
    log.info("Starting FleetRunnerLargeEmitter.eval() ...")
    runner.eval()

    # --- 4. Report results ---
    succeeded = len(runner.fleet_with_climate_impact) if runner.fleet_with_climate_impact else 0
    errors = list(runner.error_records) if runner.error_records else []
    failed = len(errors)

    print()
    print("=" * 60)
    print("FleetRunnerLargeEmitter — ADS-B Results")
    print("=" * 60)
    print(f"  Input flights:     {total_input}")
    print(f"  Succeeded:         {succeeded}")
    print(f"  Failed:            {failed}")
    if total_input > 0:
        print(f"  Success rate:      {succeeded / total_input * 100:.1f}%")
    print("=" * 60)

    if errors:
        print()
        print("Failed flights:")
        print("-" * 60)
        for err in errors:
            fid = err.get("flight_id", "unknown")
            step = err.get("step_name", "unknown")
            msg = err.get("error_msg", str(err))
            print(f"  {fid:<15}  step={step:<20}  {msg}")

    if runner.results:
        print()
        print("Fleet metadata:")
        print(runner.results.get("fleet_meta_data", {}))


if __name__ == "__main__":
    main()
