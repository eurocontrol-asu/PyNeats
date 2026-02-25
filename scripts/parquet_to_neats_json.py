"""
Convert a parquet file of ADS-B state vectors into NEATS-format JSON.

Reads a parquet file produced by OpenSky (or similar ADS-B sources),
applies quality filters, selects a random sample of flights, and writes
a JSON file compatible with the NEATS input schema.

Usage
-----
    python scripts/parquet_to_neats_json.py

    python scripts/parquet_to_neats_json.py \
        --input  data/2025-07-09.parquet \
        --output data/neats_from_parquet.json \
        --num-flights 100 \
        --seed 42 \
        --min-duration 5 \
        --max-endpoint-altitude 10000
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Pool of European ICAO airport codes used for random assignment.
EUROPEAN_AIRPORTS = [
    "LFPG", "LFPO", "EGLL", "EGKK", "EHAM", "EDDF", "EDDM",
    "LEMD", "LEBL", "LIRF", "LIMC", "LSZH", "LOWW", "EKCH",
    "ENGM", "ESSA", "EFHK", "EPWA", "LKPR", "LHBP", "LPPT",
    "LGAV", "LTFM", "LYBE", "LROP", "LBSF", "LDZA", "LJLJ",
    "EYVI", "EVRA", "EETN", "EBBR", "ELLX", "BIKF", "GCFV",
]

FEET_PER_FL = 100.0


def compute_flight_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-flight quality statistics for filtering.

    The DataFrame must be sorted by ``["flight_id", "timestamp"]`` before
    calling this function so that ``.first()`` / ``.last()`` return the
    chronologically correct endpoints.
    """
    grouped = df.groupby("flight_id")
    stats = pd.DataFrame({
        "duration_s": (
            grouped["timestamp"].max() - grouped["timestamp"].min()
        ).dt.total_seconds(),
        "first_alt": grouped["altitude"].first(),
        "last_alt": grouped["altitude"].last(),
    })
    return stats


def trajectory_data_from_group(group: pd.DataFrame) -> list[dict]:
    """Convert a per-flight DataFrame group into NEATS trajectory_data list."""
    rows: list[dict] = []
    for _, r in group.iterrows():
        ts: pd.Timestamp = r["timestamp"]
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S+0000")
        fl = round(float(r["altitude"]) / FEET_PER_FL)
        rows.append(
            {
                "ts": ts_str,
                "lat": round(float(r["latitude"]), 6),
                "lon": round(float(r["longitude"]), 6),
                "fl": fl,
                "ff": None,
                "ee": None,
                "am": None,
            }
        )
    return rows


def build_neats_flight(
    callsign: str,
    aircraft_type: str,
    dep_airport: str,
    arr_airport: str,
    dep_time: str,
    arr_time: str,
    traj_data: list[dict],
) -> dict:
    """Build a single NEATS-format flight dict."""
    return {
        "flight_information": {
            "confidential": "false",
            "flight_identification": callsign,
            "departure_date_time": dep_time,
            "arrival_date_time": arr_time,
            "departure_airport": dep_airport,
            "arrival_airport": arr_airport,
            "aircraft_properties": {
                "aircraft_type": aircraft_type,
            },
            "fuel_properties": {
                "hydrogen_content": None,
                "hydrogen_per_carbon_ratio": None,
                "aromatic_content": None,
                "calorific_value": None,
            },
            "trajectory": {
                "trj_data_source": "OpenSky_ADS-B",
                "trajectory_data": traj_data,
            },
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert parquet ADS-B data to NEATS JSON.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/2025-07-09.parquet"),
        help="Path to the input parquet file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/neats_from_parquet.json"),
        help="Path for the output NEATS JSON file.",
    )
    parser.add_argument(
        "--num-flights",
        type=int,
        default=100,
        help="Number of flights to include (default: 100).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling (default: 42).",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=5.0,
        help="Minimum flight duration in minutes (default: 5).",
    )
    parser.add_argument(
        "--max-endpoint-altitude",
        type=float,
        default=10000.0,
        help=(
            "Maximum altitude in feet for the first and last waypoints "
            "(default: 10000). Flights whose first or last altitude exceeds "
            "this are excluded, ensuring only full origin-to-destination "
            "trajectories are kept."
        ),
    )
    args = parser.parse_args()

    # --- 1. Load parquet ---
    log.info("Loading %s", args.input)
    df = pd.read_parquet(args.input)
    df = df.sort_values(["flight_id", "timestamp"])
    total_flights = df["flight_id"].nunique()
    log.info("Loaded %d state vectors, %d unique flights", len(df), total_flights)

    # --- 2. Filter flights ---
    stats = compute_flight_stats(df)

    dur_mask = stats["duration_s"] >= args.min_duration * 60
    alt_mask = (
        (stats["first_alt"] <= args.max_endpoint_altitude)
        & (stats["last_alt"] <= args.max_endpoint_altitude)
    )

    n_dur_fail = int((~dur_mask).sum())
    n_alt_fail = int((~alt_mask).sum())
    log.info(
        "  Excluded by --min-duration (%.1f min): %d flights",
        args.min_duration, n_dur_fail,
    )
    log.info(
        "  Excluded by --max-endpoint-altitude (%.0f ft): %d flights",
        args.max_endpoint_altitude, n_alt_fail,
    )

    eligible_ids = stats.index[dur_mask & alt_mask].tolist()
    log.info(
        "After filtering: %d / %d flights eligible (%.1f%%)",
        len(eligible_ids), total_flights,
        100.0 * len(eligible_ids) / total_flights if total_flights else 0,
    )

    if not eligible_ids:
        log.warning("No flights passed the filters — writing empty output.")

    # --- 3. Sample flights ---
    rng = random.Random(args.seed)
    n = min(args.num_flights, len(eligible_ids))
    sampled_ids = rng.sample(eligible_ids, n) if eligible_ids else []
    log.info("Sampled %d flights", n)

    df = df[df["flight_id"].isin(set(sampled_ids))]

    # --- 4. Convert each flight ---
    output_flights: list[dict] = []
    grouped = df.groupby("flight_id")

    for i, (fid, group) in enumerate(grouped):
        callsign = group["callsign"].iloc[0]
        aircraft_type = group["typecode"].iloc[0]

        dep_ts: pd.Timestamp = group["timestamp"].iloc[0]
        arr_ts: pd.Timestamp = group["timestamp"].iloc[-1]
        dep_time = dep_ts.strftime("%Y-%m-%dT%H:%M:%S+0000")
        arr_time = arr_ts.strftime("%Y-%m-%dT%H:%M:%S+0000")

        dep_airport = rng.choice(EUROPEAN_AIRPORTS)
        arr_airport = rng.choice([a for a in EUROPEAN_AIRPORTS if a != dep_airport])

        traj_data = trajectory_data_from_group(group)
        flight_dict = build_neats_flight(
            callsign=callsign,
            aircraft_type=aircraft_type,
            dep_airport=dep_airport,
            arr_airport=arr_airport,
            dep_time=dep_time,
            arr_time=arr_time,
            traj_data=traj_data,
        )
        output_flights.append(flight_dict)

        if (i + 1) % 20 == 0:
            log.info("  processed %d / %d flights", i + 1, n)

    # --- 5. Write output ---
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(output_flights, fh, indent=2, ensure_ascii=False)

    log.info("Done. Wrote %d flights to %s", len(output_flights), args.output)


if __name__ == "__main__":
    main()
