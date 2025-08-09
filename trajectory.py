from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Mapping, Any, Final, cast
from enum import Enum
import inspect
import pandas as pd

from pycontrails import Flight

# ---- constants ----
METERS_PER_FOOT: Final[float] = 0.3048
FEET_PER_FL: Final[float] = 100.0
REQUIRED_4D_COLS: Final[tuple[str, ...]] = ("latitude", "longitude", "altitude", "time")


# ---- validated flight type ----
class ParsedFlight(Flight):
    """
    A Flight guaranteed to contain latitude, longitude, altitude (m), and time (tz-aware).

    Notes
    -----
    - Validates presence of required columns only (O(#cols)); no DataFrame copy.
    - `from_flight` reuses the underlying data; no large allocations.
    """

    def __init__(self, data: pd.DataFrame, attrs: dict[str, Any] | None = None) -> None:
        super().__init__(data=data, attrs=attrs)
        missing = [c for c in REQUIRED_4D_COLS if c not in self]
        if missing:
            raise KeyError(f"ParsedFlight missing required columns: {missing}")
        self.attrs.setdefault("altitude_units", "m")

    @classmethod
    def from_flight(cls, flight: Flight) -> ParsedFlight:
        """
        Wrap an existing Flight in a ParsedFlight without copying data.

        Parameters
        ----------
        flight : Flight
            Existing Flight object to wrap.

        Returns
        -------
        ParsedFlight
            A validated wrapper around the original Flight data.

        Raises
        ------
        KeyError
            If any of the required 4D columns are missing.
        """
        missing = [c for c in REQUIRED_4D_COLS if c not in flight]
        if missing:
            raise KeyError(f"ParsedFlight missing required columns: {missing}")

        return cls(
            data=cast(pd.DataFrame, flight.data),
            attrs=dict(flight.attrs),
        )


# ---- single protocol for all parsers ----
class TrajectoryParser(Protocol):
    """Callable that takes a DataFrame and returns a validated ParsedFlight."""
    def __call__(self, source: pd.DataFrame) -> ParsedFlight: ...


# ---- NM parser ----
@dataclass(frozen=True)
class NMTrajectoryParserParams:
    """Configuration for parsing NM flights from raw DataFrame."""
    mapping_4d: Mapping[str, str] = field(default_factory=lambda: {
        "LAT": "latitude",
        "LON": "longitude",
        "TIME_OVER": "time",
        "FLIGHT_LEVEL": "altitude",
    })
    # NM exports are typically UTC
    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"
    attrs_mapping: Mapping[str, str] = field(default_factory=lambda: {
        "flight_id": "AIRCRAFT_ID",
        "aircraft_type": "AIRCRAFT_TYPE_ICAO_ID",
        "callsign": "REGISTRATION",
        "departure_airport": "ADEP",
        "arrival_airport": "ADES",
        "aobt": "time",  # first timestamp as proxy; adjust if better field
    })


class NMTrajectoryParser:
    """Parse NM FTFM/RTFM/CTFM data into a ParsedFlight (altitude in meters)."""

    required_after_rename = REQUIRED_4D_COLS

    def __init__(self, params: NMTrajectoryParserParams | None = None) -> None:
        self.params = params or NMTrajectoryParserParams()

    def __call__(self, source: pd.DataFrame) -> ParsedFlight:
        # Rename and copy to avoid chained assignment
        df = source.rename(columns=self.params.mapping_4d).copy()

        # Validate required columns exist post-rename
        missing = [c for c in self.required_after_rename if c not in df.columns]
        if missing:
            raise KeyError(f"Missing required columns after rename: {missing}")

        # Convert FL (hundreds of feet) → meters
        df["altitude"] *= FEET_PER_FL * METERS_PER_FOOT
        # Parse time to tz-aware (UTC)
        ts = pd.to_datetime(
            df["time"],
            format=self.params.date_format,
            errors="coerce",
            utc=True,
        )
        if self.params.timezone != "UTC":
            ts = ts.dt.tz_convert(self.params.timezone)
        df["time"] = ts

        # Drop rows missing any required fields (including NaT)
        mask = df[list(self.required_after_rename)].notna().all(axis=1)
        df = df.loc[mask]


        # Sort and deduplicate by time
        df = (
            df.sort_values("time")
              .drop_duplicates(subset="time", keep="first")
              .reset_index(drop=True)
        )

        if df.empty:
            raise ValueError("No valid trajectory points after cleaning.")

        # Build attrs from the first row (if present)
        attrs: dict[str, Any] = {}
        for key, col in self.params.attrs_mapping.items():
            if col in df.columns:
                attrs[key] = df[col].iloc[0]
        attrs.setdefault("altitude_units", "m")

        return ParsedFlight(data=df[list(self.required_after_rename)], attrs=attrs)


# ---- OpenSky parser (same signature; implement when schema is known) ----
class ADSBParser:
    """Parse ADS-B data into a ParsedFlight (to be implemented)."""

    def __init__(self) -> None:
        ...

    def __call__(self, source: pd.DataFrame) -> ParsedFlight:
        # TODO:
        # 1) rename columns → ("latitude","longitude","altitude","time")
        # 2) ensure altitude is meters (convert if needed)
        # 3) dropna, sort, dedup
        # 4) return ParsedFlight(data=df[list(REQUIRED_4D_COLS)], attrs=attrs)
        raise NotImplementedError("OpenSky Parser not yet implemented")


# ---- factory ----
class TrajectoryParserType(Enum):
    """Enum mapping parser names to classes; safe factory that handles params when supported."""
    NM = NMTrajectoryParser
    ADSB = ADSBParser

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryParser:
        cls = self.value
        sig = inspect.signature(cls)
        try:
            sig.bind_partial(*args, **kwargs)
            return cls(*args, **kwargs)  # type: ignore[call-arg]
        except TypeError:
            return cls()  # constructor takes no params
