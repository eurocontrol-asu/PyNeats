"""
NEATS JSON to Flight DataFrame Conversion Module

Converts NEATS/NM JSON flight objects into a list of per-flight DataFrames in the canonical Flight4D schema.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pandas as pd

from pyneats.steps.parsing.views import Flight4D


def neats_json_to_flights(
    flights: Sequence[Mapping[str, Any]],
    *,
    model_type: str = "NM",
) -> list[pd.DataFrame]:
    """
    Convert a sequence of NEATS / NM JSON flight objects into a list of
    per-flight DataFrames in the canonical Flight4D schema.

    This function assumes the JSON is already decoded (list[dict]).
    It does *not* perform any file I/O.

    Parameters
    ----------
    flights : Sequence[Mapping[str, Any]]
        Sequence of decoded NEATS/NM JSON flight objects.
    model_type : str, optional
        Model type label to assign to each flight (default is "NM").

    Returns
    -------
    list of pd.DataFrame
        List of per-flight DataFrames in Flight4D schema.
    """
    result: list[pd.DataFrame] = []

    for flight in flights:
        fi = flight.get("flight_information", {}) or {}
        ap = fi.get("aircraft_properties", {}) or {}
        fp = fi.get("fuel_properties", {}) or {}

        # ...existing code...

        # -----------------------------
        # 2. Per-point rows (canonical column names)
        # -----------------------------
        rows: list[dict[str, Any]] = []

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
        # Reconstruct flight-level attrs as in original logic
        allowed_attrs = set(Flight4D.ATTRS_REQUIRED) | set(Flight4D.ATTRS_OPTIONAL)
        attrs = {
            k: v
            for k, v in {
                "flight_id": fi.get("flight_identification"),
                "departure_airport": fi.get("departure_airport"),
                "arrival_airport": fi.get("arrival_airport"),
                "model_type": model_type,
                "aobt": fi.get("departure_date_time"),
                "arrival_date_time": fi.get("arrival_date_time"),
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
            }.items()
            if v is not None and k in allowed_attrs
        }
        df.attrs = attrs

        result.append(df)

    return result


def concat_neats_flight(
    dfs: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    """
    Take a list of per-flight DataFrames (as produced by `neats_json_to_flights`)
    and return a single concatenated DataFrame where each row also contains the
    flight-level attributes as regular columns.

    - df.attrs is broadcast to all rows of that flight
    - Flights with different sets of attrs will just have NaN in the missing ones
    """

    frames: list[pd.DataFrame] = []

    for df in dfs:
        if df.empty:
            # nothing to add for this flight
            continue

        attrs = getattr(df, "attrs", None) or {}

        if attrs:
            # Broadcast attrs to all rows of this df
            meta_df = pd.DataFrame(
                {k: [v] * len(df) for k, v in attrs.items()},
                index=df.index,
            )
            df_with_attrs = pd.concat([df, meta_df], axis=1)
        else:
            df_with_attrs = df.copy()

        frames.append(df_with_attrs)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def select_flights(
    dfs: list[pd.DataFrame],
    flight_id: str | None = None,
    adep: str | None = None,
    ades: str | None = None,
) -> list[pd.DataFrame]:
    """
    Filter the list of per-flight DataFrames by matching
    FLIGHT_ID, ADEP, ADES values stored in df.attrs.

    Any parameter left as None is ignored.
    """
    result: list[pd.DataFrame] = []

    for df in dfs:
        attrs = df.attrs

        if flight_id is not None and attrs.get("flight_id") != flight_id:
            continue
        if adep is not None and attrs.get("departure_airport") != adep:
            continue
        if ades is not None and attrs.get("arrival_airport") != ades:
            continue

        result.append(df)

    return result


def select_json_flights(
    flights: Sequence[Mapping[str, Any]],
    flight_id: str | None = None,
    adep: str | None = None,
    ades: str | None = None,
) -> list[dict[str, Any]]:
    """
    Filter the list of NEATS / NM JSON flight objects by matching:

      - flight_information.flight_identification
      - flight_information.departure_airport
      - flight_information.arrival_airport

    Any parameter left as None is ignored.
    """

    result: list[dict[str, Any]] = []

    for flight in flights:
        fi = flight.get("flight_information", {}) or {}

        if flight_id is not None and fi.get("flight_identification") != flight_id:
            continue
        if adep is not None and fi.get("departure_airport") != adep:
            continue
        if ades is not None and fi.get("arrival_airport") != ades:
            continue

        # keep this flight
        # (copy to dict if you want to be extra-safe: dict(flight))
        result.append(flight)  # type: ignore[arg-type]

    return result


def split_df_into_flights(
    df: pd.DataFrame,
    *,
    attr_columns: list[str] | None = None,
) -> list[pd.DataFrame]:
    """
    Rebuild the list of per-flight DataFrames that have .attrs populated.

    Parameters
    ----------
    df : pd.DataFrame
        Big concatenated DataFrame with flight-level columns.
    flight_key : str
        Column used to group rows back into individual flights.
    attr_columns : list[str] or None
        Columns that should be stored in df.attrs instead of standard columns.
        If None, defaults to all non-trajectory columns except `flight_key`.
    """

    flight_key_cols = ["flight_id", "arrival_airport", "departure_airport", "aobt"]
    df["flight_key"] = df[flight_key_cols].astype(str).agg("_".join, axis=1)

    per_flight_dfs: list[pd.DataFrame] = []

    # --- Determine which columns are trajectory-level vs flight-level ---
    if attr_columns is None:
        # Attr cols = columns that were originally in df.attrs
        # i.e. all non-trajectory columns + fuel/aircraft metadata
        trajectory_cols = {
            "latitude",
            "longitude",
            "time",
            "altitude",
            "fuel_flow",
            "engine_efficiency",
            "aircraft_mass",
            "true_airspeed",
        }
        attr_columns = [
            c for c in df.columns if c not in trajectory_cols and c != "flight_key"
        ]

    # --- Split by flight_key ---
    for _, grp in df.groupby("flight_key", sort=False):
        # Extract attrs from the *first row* of the group
        first_row = grp.iloc[0]
        attrs = {
            col: first_row[col] for col in attr_columns if pd.notna(first_row[col])
        }

        # Drop attribute columns from the actual trajectory dataframe
        traj_df = grp.drop(columns=attr_columns + ["flight_key"]).reset_index(drop=True)

        # --- Drop columns that are entirely NaN within this flight ---
        # (optional) keep these even if all-NaN:
        keep_cols = {"latitude", "longitude", "time", "altitude"}
        traj_df = traj_df.dropna(axis=1, how="all")
        traj_df = traj_df.reindex(
            columns=list(keep_cols.intersection(traj_df.columns))
            + [c for c in traj_df.columns if c not in keep_cols]
        )

        # Assign attrs
        traj_df.attrs = attrs

        per_flight_dfs.append(traj_df)

    return per_flight_dfs
