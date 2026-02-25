"""
Fetch ADS-B trajectories from OpenSky Network for intra-European flights.

Reads a NEATS/NM JSON input file, filters flights whose departure *and*
arrival airports both lie inside the ECAC/European area, queries the
OpenSky Trino database for ADS-B state-vector data, and writes a new
JSON file in the same NEATS schema with trajectory data sourced from
ADS-B (lat, lon, fl, ts).

Usage
-----
    # List intra-European flights (dry run, no OpenSky query):
    python scripts/fetch_opensky_adsb.py --list-only

    # Fetch ADS-B data:
    python scripts/fetch_opensky_adsb.py \
        --input  data/nm_json_20250709_sample_100.json \
        --output data/opensky_intra_eu.json

    # Resume a partial run (appends to existing output):
    python scripts/fetch_opensky_adsb.py --resume

Prerequisites
-------------
* ``pip install pyopensky``
* OpenSky Trino credentials configured in one of:
  - ``~/.config/pyopensky/settings.conf``  (recommended)
  - environment variables ``OPENSKY_USERNAME`` / ``OPENSKY_PASSWORD``

  To create the config file::

      mkdir -p ~/.config/pyopensky
      cat > ~/.config/pyopensky/settings.conf << 'EOF'
      [default]
      username = your_opensky_username
      password = your_opensky_password
      EOF
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# European ICAO 2-letter prefixes (ECAC + near-European states)
# ---------------------------------------------------------------------------
EUROPEAN_PREFIXES = {
    # E* — Northern / Central Europe
    "EB", "ED", "EE", "EF", "EG", "EH", "EI", "EK", "EL",
    "EN", "EP", "ES", "ET", "EV", "EY",
    # L* — Southern / South-Eastern Europe + Turkey + Israel
    "LA", "LB", "LC", "LD", "LE", "LF", "LG", "LH", "LI",
    "LJ", "LK", "LL", "LM", "LN", "LO", "LP", "LQ", "LR",
    "LS", "LT", "LU", "LW", "LX", "LY", "LZ",
    # Other
    "BI",  # Iceland
    "GC",  # Canary Islands (Spain)
    "UM",  # Belarus
    "UK",  # Ukraine
    "UG",  # Georgia
    "BK",  # Kosovo
}

METERS_TO_FEET = 3.28084
FEET_PER_FL = 100.0


def is_european(icao_code: str) -> bool:
    """Return True when the ICAO airport code belongs to Europe."""
    return icao_code[:2] in EUROPEAN_PREFIXES


def is_intra_european(flight: dict) -> bool:
    fi = flight.get("flight_information", {}) or {}
    dep = fi.get("departure_airport", "")
    arr = fi.get("arrival_airport", "")
    return is_european(dep) and is_european(arr)


# ---------------------------------------------------------------------------
# OpenSky query helpers
# ---------------------------------------------------------------------------


def query_adsb_trajectory(
    trino,
    callsign: str,
    dep_time: datetime,
    arr_time: datetime,
    *,
    time_margin_minutes: int = 15,
) -> pd.DataFrame | None:
    """
    Query OpenSky Trino for ADS-B state vectors matching *callsign*
    within a time window around the flight times.

    Returns a cleaned DataFrame sorted by time, or None when no data is found.
    """
    start = dep_time - timedelta(minutes=time_margin_minutes)
    stop = arr_time + timedelta(minutes=time_margin_minutes)

    cs = callsign.strip()
    log.debug("  querying callsign=%r  [%s -> %s]", cs, start, stop)
    try:
        df = trino.history(
            start=start,
            stop=stop,
            callsign=cs,
            selected_columns=(
                "time",
                "icao24",
                "callsign",
                "lat",
                "lon",
                "baroaltitude",
                "geoaltitude",
                "onground",
            ),
        )
    except Exception as exc:
        log.warning("  Trino query failed for %s: %s", cs, exc)
        return None

    if df is None or df.empty:
        return None

    # Drop ground points and rows without position / altitude
    df = df[~df["onground"]].copy()
    df = df.dropna(subset=["lat", "lon", "baroaltitude"])
    df = df.sort_values("time").drop_duplicates(subset=["time"], keep="first")
    df = df.reset_index(drop=True)

    return df if not df.empty else None


def adsb_df_to_trajectory_data(df: pd.DataFrame) -> list[dict]:
    """
    Convert a state-vector DataFrame into the NEATS ``trajectory_data``
    list format (ts, lat, lon, fl, ff=null, ee=null, am=null).
    """
    rows: list[dict] = []
    for _, r in df.iterrows():
        ts: pd.Timestamp = r["time"]
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S+0000")

        fl_raw = r["baroaltitude"] * METERS_TO_FEET / FEET_PER_FL
        fl = round(fl_raw)

        rows.append(
            {
                "ts": ts_str,
                "lat": round(float(r["lat"]), 6),
                "lon": round(float(r["lon"]), 6),
                "fl": fl,
                "ff": None,
                "ee": None,
                "am": None,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_nm_datetime(s: str) -> datetime:
    """Parse NM datetime string like '2025-07-09T18:07:00+0000'."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def build_output_flight(fi: dict, traj_data: list[dict]) -> dict:
    """Build a single NEATS-format output flight dict with ADS-B trajectory."""
    return {
        "flight_information": {
            "confidential": fi.get("confidential", "false"),
            "flight_identification": fi["flight_identification"],
            "departure_date_time": fi["departure_date_time"],
            "arrival_date_time": fi["arrival_date_time"],
            "departure_airport": fi["departure_airport"],
            "arrival_airport": fi["arrival_airport"],
            "aircraft_properties": fi.get("aircraft_properties", {}),
            "fuel_properties": fi.get("fuel_properties", {}),
            "trajectory": {
                "trj_data_source": "OpenSky_ADS-B",
                "trajectory_data": traj_data,
            },
        }
    }


