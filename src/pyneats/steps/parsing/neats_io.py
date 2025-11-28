# pyneats/io/nm_json.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Sequence, Mapping

import pandas as pd

from pyneats.steps.parsing.views import Flight4D


def neats_json_flights_to_dfs(
    flights: Sequence[Mapping[str, Any]],
    *,
    model_type: str = "NM",
) -> List[pd.DataFrame]:
    """
    Convert a sequence of NEATS / NM JSON flight objects into a list of
    per-flight DataFrames in the canonical Flight4D schema.

    This function assumes the JSON is already decoded (list[dict]).
    It does *not* perform any file I/O.
    """

    result: List[pd.DataFrame] = []

    for flight in flights:
        fi = flight.get("flight_information", {}) or {}
        ap = fi.get("aircraft_properties", {}) or {}
        fp = fi.get("fuel_properties", {}) or {}

        # -----------------------------
        # 1. Flight-level attrs (canonical names)
        # -----------------------------
        
        attrs: Dict[str, Any] = {
            "flight_id": fi.get("flight_identification"),
            "departure_airport": fi.get("departure_airport"),
            "arrival_airport": fi.get("arrival_airport"),
            "model_type": model_type,
            'aobt': fi.get("departure_date_time"),
            'arrival_date_time': fi.get("arrival_date_time"),
            
            # Aircraft
            "aircraft_type": ap.get("aircraft_type"),
            "aircraft_series": ap.get("aircraft_version"),
            "engine_uid": ap.get("engine_uid"),
            "takeoff_weight": ap.get("takeoff_mass"),
            "payload_factor": ap.get("load_factor"),

            # Fuel (canonical names aligned with NEATSFuel / Flight4D)
            "hydrogen_content": fp.get("hydrogen_content"),
            "h_c_ratio": fp.get("hydrogen_per_carbon_ratio"),
            "aromatic_content": fp.get("aromatic_content"),
            "q_fuel": fp.get("calorific_value"),
            "sulphur_content": fp.get("sulphur"),
            "naphthalene": fp.get("naphthalene"),
        }

        # Drop attrs with None values or not in Flight4D schema
        allowed_attrs = set(Flight4D.ATTRS_REQUIRED) | set(Flight4D.ATTRS_OPTIONAL)
        attrs = {
            k: v
            for k, v in attrs.items()
            if v is not None and k in allowed_attrs
        }

        # -----------------------------
        # 2. Per-point rows (canonical column names)
        # -----------------------------
        rows: List[Dict[str, Any]] = []

        tr = fi.get("trajectory", {}) or {}
        pts = tr.get("trajectory_data", []) or []

        for p in pts:
            ts_raw = p.get("ts")

            if ts_raw is None:
                time_over = None
            else:
                # "2025-11-02T10:02:00+0000" → "2025-11-02 10:02:00"
                dt = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%S%z")
                time_over = dt.strftime("%Y-%m-%d %H:%M:%S")

            rows.append(
                {
                    # canonical 4D columns
                    "latitude": p.get("lat"),
                    "longitude": p.get("lon"),
                    "time": time_over,
                    # NB: still FL in hundreds of feet; conversion stays in parser
                    "altitude": p.get("fl"),
                    # optional
                    "fuel_flow": p.get("ff"),
                    "engine_efficiency": p.get("ee"),
                    "aircraft_mass": p.get("am"),
                    "true_airspeed": p.get("tas"),  
                }
            )

        df = pd.DataFrame(rows)

        # Keep only columns that are part of the Flight4D schema
        if not df.empty:
            allowed_cols = set(Flight4D.REQUIRED) | set(Flight4D.OPTIONAL)
            df = df[[c for c in df.columns if c in allowed_cols]]

            # Drop columns that are entirely NaN
            df = df.dropna(axis=1, how="all")

        # Attach attrs (canonical)
        df.attrs = attrs

        result.append(df)

    return result
