from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping
import pandas as pd

from pycontrails import Flight
from pycontrails.physics.units import ft_to_m
from pyneats.core.steps import BaseStep
from pyneats.core.views import ValidationError
from pyneats.core.steps_registry import register
from pyneats.steps.trajectory.params import TrajectoryParserParams
from pyneats.steps.trajectory.views import Flight4D, REQUIRED_4D_COLS
from pyneats.steps.trajectory.protocol import (
    TrajectoryParserStepError,
    TrajectoryParser,
)
from pyneats.models.neats_fuel import NEATSFuel

__all__ = [
    "NMTrajectoryParserParams",
    "NMTrajectoryParser",
]


@dataclass(frozen=True)
class NMTrajectoryParserParams(TrajectoryParserParams):
    """Parameters for parsing NM (Network Manager) trajectory data."""

    mapping_4d: Mapping[str, str] = field(
        default_factory=lambda: {
            "LAT": "latitude",
            "LON": "longitude",
            "TIME_OVER": "time",
            "FLIGHT_LEVEL": "altitude",  # FL (hundreds of feet)
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
            "takeoff_weight": "TAKEOFF_WEIGHT",
            "payload_factor": "PAYLOAD_FACTOR",
            "model_type": "MODEL_TYPE",
        }
    )
    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"  # output tz; parsing is done as UTC then converted


@register(TrajectoryParser, "nm")
class NMTrajectoryParser(
    BaseStep[
        pd.DataFrame,
        Flight4D,
        NMTrajectoryParserParams,
    ]
):
    """
    Parse NM FTFM/RTFM/CTFM data into a `Flight4D`.
    __call__(df: pd.DataFrame) -> Flight4D
    """

    default_params = NMTrajectoryParserParams

    REQUIRED_AFTER_RENAME: Final[tuple[str, ...]] = REQUIRED_4D_COLS

    def run(self, flight: pd.DataFrame) -> Flight4D:
        try:
            self.logger.debug("NM parse start: rows=%d, cols=%d", *flight.shape)

            # 1) Rename to canonical schema
            df = flight.rename(columns=self.params.mapping_4d)
            missing = [c for c in self.REQUIRED_AFTER_RENAME if c not in df.columns]

            if missing:
                raise TrajectoryParserStepError(
                    f"missing columns after rename: {missing}"
                )

            # 2) FL → meters
            try:
                alt_ft = (
                    pd.to_numeric(df["altitude"], errors="coerce")
                    .mul(100.0)  # FL → ft
                    .to_numpy(dtype=float, copy=False)  # -> ndarray[float]
                )
                df["altitude"] = ft_to_m(alt_ft)

            except Exception as e:
                raise TrajectoryParserStepError(
                    f"altitude conversion failed: {e}"
                ) from e

            # 3) Parse time (tz-aware)
            try:
                ts = pd.to_datetime(
                    df["time"],
                    format=self.params.date_format,
                    errors="coerce",
                    utc=True,
                )
                if self.params.timezone and self.params.timezone != "UTC":
                    ts = ts.dt.tz_convert(self.params.timezone)
                df["time"] = ts
            except Exception as e:
                raise TrajectoryParserStepError(f"timestamp parsing failed: {e}") from e

            # 4) Clean, sort, dedup
            mask = df[list(self.REQUIRED_AFTER_RENAME)].notna().all(axis=1)
            df = (
                df.loc[mask]
                .sort_values("time")
                .drop_duplicates(subset="time", keep="first")
                .reset_index(drop=True)
            )

            if df.empty:
                raise TrajectoryParserStepError(
                    "no valid trajectory points after cleaning"
                )

            # 5) Build attrs
            attrs: dict[str, Any] = {"altitude_units": "m"}
            first = df.iloc[0]

            for attr_key, src_col in self.params.attrs_mapping.items():
                if src_col in df.columns:
                    attrs[attr_key] = first[src_col]

            # 6) Optional attributes:
            if "TAKEOFF_WEIGHT" in df.columns:
                try:
                    attrs["takeoff_weight"] = float(first["TAKEOFF_WEIGHT"])
                except (ValueError, TypeError):
                    self.logger.warning(
                        "invalid TAKEOFF_WEIGHT value: %r", first["TAKEOFF_WEIGHT"]
                    )

            if "PAYLOAD_FACTOR" in df.columns:
                try:
                    attrs["payload_factor"] = float(first["PAYLOAD_FACTOR"])
                except (ValueError, TypeError):
                    self.logger.warning(
                        "invalid PAYLOAD_FACTOR value: %r", first["PAYLOAD_FACTOR"]
                    )

            if "ENGINE_ID" in df.columns:
                try:
                    attrs["engine_type"] = str(first["ENGINE_ID"])
                except (ValueError, TypeError):
                    self.logger.warning(
                        "invalid ENGINE_ID value: %r", first["ENGINE_ID"]
                    )

            # optional custom-fuel inputs
            if "HYDROGEN_CONTENT" in df.columns:
                try:
                    attrs["hydrogen_content"] = float(first["HYDROGEN_CONTENT"])
                except (ValueError, TypeError):
                    self.logger.warning(
                        "invalid HYDROGEN_CONTENT value: %r", first["HYDROGEN_CONTENT"]
                    )

            if "H_C_RATIO" in df.columns:
                try:
                    attrs["h_c_ratio"] = float(first["H_C_RATIO"])
                except (ValueError, TypeError):
                    self.logger.warning(
                        "invalid HYDROGEN to CARBON RATIO value: %r", first["H_C_RATIO"]
                    )

            if "Q_FUEL" in df.columns:
                try:
                    attrs["q_fuel"] = float(first["Q_FUEL"])
                except (ValueError, TypeError):
                    self.logger.warning("invalid Q_FUEL value: %r", first["Q_FUEL"])

            # 7) Construct base Flight, with custom Fuel if provided

            qf: float | None = attrs.get("q_fuel")
            H: float | None = attrs.get("hydrogen_content")
            r: float | None = attrs.get("h_c_ratio")

            fuel_obj: NEATSFuel | None = None
            if any(v is not None for v in (qf, H, r)):
                try:
                    # Fuel attributes provided by AO, build custom fuel
                    # NEATSFuel signature: (*, hydrogen_content=None, h_c_ratio=None, q_fuel=None, ...)
                    fuel_obj = NEATSFuel(hydrogen_content=H, h_c_ratio=r, q_fuel=qf)
                except Exception as e:
                    self.logger.warning(
                        "Failed to build custom fuel from inputs (q_fuel=%r, hydrogen_content=%r, h_c_ratio=%r): %s",
                        qf,
                        H,
                        r,
                        e,
                    )
                    fuel_obj = None

            # 7) Construct base Flight with required columns only
            # Required columns only for Flight data
            data_req = df[list(self.REQUIRED_AFTER_RENAME)]

            if fuel_obj is not None:
                base = Flight(data=data_req, attrs=attrs, fuel=fuel_obj)
            else:
                base = Flight(data=data_req, attrs=attrs)

            # 8) Validate & return typed zero-copy view
            return Flight4D.from_flight(base)

        except ValidationError as e:
            raise TrajectoryParserStepError(str(e)) from e
        except TrajectoryParserStepError:
            raise
        except Exception as e:
            self.logger.exception("Unexpected NM parsing error")
            raise TrajectoryParserStepError(f"unexpected: {e}") from e
