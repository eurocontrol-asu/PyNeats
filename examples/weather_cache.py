"""
Build and cache meteorological data from DWD (Deutscher Wetterdienst) for PyNeats computations.

This example demonstrates how to use the DWDFactory to download and cache weather data
in Zarr format, which is required for running fleet-level climate impact computations.

The cached data includes:
- Met (meteorology): Temperature, humidity, pressure, wind
- Rad (radiation): Solar and thermal radiation
- Wind (optional): Additional high-resolution wind data
"""

import argparse
import os
import sys
from datetime import datetime

from pyneats.steps.weather.weather_factory import (
    DWDFactory,
    DWDZarrCacheSpec,
    WeatherCacheConfig,
    WeatherFactoryParams,
)


def main():
    """
    Download and cache DWD meteorological data as Zarr stores.

    This process may take significant time depending on the date range and
    spatial coverage requested. Cached data is reused across multiple
    climate impact computations.
    """
    parser = argparse.ArgumentParser(
        description="Build and cache DWD meteorological data for PyNeats"
    )
    parser.add_argument(
        "--dwd-path",
        required=True,
        help="Path to DWD (Deutscher Wetterdienst) data directory",
    )
    parser.add_argument(
        "--zarr-path",
        required=True,
        help="Path to output directory where Zarr stores will be created",
    )
    parser.add_argument(
        "--date",
        type=str,
        default="2025-07-09",
        help="Date to cache data for (YYYY-MM-DD format, default: 2025-07-09)",
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=0,
        help="Time of day to cache (0-23 hours, default: 0)",
    )
    parser.add_argument(
        "--include-wind",
        action="store_true",
        help="Include wind data cache (optional, requires additional processing)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing Zarr stores",
    )

    args = parser.parse_args()

    # Parse and validate date
    try:
        asofdate = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(
            f"ERROR: Invalid date format: {args.date}. Use YYYY-MM-DD format.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate time of day
    if not 0 <= args.hour <= 23:
        print(f"ERROR: Hour must be between 0 and 23, got {args.hour}", file=sys.stderr)
        sys.exit(1)

    # Validate paths
    if not os.path.isdir(args.dwd_path):
        print(f"ERROR: DWD path does not exist: {args.dwd_path}", file=sys.stderr)
        sys.exit(1)

    # Create zarr output path if it doesn't exist
    os.makedirs(args.zarr_path, exist_ok=True)

    # Set up meteorological data paths
    met_store = os.path.join(args.zarr_path, "icon_met.zarr")
    rad_store = os.path.join(args.zarr_path, "icon_rad.zarr")
    wind_store = os.path.join(args.zarr_path, "icon_wind.zarr") if args.include_wind else None

    print("=" * 70)
    print("DWD Weather Cache Builder")
    print("=" * 70)
    print(f"Date: {args.date}")
    print(f"Hour: {args.hour:02d}:00")
    print(f"DWD Data Path: {args.dwd_path}")
    print(f"Zarr Output Path: {args.zarr_path}")
    print(f"Met Store: {met_store}")
    print(f"Rad Store: {rad_store}")
    if wind_store:
        print(f"Wind Store: {wind_store}")
    print(f"Overwrite: {args.overwrite}")
    print("=" * 70)
    print()

    # Configure Zarr cache specification
    zspec = DWDZarrCacheSpec(
        met_store=met_store,
        rad_store=rad_store,
        wind_store=wind_store,  # None to skip wind
        build_if_missing=True,
        met_chunks={"time": 1, "level": 10, "latitude": 256, "longitude": 256},
        rad_chunks={"time": 1, "level": 1, "latitude": 256, "longitude": 256},
        sdr_accumulate_dt_s=None,
    )

    # Create factory and build cache
    params = WeatherFactoryParams(
        data_dir=args.dwd_path,
        cache=WeatherCacheConfig(zarr=zspec),
    )
    factory = DWDFactory(params)

    print(f"Building weather cache for {args.date} at {args.hour:02d}:00...")
    print("This may take several minutes depending on data size...")
    print()

    try:
        factory.build_cache(asofdate, hour=args.hour, overwrite=args.overwrite)
        print()
        print("=" * 70)
        print("✅ Weather cache built successfully!")
        print("=" * 70)
        print()
        print("Cache locations:")
        print(f"  Met:  {met_store}")
        print(f"  Rad:  {rad_store}")
        if wind_store:
            print(f"  Wind: {wind_store}")
        print()
        print("Use these paths with:")
        print("  - fleet_computation_from_dataframe.py")
        print("  - fleet_computation_from_json.py")
    except Exception as e:
        print()
        print("=" * 70)
        print(f"❌ Error building weather cache: {e}")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
