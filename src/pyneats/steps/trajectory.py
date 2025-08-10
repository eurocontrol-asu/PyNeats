# trajectory.py
from __future__ import annotations

import logging
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
    "FlightParsingError",
]

logger = logging.getLogger(__name__)

# ---- constants ----
METERS_PER_FOOT: Final[float] = 0.3048
FEET_PER_FL: Final[float] = 100.0
REQUIRED_4D_COLS: Final[tuple[str, ...]] = ("latitude", "longitude", "altitude", "time")


# ---- error type ----
class FlightParsingError(RuntimeError):
    """Raised when a trajectory table cannot be parsed into a valid Flight."""


# ---- validated flight view (zero-copy) ----
class ParsedFlight(Flight):
    """Zero-copy view ensuring ('latitude','longitude','altitude','time') exist."""

    def __init__(self, data: pd.DataFrame, attrs: dict[str, Any] | None = None) -> None:
        super().__init__(data=data, attrs=attrs)

    @classmethod
    def from_flight(cls, flight: Flight) -> "ParsedFlight":
        missing = [c for c in REQUIRED_4D_COLS if c not in flight]
        if missing:
            raise KeyError(f"ParsedFlight missing required columns: {missing}")
        view = cls(
            data=cast(pd.DataFrame, flight.data),
            attrs=getattr(flight, "attrs", None),
        )
        view.attrs.setdefault("altitude_units", "m")
        return view

    def has_columns(self, *cols: str) -> bool:
        return all(c in self for c in cols)


# ---- parser protocol: return a plain Flight for composability ----
class TrajectoryParser(Protocol):
    def __call__(self, source: pd.DataFrame) -> Flight: ...


# ---- NM (Network Manager) parser ----
@dataclass(frozen=True)
class NMTrajectoryParserParams:
    mapping_4d: Mapping[str, str] = field(default_factory=lambda: {
        "LAT": "latitude",
        "LON": "longitude",
        "TIME_OVER": "time",
        "FLIGHT_LEVEL": "altitude",
    })
    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"
    attrs_mapping: Mapping[str, str] = field(default_factory=lambda: {
        "flight_id": "AIRCRAFT_ID",
        "aircraft_type": "AIRCRAFT_TYPE_ICAO_ID",
        "callsign": "REGISTRATION",
        "departure_airport": "ADEP",
        "arrival_airport": "ADES",
        "aobt": "time",
    })


class NMTrajectoryParser:
    """Parse NM FTFM/RTFM/CTFM data into a `Flight` with required 4D fields."""

    required_after_rename = REQUIRED_4D_COLS

    def __init__(self, params: NMTrajectoryParserParams | None = None) -> None:
        self.params = params or NMTrajectoryParserParams()

    def __call__(self, source: pd.DataFrame) -> Flight:
        logger.debug("Starting NM trajectory parsing; rows=%d, cols=%d", *source.shape)

        # 1) Rename columns
        df = source.rename(columns=self.params.mapping_4d)
        missing = [c for c in self.required_after_rename if c not in df.columns]
        if missing:
            logger.error("Missing required columns after rename: %s", missing)
            raise FlightParsingError(f"Missing required columns after rename: {missing}")

        # 2) Altitude: FL (hundreds of feet) -> meters
        try:
            df["altitude"] = df["altitude"] * FEET_PER_FL * METERS_PER_FOOT
        except Exception as e:
            logger.exception("Failed converting altitude to meters")
            raise FlightParsingError(f"Failed converting altitude to meters: {e}") from e

        # 3) Parse time to tz-aware
        try:
            ts = pd.to_datetime(
                df["time"],
                format=self.params.date_format,
                errors="coerce",
                utc=True,
            )
            if self.params.timezone != "UTC":
                ts = ts.dt.tz_convert(self.params.timezone)
            df["time"] = ts
        except Exception as e:
            logger.exception("Failed parsing timestamps")
            raise FlightParsingError(f"Failed parsing timestamps: {e}") from e

        # 4) Drop rows with missing required fields
        mask = df[list(self.required_after_rename)].notna().all(axis=1)
        df = df.loc[mask]
        if df.empty:
            logger.error("No valid trajectory points after cleaning")
            raise FlightParsingError("No valid trajectory points after cleaning.")

        # 5) Sort & deduplicate by time
        df = (
            df.sort_values("time")
              .drop_duplicates(subset="time", keep="first")
              .reset_index(drop=True)
        )

        # 6) Build attrs from first row
        attrs: dict[str, Any] = {}
        first = df.iloc[0]
        for attr_key, src_col in self.params.attrs_mapping.items():
            if src_col in df.columns:
                attrs[attr_key] = first[src_col]
        attrs.setdefault("altitude_units", "m")

        # 7) Construct base Flight and validate (zero-copy view)
        out = Flight(data=df[list(self.required_after_rename)], attrs=attrs)
        try:
            _ = ParsedFlight.from_flight(out)
        except KeyError as e:
            logger.error("ParsedFlight validation failed: %s", e)
            raise FlightParsingError(f"Validation failed: {e}") from e

        logger.info("NM trajectory parsing done; points=%d", len(out.data))
        return out


# ---- ADS-B / OpenSky parser (skeleton) ----
class ADSBParser:
    def __init__(self) -> None:
        ...

    def __call__(self, source: pd.DataFrame) -> Flight:
        raise NotImplementedError("OpenSky/ADS-B parser not yet implemented")


# ---- factory ----
class TrajectoryParserType(Enum):
    NM = NMTrajectoryParser
    ADSB = ADSBParser

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryParser:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