def load_already_fetched(output_path: Path) -> set[str]:
    """Return the set of callsigns already present in *output_path*."""
    if not output_path.exists():
        return set()
    with open(output_path) as fh:
        existing = json.load(fh)
    return {
        f["flight_information"]["flight_identification"]
        for f in existing
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch ADS-B trajectories from OpenSky for intra-European flights.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/nm_json_20250709_sample_100.json"),
        help="Path to the input NEATS/NM JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/opensky_intra_eu.json"),
        help="Path for the output JSON file with ADS-B trajectories.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between OpenSky queries (default: 1.0).",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list intra-European flights; do not query OpenSky.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip flights already present in the output file.",
    )
    args = parser.parse_args()

    # --- 1. Load input ---
    log.info("Loading %s", args.input)
    with open(args.input) as fh:
        all_flights: list[dict] = json.load(fh)
    log.info("Loaded %d flights total", len(all_flights))

    # --- 2. Filter intra-European ---
    eu_flights = [f for f in all_flights if is_intra_european(f)]
    log.info("Intra-European flights: %d / %d", len(eu_flights), len(all_flights))

    if args.list_only:
        print(f"\n{'#':>3}  {'Callsign':<12} {'Route':<12} {'Type':<6} {'Dep time':<20} {'Arr time'}")
        print("-" * 80)
        for i, fl in enumerate(eu_flights, 1):
            fi = fl["flight_information"]
            print(
                f"{i:3d}  {fi['flight_identification']:<12} "
                f"{fi['departure_airport']}->{fi['arrival_airport']:<5} "
                f"{fi['aircraft_properties']['aircraft_type']:<6} "
                f"{fi['departure_date_time']:<20} {fi['arrival_date_time']}"
            )
        return

    # --- 3. Resume support ---
    already_done: set[str] = set()
    output_flights: list[dict] = []

    if args.resume:
        already_done = load_already_fetched(args.output)
        if already_done:
            log.info("Resuming: %d flights already in output", len(already_done))
            with open(args.output) as fh:
                output_flights = json.load(fh)

    # --- 4. Connect to OpenSky Trino ---
    from pyopensky.trino import Trino

    trino = Trino()
    log.info("Connected to OpenSky Trino")

    # --- 5. Query ADS-B for each flight ---
    success = len(output_flights)
    skipped = 0

    for idx, flight in enumerate(eu_flights):
        fi = flight["flight_information"]
        callsign = fi["flight_identification"]
        dep = fi["departure_airport"]
        arr = fi["arrival_airport"]
        dep_dt = parse_nm_datetime(fi["departure_date_time"])
        arr_dt = parse_nm_datetime(fi["arrival_date_time"])

        if callsign in already_done:
            log.info("[%d/%d] %s — already fetched, skipping", idx + 1, len(eu_flights), callsign)
            continue

        log.info(
            "[%d/%d] %s  %s->%s  (%s -> %s)",
            idx + 1,
            len(eu_flights),
            callsign,
            dep,
            arr,
            dep_dt.strftime("%H:%M"),
            arr_dt.strftime("%H:%M"),
        )

        df = query_adsb_trajectory(trino, callsign, dep_dt, arr_dt)

        if df is None:
            log.warning("  no ADS-B data found -- skipping")
            skipped += 1
            if args.delay > 0:
                time.sleep(args.delay)
            continue

        log.info("  %d ADS-B state vectors retrieved", len(df))

        traj_data = adsb_df_to_trajectory_data(df)
        output_flights.append(build_output_flight(fi, traj_data))
        success += 1

        # Incremental save (so partial progress survives interruption)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as fh:
            json.dump(output_flights, fh, indent=2, ensure_ascii=False)

        if args.delay > 0:
            time.sleep(args.delay)

    # --- 6. Final summary ---
    log.info(
        "Done. %d flights with ADS-B data, %d skipped (no data).",
        success,
        skipped,
    )
    log.info("Output: %s", args.output)


if __name__ == "__main__":
    main()
