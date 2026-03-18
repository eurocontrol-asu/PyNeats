import argparse
import json
import os
import sys

from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.performance_runner import FleetRunnerPerformanceOnly
from pyneats.steps.weather.weather_store import ZarrPaths


def main():
    """
    Run fleet-level performance computations (no emissions / climate impact).

    This example demonstrates how to use the FleetRunnerPerformanceOnly to
    compute aircraft performance metrics (fuel flow, aircraft mass, true
    airspeed, engine efficiency) for a fleet of flights without running
    the downstream emissions, contrails, or climate impact steps.

    Use this when you only need performance trajectory data — it is
    significantly faster than the full pipeline.
    """
    parser = argparse.ArgumentParser(
        description="Fleet-level performance-only computation (no emissions / climate)"
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

    # Instantiate Fleet Runner (performance only — no emissions or climate)
    params = FleetRunnerParams(
        trajectory_json_filepath=args.json_file,
        zarr_paths=zarr_paths,
        njobs=args.njobs,
        bada_path=args.bada_path,
        airport_fuel_path=args.airport_fuel_path,
    )

    print("Starting fleet-level performance-only computation...")
    print(f"Loading trajectories from: {args.json_file}")
    runner = FleetRunnerPerformanceOnly(params)
    runner.eval()

    # Print results
    print("\n" + "=" * 60)
    print("Fleet Computation Complete (Performance Only)")
    print("=" * 60)
    print("\nFleet Meta-data:")
    print(runner.results["fleet_meta_data"])

    print("\n" + "-" * 60)
    print(f"Number of flights processed: {len(runner.results['flight_results'])}")
    print("-" * 60)

    for i, flight_result in enumerate(runner.results["flight_results"], 1):
        fi = flight_result.get("flight_information", {})
        perf = flight_result.get("performance", {})
        error = flight_result.get("error")

        print(f"\nFlight {i}: {fi.get('flight_id', 'UNKNOWN')}")

        if error:
            print(f"  ❌ Error: {error}")
            continue

        n_points = len(perf.get("timestamps", []))
        print(
            f"  Route: {fi.get('departure_airport', '?')} → {fi.get('arrival_airport', '?')}"
        )
        print(f"  Aircraft: {fi.get('aircraft_type', '?')}")
        print(f"  Trajectory points: {n_points}")

        # Show a snippet of performance vectors
        if n_points > 0:
            fuel_flow = perf.get("fuel_flow", [])
            ff_values = [v for v in fuel_flow[:3] if v is not None]
            if ff_values:
                print(f"  Fuel flow (first 3): {ff_values}")

    # Optionally dump full results to JSON
    print("\n" + "-" * 60)
    print("Full results (JSON):")
    print(json.dumps(runner.results, indent=2, default=str))


if __name__ == "__main__":
    main()
