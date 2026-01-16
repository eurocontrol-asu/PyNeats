from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd
from pycontrails import Flight
from pycontrails.physics.units import ft_to_m

from pyneats.core.neats_fuel import NEATSFuel
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.core.views import ValidationError
from pyneats.steps.parsing.params import TrajectoryParserParams
from pyneats.steps.parsing.protocol import (
    TrajectoryParser,
    TrajectoryParserStepError,
)
from pyneats.steps.parsing.views import REQUIRED_4D_COLS, Flight4D

__all__ = [
    "NeatsTrajectoryParserParams",
    "NeatsTrajectoryParser",
]


@dataclass(frozen=True)
class NeatsTrajectoryParserParams(TrajectoryParserParams):
    """Parameters for parsing NM (Network Manager) trajectory data."""

    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"  # output tz; parsing is done as UTC then converted


@register(TrajectoryParser, "neats")
class NeatsTrajectoryParser(
    BaseStep[
        pd.DataFrame,
        Flight4D,
        NeatsTrajectoryParserParams,
    ]
):
    """
    Parse NM trajectory data or AO trajectory data that follows NEATS Json format into Flight4D format.
    __call__(df: pd.DataFrame) -> Flight4D

    It performs:


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

    default_params = NeatsTrajectoryParserParams

    def run(self, flight: pd.DataFrame) -> Flight4D:
        try:
            self.logger.debug("NM parse start: rows=%d, cols=%d", *flight.shape)

            # 1) Check presence of required columns
            missing = [c for c in Flight4D.REQUIRED if c not in flight.columns]
            if missing:
                raise TrajectoryParserStepError(f"missing required columns: {missing}")

            # 2) FL → meters
            try:
                alt_ft = (
                    pd.to_numeric(flight["altitude"], errors="coerce")
                    .mul(100.0)  # FL → ft
                    .to_numpy(dtype=float, copy=False)
                )
                df = flight
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

            # 5) Build flight attributes from df.attrs (canonical keys)
            attrs_input: Mapping[str, Any] = getattr(df, "attrs", {}) or {}
            attrs: dict[str, Any] = {}

            # Required attrs must be present (or you'll get ValidationError downstream)
            for k in Flight4D.ATTRS_REQUIRED:
                if k in attrs_input and attrs_input[k] is not None:
                    attrs[k] = attrs_input[k]

            # Optional attrs if present
            for k in Flight4D.ATTRS_OPTIONAL:
                if k in attrs_input and attrs_input[k] is not None:
                    attrs[k] = attrs_input[k]

            # 6) Construct Custom Fuel Object based on available attributes
            fuel_obj: NEATSFuel = NEATSFuel.from_attrs(attrs)

            # 7) Construct base Flight with required + optional columns only
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
