from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
import pandas as pd

from pycontrails import Flight
from pycontrails.physics.units import ft_to_m
from pyneats.core.steps import BaseStep
from pyneats.core.views import ValidationError
from pyneats.core.steps_registry import register
from pyneats.steps.parsing.params import TrajectoryParserParams
from pyneats.steps.parsing.views import Flight4D, REQUIRED_4D_COLS
from pyneats.steps.parsing.protocol import (
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
            "FUEL_FLOW": "fuel_flow",
            "ENGINE_EFFICIENCY": "engine_efficiency",
            "AIRCRAFT_MASS": "aircraft_mass",
            "TRUE_AIRSPEED": "true_airspeed",
        }
    )
    attrs_mapping: Mapping[str, str] = field(
        default_factory=lambda: {
            "flight_id": "AIRCRAFT_ID",
            "aircraft_type": "AIRCRAFT_TYPE_ICAO_ID",
            "aircraft_series": "AIRCRAFT_VERSION",
            "registration": "REGISTRATION",
            "departure_airport": "ADEP",
            "arrival_airport": "ADES",
            "aobt": "time",
            "takeoff_weight": "TAKEOFF_WEIGHT",
            "payload_factor": "PAYLOAD_FACTOR",
            "model_type": "MODEL_TYPE",
            "engine_id": "ENGINE_UID",
            "hydrogen_content": "HYDROGEN_CONTENT",
            "h_c_ratio": "HYDROGEN_PER_CARBON_RATIO",
            "aromatic_content": "AROMATIC_CONTENT",
            "q_fuel": "CALORIFIC_VALUE",
            "sulfur_content": "SULFUR",
            "naphthalene": "NAPHTHALENE",
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
    Parse Network Manager (NM) trajectory data or AO trajectory data into Flight4D format.
    __call__(df: pd.DataFrame) -> Flight4D

    It performs:

    - Column mapping to canonical schema
    - Unit conversions 
    - Timestamp parsing and timezone handling
    - Data cleaning and validation
    - Custom fuel properties handling
    - Schema validation

    The parser ensures:
    - All required columns are present
    - Numeric values are valid
    - Timestamps are properly formatted and timezone-aware
    - No duplicate timestamps exist
    - No missing values in required columns

    Attributes:
        default_params (NMTrajectoryParserParams): Default parameters for parsing


    Raises:
        TrajectoryParserStepError: If parsing fails due to:
            - Missing required columns
            - Invalid numeric values
            - Timestamp parsing errors
            - Empty trajectory after cleaning
            - Schema validation failures
    """

    default_params = NMTrajectoryParserParams

    def run(self, flight: pd.DataFrame) -> Flight4D:
        try:
            self.logger.debug("NM parse start: rows=%d, cols=%d", *flight.shape)

            # 1) Rename to canonical schema
            df = flight.rename(columns=self.params.mapping_4d)
            missing = [c for c in Flight4D.REQUIRED if c not in df.columns]

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
            # NOTE: Can AO upload NaNs? Then we should only sort by time here ...
            mask = df[list(REQUIRED_4D_COLS)].notna().all(axis=1)
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

            # 5) Build flight attributes 
            attrs: dict[str, Any] = {}
            first = df.iloc[0]

            for attr_key, src_col in self.params.attrs_mapping.items():
                if src_col in df.columns:
                    try:
                        attrs[attr_key] = first[src_col]
                    except (ValueError, TypeError):
                        self.logger.warning(
                            "invalid %r value: %r", attr_key, first[src_col]

                        )

            # 6) Construct Custom Fuel Object based on available attributes

            fuel_obj: NEATSFuel = NEATSFuel.from_attrs(attrs)
            
            # 7) Construct base Flight with required columns only
            # Keep required and optional columns

            optional_columns = [c for c in df.columns if c in Flight4D.OPTIONAL]
            data_req = df[list(Flight4D.REQUIRED) + list(optional_columns)]

            base = Flight(data=data_req, attrs=attrs, fuel=fuel_obj)

            # 8) Validate & return typed zero-copy view
            return Flight4D.from_flight(base)

        except ValidationError as e:
            raise TrajectoryParserStepError(str(e)) from e
        except TrajectoryParserStepError:
            raise
        except Exception as e:
            self.logger.exception("Unexpected NM parsing error")
            raise TrajectoryParserStepError(f"unexpected: {e}") from e
