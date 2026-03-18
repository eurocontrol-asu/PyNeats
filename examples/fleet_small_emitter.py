import argparse
import os
import sys

from pyneats.runners.small_emitter import FleetRunnerSmallEmitter
from pyneats.runners.small_emitter import SmallFleetRunnerParams
from pyneats.steps.weather.weather_store import ZarrPaths


def main():
    """
    Run fleet-level climate impact computations for small emitters (OpenAirClim).

    This example demonstrates how to use the FleetRunnerSmallEmitter to compute
    climate impacts for a fleet of flights using the OpenAirClim pipeline.

    Unlike the large-emitter pipeline, this runner does NOT use CoCiP (no
    weather-based contrail modelling).  It requires a temporary directory for
    the OpenAirClim file I/O.
    """
    parser = argparse.ArgumentParser(
        description="Fleet-level climate impact computation for small emitters (OpenAirClim)"
    )
    parser.add_argument(
        "--json-file",
        required=True,
        help="Path to JSON file containing flight trajectories",
    )
    parser.add_argument(
        "--weather-path",
        required=True,
        help="Path to meteorological data directory (containing icon_met.zarr, icon_rad.zarr, etc.)",
    )
    parser.add_argument(
        "--bada-path",
        required=True,
        help="Path to BADA (Base of Aircraft Data) directory",
    )
    parser.add_argument(
        "--tmp-dir",
        required=True,
        help="Path to a temporary directory for OpenAirClim file I/O",
    )
    parser.add_argument(
        "--airport-fuel-path",
        default=None,
        help="Optional path to a CSV or JSON file mapping airport codes to fuel properties",
    )
    parser.add_argument(
        "--njobs", type=int, default=2, help="Number of parallel jobs (default: 2)"
    )

    args = parser.parse_args()

    # Validate paths
    if not os.path.isfile(args.json_file):
        print(f"ERROR: JSON file does not exist: {args.json_file}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(args.weather_path):
        print(
            f"ERROR: Weather path does not exist: {args.weather_path}", file=sys.stderr
        )
        sys.exit(1)
    if not os.path.isdir(args.bada_path):
        print(f"ERROR: BADA path does not exist: {args.bada_path}", file=sys.stderr)
        sys.exit(1)
    if args.airport_fuel_path and not os.path.isfile(args.airport_fuel_path):
        print(
            f"ERROR: Airport fuel file does not exist: {args.airport_fuel_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not os.path.isdir(args.tmp_dir):
        print(f"ERROR: Temp directory does not exist: {args.tmp_dir}", file=sys.stderr)
        sys.exit(1)

    # Set up meteorological data paths
    met_store = os.path.join(args.weather_path, "icon_met.zarr")
    rad_store = os.path.join(args.weather_path, "icon_rad.zarr")
    wind_store = os.path.join(args.weather_path, "icon_wind.zarr")

    if not os.path.isdir(met_store):
        print(f"ERROR: Met store not found: {met_store}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(rad_store):
        print(f"ERROR: Rad store not found: {rad_store}", file=sys.stderr)
        sys.exit(1)

    # Note: wind_store is optional
    if not os.path.isdir(wind_store):
        print(
            f"WARNING: Wind store not found: {wind_store}. Setting to None.",
            file=sys.stderr,
        )
        wind_store = None

    zarr_paths = ZarrPaths(
        met_store=met_store, rad_store=rad_store, wind_store=wind_store
    )

    # Instantiate Fleet Runner for Small Emitters
    params = SmallFleetRunnerParams(
        trajectory_json_filepath=args.json_file,
        zarr_paths=zarr_paths,
        njobs=args.njobs,
        bada_path=args.bada_path,
        airport_fuel_path=args.airport_fuel_path,
        tmp_base_dir_path=args.tmp_dir,
    )

    print("Starting fleet-level climate impact computation for small emitters...")
    print(f"Loading trajectories from: {args.json_file}")
    print(f"Using OpenAirClim temp dir: {args.tmp_dir}")
    runner = FleetRunnerSmallEmitter(params)
    runner.eval()

    # Print results
    print("\n" + "=" * 60)
    print("Fleet Computation Complete (Small Emitters)")
    print("=" * 60)
    print("\nFleet Meta-data:")
    print(runner.results["fleet_meta_data"])

    print("\n" + "-" * 60)
    print(f"Number of flights processed: {len(runner.results['flight_results'])}")
    print("-" * 60)

    for i, flight_result in enumerate(runner.results["flight_results"], 1):
        print(f"\nFlight {i}:")
        print(flight_result)


if __name__ == "__main__":
    main()
