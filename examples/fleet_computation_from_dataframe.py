import argparse
import json
import os
import sys

import pandas as pd

from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.weather.weather_store import ZarrPaths


def json_to_dataframe(json_filepath: str) -> pd.DataFrame:
    """
    Convert JSON trajectory data to a pandas DataFrame.

    Parameters
    ----------
    json_filepath : str
        Path to JSON file containing flight trajectories.

    Returns
    -------
    pd.DataFrame
        DataFrame with trajectory waypoints, with flight-level metadata as columns.
    """
    with open(json_filepath) as f:
        flights_data = json.load(f)

    rows = []

    for flight in flights_data:
        fi = flight.get("flight_information", {})
        ap = fi.get("aircraft_properties", {})
        trajectory = fi.get("trajectory", {})
        trajectory_data = trajectory.get("trajectory_data", [])

        flight_id = fi.get("flight_identification")
        departure_airport = fi.get("departure_airport")
        arrival_airport = fi.get("arrival_airport")
        aobt = fi.get("departure_date_time")
        aircraft_type = ap.get("aircraft_type")
        model_type = trajectory.get("trj_data_source", "Unknown")

        # Convert each trajectory point to a row
        rows.extend(
            {
                "latitude": point.get("lat"),
                "longitude": point.get("lon"),
                "time": point.get("ts"),
                "altitude": point.get("fl"),  # flight level
                "flight_id": flight_id,
                "departure_airport": departure_airport,
                "arrival_airport": arrival_airport,
                "aobt": aobt,
                "aircraft_type": aircraft_type,
                "model_type": model_type,
            }
            for point in trajectory_data
        )

    df = pd.DataFrame(rows)

    # Parse time columns to datetime for the DataFrame
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["aobt"] = pd.to_datetime(df["aobt"], utc=True)

    return df


def main():
    """
    Run fleet-level climate impact computations for large emitters from DataFrame input.

    This example demonstrates how to use the FleetRunnerLargeEmitter to compute
    climate impacts (contrails, non-CO2 effects, and metrics) for a fleet of flights
    loaded from a pandas DataFrame.

    To keep this example working, it loads data from the JSON test file and converts
    it to a DataFrame. In your own code, you would load trajectory data from CSV,
    database, or other sources.
    """
    parser = argparse.ArgumentParser(
        description="Fleet-level climate impact computation from DataFrame"
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

    # Note: wind_store is optional, but will use it if it exists
    if not os.path.isdir(wind_store):
        print(
            f"WARNING: Wind store not found: {wind_store}. Setting to None.",
            file=sys.stderr,
        )
        wind_store = None

    zarr_paths = ZarrPaths(
        met_store=met_store, rad_store=rad_store, wind_store=wind_store
    )

    # Load trajectory data from JSON test file and convert to DataFrame
    # This ensures the example works end-to-end with complete trajectory data
    test_json_path = "tests/data/golden/fleet_5_flights_input.json"

    if not os.path.isfile(test_json_path):
        print(
            f"ERROR: Test data file not found: {test_json_path}\n"
            f"This example loads from test data to ensure it works end-to-end.\n"
            f"Please run this script from the project root directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Convert JSON trajectories to DataFrame
    print(f"Loading trajectory data from: {test_json_path}")
    trajectory_dataframe = json_to_dataframe(test_json_path)

    # Required DataFrame schema with trajectory waypoints:
    #
    #   Column name        Type              Description
    #   -----------------------------------------------
    #   latitude           float             Geodetic latitude (deg)
    #   longitude          float             Geodetic longitude (deg)
    #   time               datetime64[ns]    Timestamp of waypoint
    #   altitude           float/int         Altitude (FL - flight level)
    #   flight_id          str               Unique flight identifier
    #   departure_airport  str               ICAO departure airport code
    #   arrival_airport    str               ICAO arrival airport code
    #   model_type         str               Source of trajectory data
    #   aobt               datetime64[ns]    Actual off-block time
    #   aircraft_type      str               ICAO aircraft type code

    print(
        f"Loaded {len(trajectory_dataframe)} waypoints for {trajectory_dataframe['flight_id'].nunique()} flights"
    )
    print(f"Columns: {', '.join(trajectory_dataframe.columns.tolist())}")
    print()

    # Instantiate Fleet Runner for Large Emitters
    params = FleetRunnerParams(
        trajectory_dataframe=trajectory_dataframe,
        zarr_paths=zarr_paths,
        njobs=args.njobs,
        bada_path=args.bada_path,
        airport_fuel_path=args.airport_fuel_path,
    )

    print("Starting fleet-level climate impact computation for large emitters...")
    runner = FleetRunnerLargeEmitter(params)
    runner.eval()

    # Print results for the Fleet sample
    print("\n" + "=" * 60)
    print("Fleet Computation Complete")
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
