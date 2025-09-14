from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Mapping

import pandas as pd
from pycontrails import Flight

from pyneats.core.steps import BaseStage, StepError
from pyneats.core.views import ValidationError
from pyneats.core.constants import METERS_PER_FOOT, FEET_PER_FL
from pyneats.steps.trajectory.views import Flight4D, REQUIRED_4D_COLS

__all__ = ["FlightParsingError", "NMTrajectoryParserParams", "NMTrajectoryParser"]

logger = logging.getLogger(__name__)

class FlightParsingError(StepError):
    """Raised when a trajectory table cannot be parsed into a valid Flight."""

@dataclass(frozen=True)
class NMTrajectoryParserParams:
    """Parameters for parsing NM (Network Manager) trajectory data."""
    mapping_4d: Mapping[str, str] = field(
        default_factory=lambda: {
            "LAT": "latitude",
            "LON": "longitude",
            "TIME_OVER": "time",
            "FLIGHT_LEVEL": "altitude",   # FL (hundreds of feet)
        }
    )
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
    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"  # output tz; parsing is done as UTC then converted

class NMTrajectoryParser(BaseStage[pd.DataFrame, Flight4D]):
    """
    Parse NM FTFM/RTFM/CTFM data into a `Flight4D`.
    __call__(df: pd.DataFrame) -> Flight4D
    """

    REQUIRED_AFTER_RENAME: Final[tuple[str, ...]] = REQUIRED_4D_COLS

    def __init__(self, params: NMTrajectoryParserParams | None = None) -> None:
        super().__init__()
        self.params = params or NMTrajectoryParserParams()

    def run(self, source: pd.DataFrame) -> Flight4D:
        try:
            logger.debug("NM parse start: rows=%d, cols=%d", *source.shape)

            # 1) Rename to canonical schema
            df = source.rename(columns=self.params.mapping_4d)
            missing = [c for c in self.REQUIRED_AFTER_RENAME if c not in df.columns]
            if missing:
                raise FlightParsingError(type(self).__name__,
                                         f"missing columns after rename: {missing}")

            # 2) FL → meters
            try:
                df["altitude"] = df["altitude"] * FEET_PER_FL * METERS_PER_FOOT
            except Exception as e:
                raise FlightParsingError(type(self).__name__,
                                         f"altitude conversion failed: {e}") from e

            # 3) Parse time (tz-aware)
            try:
                ts = pd.to_datetime(df["time"],
                                    format=self.params.date_format,
                                    errors="coerce", utc=True)
                if self.params.timezone and self.params.timezone != "UTC":
                    ts = ts.dt.tz_convert(self.params.timezone)
                df["time"] = ts
            except Exception as e:
                raise FlightParsingError(type(self).__name__,
                                         f"timestamp parsing failed: {e}") from e

            # 4) Clean, sort, dedup
            mask = df[list(self.REQUIRED_AFTER_RENAME)].notna().all(axis=1)
            df = (
                df.loc[mask]
                  .sort_values("time")
                  .drop_duplicates(subset="time", keep="first")
                  .reset_index(drop=True)
            )
            if df.empty:
                raise FlightParsingError(type(self).__name__,
                                         "no valid trajectory points after cleaning")

            # 5) Build attrs (optional convenience)
            attrs: dict[str, Any] = {"altitude_units": "m"}
            first = df.iloc[0]
            for attr_key, src_col in self.params.attrs_mapping.items():
                if src_col in df.columns:
                    attrs[attr_key] = first[src_col]

            # 6) Construct base Flight with required columns only
            base = Flight(data=df[list(self.REQUIRED_AFTER_RENAME)], attrs=attrs)

            # 7) Validate & return typed zero-copy view
            return Flight4D.from_flight(base)

        except ValidationError as e:
            raise FlightParsingError(type(self).__name__, str(e)) from e
        except FlightParsingError:
            raise
        except Exception as e:
            logger.exception("Unexpected NM parsing error")
            raise FlightParsingError(type(self).__name__, f"unexpected: {e}") from e
