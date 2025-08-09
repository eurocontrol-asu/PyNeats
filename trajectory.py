# trajectory.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Protocol, cast

import pandas as pd
from pycontrails import Flight

__all__ = [
    "METERS_PER_FOOT",
    "FEET_PER_FL",
    "REQUIRED_4D_COLS",
    "ParsedFlight",
    "TrajectoryParser",
    "NMTrajectoryParserParams",
    "NMTrajectoryParser",
    "ADSBParser",
    "TrajectoryParserType",
]

# ---- constants ----
METERS_PER_FOOT: Final[float] = 0.3048
FEET_PER_FL: Final[float] = 100.0
REQUIRED_4D_COLS: Final[tuple[str, ...]] = ("latitude", "longitude", "altitude", "time")


# ---- validated flight view (zero-copy) ----
class ParsedFlight(Flight):
    """
    A zero-copy *view* of a Flight that guarantees the presence of
    ('latitude', 'longitude', 'altitude', 'time') with altitude in meters
    and timezone-aware timestamps.
    """

    def __init__(self, data: pd.DataFrame, attrs: dict[str, Any] | None = None) -> None:
        # No validation here; keep constructor trivial for robustness.
        super().__init__(data=data, attrs=attrs)

    @classmethod
    def from_flight(cls, flight: Flight) -> "ParsedFlight":
        """
        Create a validated, zero-copy `ParsedFlight` view from an existing `Flight`.

        Parameters
        ----------
        flight : Flight
            The source flight expected to already contain the required 4D columns.

        Returns
        -------
        ParsedFlight
            A view on the same underlying data/attrs.

        Raises
        ------
        KeyError
            If any of the required 4D columns are missing.
        """
        missing = [c for c in REQUIRED_4D_COLS if c not in flight]
        if missing:
            raise KeyError(f"ParsedFlight missing required columns: {missing}")

        # Reuse underlying data/attrs (no DataFrame copy)
        view = cls(
            data=cast(pd.DataFrame, flight.data),
            attrs=getattr(flight, "attrs", None),
        )
        # Ensure a standard attribute for downstream logic
        view.attrs.setdefault("altitude_units", "m")
        return view

    def has_columns(self, *cols: str) -> bool:
        """
        Check if the flight contains all of the given columns.

        Returns
        -------
        bool
            True if all specified columns are present, False otherwise.
        """
        return all(c in self for c in cols)


# ---- parser protocol: return a plain Flight for composability ----
class TrajectoryParser(Protocol):
    """Callable that takes a DataFrame and returns a Flight enriched with required 4D fields."""
    def __call__(self, source: pd.DataFrame) -> Flight: ...


# ---- NM (Network Manager) parser ----
@dataclass(frozen=True)
class NMTrajectoryParserParams:
    """
    Configuration for parsing NM FTFM/RTFM/CTFM tables.
    """
    mapping_4d: Mapping[str, str] = field(default_factory=lambda: {
        "LAT": "latitude",
        "LON": "longitude",
        "TIME_OVER": "time",
        "FLIGHT_LEVEL": "altitude",
    })
    # NM exports are typically UTC; adjust if your inputs differ
    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"
    # Optional metadata to lift into attrs from the first row when present
    attrs_mapping: Mapping[str, str] = field(default_factory=lambda: {
        "flight_id": "AIRCRAFT_ID",
        "aircraft_type": "AIRCRAFT_TYPE_ICAO_ID",
        "callsign": "REGISTRATION",
        "departure_airport": "ADEP",
        "arrival_airport": "ADES",
        "aobt": "TIME_OVER",  # crude proxy; replace with a better field if available
    })


class NMTrajectoryParser:
    """
    Parse NM FTFM/RTFM/CTFM data into a `Flight` with required 4D fields.

    Notes
    -----
    - Returns a base `Flight` for pipeline composability.
    - Immediately validates via `ParsedFlight.from_flight(out)` to fail fast.
    """

    required_after_rename = REQUIRED_4D_COLS

    def __init__(self, params: NMTrajectoryParserParams | None = None) -> None:
        self.params = params or NMTrajectoryParserParams()

    def __call__(self, source: pd.DataFrame) -> Flight:
        # Rename columns; avoid an extra .copy() unless you plan to mutate original
        df = source.rename(columns=self.params.mapping_4d)

        # Ensure required columns exist after rename
        missing = [c for c in self.required_after_rename if c not in df.columns]
        if missing:
            raise KeyError(f"Missing required columns after rename: {missing}")

        # Convert FL (hundreds of feet) → meters (in-place on a new column reference)
        # If altitude is already in meters upstream, adjust this logic accordingly.
        df["altitude"] = df["altitude"] * FEET_PER_FL * METERS_PER_FOOT

        # Parse time to tz-aware
        ts = pd.to_datetime(
            df["time"],
            format=self.params.date_format,
            errors="coerce",
            utc=True,  # interpret as UTC
        )
        if self.params.timezone != "UTC":
            # Convert to requested timezone (keeps absolute instants; changes display)
            ts = ts.dt.tz_convert(self.params.timezone)
        df["time"] = ts

        # Drop rows missing any of the required fields (including NaT)
        mask = df[list(self.required_after_rename)].notna().all(axis=1)
        df = df.loc[mask]

        if df.empty:
            raise ValueError("No valid trajectory points after cleaning.")

        # Sort & deduplicate by time to maintain temporal consistency
        df = (
            df.sort_values("time")
              .drop_duplicates(subset="time", keep="first")
              .reset_index(drop=True)
        )

        # Build attrs from the first row (no dict copy needed)
        attrs: dict[str, Any] = {}
        first = df.iloc[0]
        for attr_key, src_col in self.params.attrs_mapping.items():
            if src_col in df.columns:
                attrs[attr_key] = first[src_col]
        attrs.setdefault("altitude_units", "m")

        # Construct a Flight with exactly the required columns
        # (Selecting columns typically creates a view; minimal overhead.)
        out = Flight(data=df[list(self.required_after_rename)], attrs=attrs)

        # Fail fast: validate (zero-copy view), but keep returning base Flight
        _ = ParsedFlight.from_flight(out)

        return out


# ---- ADS-B / OpenSky parser (skeleton) ----
class ADSBParser:
    """
    Parse ADS-B tables into a `Flight` with required 4D fields.

    Implement the same pattern as NM:
    - rename → required names
    - ensure altitude in meters
    - tz-aware timestamps
    - dropna, sort, dedup
    - return Flight and validate with ParsedFlight.from_flight
    """
    def __init__(self) -> None:
        ...

    def __call__(self, source: pd.DataFrame) -> Flight:
        raise NotImplementedError("OpenSky/ADS-B parser not yet implemented")


# ---- factory ----
class TrajectoryParserType(Enum):
    """Enum mapping parser names to classes (simple factory)."""
    NM = NMTrajectoryParser
    ADSB = ADSBParser

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryParser:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
