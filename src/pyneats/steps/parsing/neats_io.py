"""
NEATS JSON to Flight DataFrame Conversion Module

Converts NEATS/NM JSON flight objects into a list of per-flight DataFrames in the canonical Flight4D schema.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any

import pandas as pd

from pyneats.steps.parsing.views import Flight4D


logger = logging.getLogger(__name__)


# Fractional seconds of the seconds field (".5" in "2025-11-02T10:02:00.5Z").
_FRACTIONAL_SECONDS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.\d+", re.ASCII
)


def _ts_to_utc_string(ts_raw: str) -> str:
    """Convert an AO trajectory ``ts`` to a naive UTC ``"%Y-%m-%d %H:%M:%S"`` string.

    ``ts`` is an RFC 3339 date-time (AO schema ``"format": "date-time"``).
    The UTC offset is applied, so ``"2025-11-02T12:02:00+02:00"`` becomes
    ``"2025-11-02 10:02:00"``. A ``ts`` without offset is read as UTC, the
    time scale the AO schema prescribes. Also accepted: a lowercase ``t`` or
    ``z`` and a space instead of ``T``. Fractional seconds are truncated to
    whole seconds. Leap seconds (``:60``) are not supported. UTC values
    (``Z``, ``+0000``, ``+00:00``) give the same string as before this
    function existed.

    Raises
    ------
    ValueError
        If ``ts`` is not a string or not a valid date-time, or if the UTC
        result falls outside years 1 to 9999.
    """
    if not isinstance(ts_raw, str):
        raise ValueError(f"ts {ts_raw!r} is not a string")
    s = ts_raw.upper()
    if len(s) > 10 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    s = _FRACTIONAL_SECONDS_RE.sub(r"\1", s, count=1)
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as err:
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            raise ValueError(
                f"ts {ts_raw!r} is not a valid RFC 3339 date-time ({err})"
            ) from None
    try:
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    except OverflowError:
        raise ValueError(
            f"ts {ts_raw!r} falls outside years 1 to 9999 in UTC"
        ) from None


def clamp_payload_factor(value: Any, flight_id: Any) -> Any:
    """Return 1.0 for a payload factor above 1, with a warning; else ``value``.

    The payload factor (AO ``load_factor``) is a fraction of the maximum
    payload, so 1 is full payload. A value above 1 is set to 1.0, as the DLR
    test TC_LF_GT_ONE requires; it is not divided by 100. ``None``, NaN, a
    negative value and a value that is not a number are returned unchanged:
    ``NeatsTrajectoryParser`` rejects a negative value or one that is not a
    number, and the performance step uses the default for NaN.
    """
    try:
        payload_factor = float(value)
    except (TypeError, ValueError):
        return value
    if payload_factor > 1.0:
        logger.warning(
            "Flight %s: payload_factor (AO load_factor) %g is above 1; using 1.0",
            flight_id,
            payload_factor,
        )
        return 1.0
    return value


@dataclass(frozen=True)
class FlightConversionFailure:
    """A flight that ``neats_json_to_flights`` could not convert.

    ``index`` is the flight's position in the input sequence. ``attrs`` holds
    the identifying attrs that could be read (``flight_id``, airports,
    ``aobt``, ``aircraft_type``, ``engine_uid``); it may be empty.
    """

    index: int
    attrs: dict[str, Any]
    error: Exception


def _identity_attrs(flight: Any) -> dict[str, Any]:
    """Read the identifying attrs of a flight object, never raising."""
    try:
        fi = flight.get("flight_information", {}) or {}
        ap = fi.get("aircraft_properties", {}) or {}
        found = {
            "flight_id": fi.get("flight_identification"),
            "departure_airport": fi.get("departure_airport"),
            "arrival_airport": fi.get("arrival_airport"),
            "aobt": fi.get("departure_date_time"),
            "aircraft_type": ap.get("aircraft_type"),
            "engine_uid": ap.get("engine_uid"),
        }
    except Exception:  # malformed flight object
        return {}
    return {k: v for k, v in found.items() if v is not None}


def _without_tracebacks(exc: Exception) -> Exception:
    """Drop the tracebacks of ``exc`` and of every exception it chains to.

    A stored traceback keeps its frames alive, and through them the whole
    input of ``neats_json_to_flights``.
    """
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        e.__traceback__ = None
        e = e.__cause__ or e.__context__
    return exc


def neats_json_to_flights(
    flights: Sequence[Mapping[str, Any]],
    *,
    model_type: str = "NM",
    failures: list[FlightConversionFailure] | None = None,
) -> list[pd.DataFrame]:
    """
    Convert a sequence of NEATS / NM JSON flight objects into a list of
    per-flight DataFrames in the canonical Flight4D schema.

    This function assumes the JSON is already decoded (list[dict]).
    It does *not* perform any file I/O. No unit conversion is applied here;
    values are copied as received, except that ``ts`` is reformatted (see
    Notes).

    Parameters
    ----------
    flights : Sequence[Mapping[str, Any]]
        Sequence of decoded NEATS/NM JSON flight objects. Must be a list (or
        other sequence) of flight objects. The AO schema also allows a bare
        single object at top level; it is not accepted here, because
        iterating a dict yields its keys (see
        docs/internal/pyneats_units_audit.md).
    model_type : str, optional
        Model type label to assign to each flight (default is "NM").
    failures : list of FlightConversionFailure, optional
        If ``None`` (default), the first flight that cannot be converted
        raises and stops the conversion. If a list is given, such a flight is
        left out of the result and recorded in ``failures`` instead, so the
        other flights are still converted. ``flights`` must then be a
        sequence of flight objects; a mapping or a string raises
        ``TypeError``.

    Returns
    -------
    list of pd.DataFrame
        List of per-flight DataFrames in Flight4D schema, in input order
        (without the failed flights when ``failures`` is given).

    Notes
    -----
    Field mapping (JSON field -> Flight4D name: unit as passed on). "MRR"
    is Implementing Regulation (EU) 2018/2066 as amended by (EU) 2024/2493.

    Per-point columns, from ``flight_information.trajectory.trajectory_data[*]``:

    - ``ts`` -> ``time``: UTC string ``"%Y-%m-%d %H:%M:%S"``, read as UTC
      by ``NeatsTrajectoryParser``. ``ts`` is an RFC 3339 date-time and its
      UTC offset is applied (``"2025-11-02T12:02:00+02:00"`` ->
      ``"2025-11-02 10:02:00"``); a ``ts`` without offset is read as UTC. A
      lowercase ``t``/``z`` and a space separator are accepted; fractional
      seconds are truncated to whole seconds, and points that then share a
      second are reduced to one by the parser. An invalid ``ts`` raises
      ``ValueError`` naming the flight and point. Point spacing is not
      assumed (the interpolation step resamples).
    - ``lat`` / ``lon`` -> ``latitude`` / ``longitude``: decimal degrees
      (WGS 84), unchanged.
    - ``fl`` -> ``altitude``: still flight level (hundreds of ft).
      ``NeatsTrajectoryParser`` converts it to metres of ISA pressure
      altitude (FL x 100 ft x 0.3048 m/ft).
    - ``tas`` -> ``true_airspeed``: m/s. The AO JSON field ``tas`` is in
      knots; the NEATS application converts knots to m/s (x 1852 / 3600)
      before calling PyNEATS, so values received here must already be in m/s.
    - ``ff`` -> ``fuel_flow``: kg/s, whole aircraft. The AO schema does not
      say so, but MRR Annex IIIa §1(33) defines fuel flow as the fuel mass
      passing "into the aircraft's engines per second"; pycontrails
      ``Emissions`` divides by ``n_engine`` to get per-engine flow.
    - ``ee`` -> ``engine_efficiency``: dimensionless fraction [0, 1]. MRR
      Annex IIIa §1(34) and the Commission NEATS guidance define it as the
      (overall propulsion) efficiency, useful thrust relative to fuel energy input;
      the regulation words it as a "percentage". pycontrails consumes it in
      the SAC mixing-line slope as F * TAS / (fuel_flow * q_fuel).
    - ``am`` -> ``aircraft_mass``: kg.

    Per-flight attributes (``df.attrs``), from ``flight_information``:

    - ``departure_date_time`` -> ``aobt``: copied verbatim as a string,
      never parsed (used only in flight keys and outputs). The AO schema
      describes it as the flight-plan Item 13 time in UTC, which ICAO
      Doc 4444 defines as the estimated off-block time (EOBT); PyNEATS
      labels the attr AOBT.
    - ``arrival_date_time`` is mapped but then dropped (not a Flight4D attr).
      ``nwp_date_time``, ``confidential``, ``ets_exemption`` and
      ``trajectory.trj_data_source`` are not read; ``model_type`` comes from
      the function argument.
    - ``aircraft_properties.takeoff_mass`` -> ``takeoff_weight``: kg, the
      mass "at beginning of the take-off run" (MRR Annex IIIa §1(29)).
    - ``aircraft_properties.load_factor`` -> ``payload_factor``:
      dimensionless fraction, used as payload mass / maximum payload (BADA
      MPL, or MTOW - OEW when MPL is unavailable), not a seat load factor,
      as defined in MRR Annex IIIa §1(32). A value above 1 is set to 1.0
      with a warning (``clamp_payload_factor``); a negative value is kept
      here and fails the flight in ``NeatsTrajectoryParser``.
    - ``fuel_properties.hydrogen_content`` -> ``hydrogen_content``: wt.%
      (percent by mass, e.g. 13.79), not a 0-1 fraction.
    - ``fuel_properties.hydrogen_per_carbon_ratio`` -> ``h_c_ratio``: used
      by ``NEATSFuel`` as an atomic (molar) H/C ratio, only when
      ``hydrogen_content`` is absent; MRR Annex IIIa §1(36) defines it as
      hydrogen atoms per carbon atom.
    - ``fuel_properties.calorific_value`` -> ``q_fuel``: J/kg of fuel (lower
      calorific value). The AO JSON field ``calorific_value`` is in MJ/kg of
      fuel; the NEATS application multiplies by 1e6 before calling PyNEATS,
      so values received here must already be in J/kg.
    - ``fuel_properties.aromatic_content`` -> ``aromatic_content`` and
      ``fuel_properties.sulphur`` -> ``sulphur_content``: stored, not used in
      calculations. Basis per the defaults in MRR Annex IIIa §5(4):
      aromatics % by volume, sulphur % by mass. Whether the JSON value is a
      percentage or a fraction is not defined.
    - ``fuel_properties.naphthalene`` is emitted under the key
      ``"naphthalene"``, but ``Flight4D.ATTRS_OPTIONAL`` spells it
      ``"naphtalene"``, so the ``allowed_attrs`` filter drops the value here
      (see docs/internal/pyneats_units_audit.md).
    """
    if failures is not None and isinstance(flights, (Mapping, str, bytes)):
        # A whole-file shape error, not a flight error: do not record each
        # key or character as a failed flight.
        raise TypeError(
            f"expected a sequence of flight objects, got {type(flights).__name__}"
        )

    result: list[pd.DataFrame] = []

    for index, flight in enumerate(flights):
        if failures is None:
            result.append(_flight_to_frame(flight, model_type))
            continue
        try:
            result.append(_flight_to_frame(flight, model_type))
        except Exception as exc:
            logger.debug("Flight %d could not be converted", index, exc_info=exc)
            failures.append(
                FlightConversionFailure(
                    index=index,
                    attrs=_identity_attrs(flight),
                    error=_without_tracebacks(exc),
                )
            )

    return result


def _flight_to_frame(flight: Mapping[str, Any], model_type: str) -> pd.DataFrame:
    """Convert one NEATS / NM JSON flight object (see ``neats_json_to_flights``)."""
    fi = flight.get("flight_information", {}) or {}
    ap = fi.get("aircraft_properties", {}) or {}
    fp = fi.get("fuel_properties", {}) or {}

    # -----------------------------
    # 2. Per-point rows (canonical column names)
    # -----------------------------
    rows: list[dict[str, Any]] = []

    tr = fi.get("trajectory", {}) or {}
    pts = tr.get("trajectory_data", []) or []

    for i, p in enumerate(pts):
        ts_raw = p.get("ts")

        if ts_raw is None:
            time_over = None
        else:
            # "2025-11-02T12:02:00+02:00" → "2025-11-02 10:02:00" (UTC);
            # the parser reads the result as UTC.
            try:
                time_over = _ts_to_utc_string(ts_raw)
            except ValueError as exc:
                raise ValueError(
                    f"flight {fi.get('flight_identification')!r}, "
                    f"trajectory point {i}: {exc}"
                ) from exc

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
                # PyNEATS input unit: m/s. The AO JSON field `tas` is in
                # knots. The NEATS application converts knots to m/s
                # (x 1852 / 3600) before calling PyNEATS. Values received
                # here must already be in m/s.
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
            # Above 1 set to 1.0 with a warning; a negative value fails
            # the flight in NeatsTrajectoryParser.
            "payload_factor": clamp_payload_factor(
                ap.get("load_factor"), fi.get("flight_identification")
            ),
            # Fuel (canonical names aligned with NEATSFuel / Flight4D)
            "hydrogen_content": fp.get("hydrogen_content"),
            "h_c_ratio": fp.get("hydrogen_per_carbon_ratio"),
            "aromatic_content": fp.get("aromatic_content"),
            # PyNEATS input unit: J/kg of fuel (lower calorific value).
            # The AO JSON field `calorific_value` is in MJ/kg of fuel.
            # The NEATS application multiplies by 1e6 before calling
            # PyNEATS. Values received here must already be in J/kg; do
            # not convert again.
            "q_fuel": fp.get("calorific_value"),
            "sulphur_content": fp.get("sulphur"),
            "naphthalene": fp.get("naphthalene"),
        }.items()
        if v is not None and k in allowed_attrs
    }
    df.attrs = attrs

    return df


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

    Notes
    -----
    No unit conversion is applied. Trajectory columns use the same names and
    units as the ``NeatsTrajectoryParser`` input (see
    ``neats_json_to_flights``): ``altitude`` in flight level, ``time`` as
    datetime64 (naive values are read as UTC, tz-aware values are converted
    to UTC) or as a string in the parser ``date_format``. Per-flight columns
    (e.g. ``q_fuel`` in J/kg, ``hydrogen_content`` in wt.%) are moved to
    ``df.attrs``.
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
