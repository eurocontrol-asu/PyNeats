# steps/trajectory.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Protocol, runtime_checkable

import pandas as pd
from pycontrails import Flight

from pyneats.core.constants import METERS_PER_FOOT, FEET_PER_FL
from pyneats.core.views import FlightView, ValidationError
from pyneats.core.steps import StepError  # for consistent domain errors

__all__ = [
    "REQUIRED_4D_COLS",
    "Flight4D",
    "FlightParsingError",
    "TrajectoryParser",
    "NMTrajectoryParserParams",
    "NMTrajectoryParser",
    "ADSBParser",
    "TrajectoryParserType",
]

logger = logging.getLogger(__name__)

# ---- schema constants -----------------------------------------------------------

REQUIRED_4D_COLS: Final[tuple[str, ...]] = ("latitude", "longitude", "altitude", "time")


# ---- errors --------------------------------------------------------------------

class FlightParsingError(StepError):
    """Raised when a trajectory table cannot be parsed into a valid Flight."""


# ---- validated 4D view (zero-copy) ---------------------------------------------

class Flight4D(FlightView):
    """Zero-copy, typed view ensuring ('latitude','longitude','altitude','time') exist."""
    REQUIRED  = REQUIRED_4D_COLS


# ---- parser protocol: return a validated ParsedFlight --------------------------

@runtime_checkable
class TrajectoryParser(Protocol):
    """Parses a tabular source into a validated `ParsedFlight` (zero-copy view)."""
    def __call__(self, source: pd.DataFrame) -> Flight4D: ...


# ---- NM (Network Manager) parser ----------------------------------------------

@dataclass(frozen=True)
class NMTrajectoryParserParams:
    # Map raw NM columns to canonical 4D names
    mapping_4d: Mapping[str, str] = field(
        default_factory=lambda: {
            "LAT": "latitude",
            "LON": "longitude",
            "TIME_OVER": "time",
            "FLIGHT_LEVEL": "altitude",   # FL (hundreds of feet)
        }
    )
    # Optional additional attrs to extract from the first row
    attrs_mapping: Mapping[str, str] = field(
        default_factory=lambda: {
            "flight_id": "AIRCRAFT_ID",
            "aircraft_type": "AIRCRAFT_TYPE_ICAO_ID",
            "callsign": "REGISTRATION",
            "departure_airport": "ADEP",
            "arrival_airport": "ADES",
            "aobt": "time",
        }
    )
    # Time parsing options
    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"  # output tz; parsing is done as UTC then converted

class NMTrajectoryParser:
    """
    Parse NM FTFM/RTFM/CTFM data into a `ParsedFlight`.

    Contract
    --------
    __call__(df: pd.DataFrame) -> ParsedFlight

    Notes
    -----
    - Altitude is expected as Flight Level (FL). Converted to meters.
    - Time is parsed as tz-aware timestamps in the configured timezone.
    - Output is a zero-copy `ParsedFlight` view (same underlying Flight).
    """

    required_after_rename: Final[tuple[str, ...]] = REQUIRED_4D_COLS

    def __init__(self, params: NMTrajectoryParserParams | None = None) -> None:
        self.params = params or NMTrajectoryParserParams()

    def __call__(self, source: pd.DataFrame) -> Flight4D:
        try:
            logger.debug("NM parse start: rows=%d, cols=%d", *source.shape)

            # 1) Rename columns to canonical 4D schema
            df = source.rename(columns=self.params.mapping_4d)
            missing = [c for c in self.required_after_rename if c not in df.columns]
            if missing:
                raise FlightParsingError(type(self).__name__, f"missing columns after rename: {missing}")

            # 2) Altitude: FL (hundreds of feet) -> meters
            try:
                df["altitude"] = df["altitude"] * FEET_PER_FL * METERS_PER_FOOT
            except Exception as e:
                raise FlightParsingError(type(self).__name__, f"altitude conversion failed: {e}") from e

            # 3) Parse time as tz-aware; convert if a timezone is requested
            try:
                ts = pd.to_datetime(df["time"], format=self.params.date_format, errors="coerce", utc=True)
                if self.params.timezone and self.params.timezone != "UTC":
                    ts = ts.dt.tz_convert(self.params.timezone)
                df["time"] = ts
            except Exception as e:
                raise FlightParsingError(type(self).__name__, f"timestamp parsing failed: {e}") from e

            # 4) Drop rows missing required fields, then sort & deduplicate by time
            mask = df[list(self.required_after_rename)].notna().all(axis=1)
            df = (
                df.loc[mask]
                  .sort_values("time")
                  .drop_duplicates(subset="time", keep="first")
                  .reset_index(drop=True)
            )
            if df.empty:
                raise FlightParsingError(type(self).__name__, "no valid trajectory points after cleaning")

            # 5) Build attrs from first row (optional convenience metadata)
            attrs: dict[str, Any] = {"altitude_units": "m"}
            first = df.iloc[0]
            for attr_key, src_col in self.params.attrs_mapping.items():
                if src_col in df.columns:
                    attrs[attr_key] = first[src_col]

            # 6) Construct base Flight with required columns only
            base = Flight(data=df[list(self.required_after_rename)], attrs=attrs)

            # 7) Validate and return typed zero-copy view
            return Flight4D.from_flight(base)

        except ValidationError as e:
            # Normalize view validation errors into parsing domain errors
            raise FlightParsingError(type(self).__name__, str(e)) from e
        except FlightParsingError:
            # Already normalized; just propagate
            raise
        except Exception as e:
            # Unexpected failure path
            logger.exception("Unexpected NM parsing error")
            raise FlightParsingError(type(self).__name__, f"unexpected: {e}") from e


# ---- ADS-B / OpenSky parser (skeleton) ----------------------------------------

class ADSBParser:
    """Placeholder for an ADS-B specific parser yielding `ParsedFlight`."""
    def __init__(self) -> None:
        ...

    def __call__(self, source: pd.DataFrame) -> Flight4D:
        raise FlightParsingError(type(self).__name__, "not implemented")


# ---- factory (kept like emissions) --------------------------------------------

class TrajectoryParserType(Enum):
    NM = NMTrajectoryParser
    ADSB = ADSBParser

    def get(self, *args: Any, **kwargs: Any) -> TrajectoryParser:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
