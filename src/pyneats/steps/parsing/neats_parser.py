"""
NEATS Trajectory Parser Module

Implements parsing of NM (Network Manager) and AO trajectory data in NEATS JSON format into Flight4D format.
"""

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
from pyneats.steps.parsing.protocol import TrajectoryParser
from pyneats.steps.parsing.protocol import TrajectoryParserStepError
from pyneats.steps.parsing.views import REQUIRED_4D_COLS
from pyneats.steps.parsing.views import Flight4D


__all__ = [
    "NeatsTrajectoryParserParams",
    "NeatsTrajectoryParser",
]


def _load_airport_q_fuel(path: str | None) -> dict[str, float]:
    """Load airport→q_fuel mapping; returns {} on missing/invalid file (with warning)."""
    if path is None:
        return {}
    import csv
    import json
    import logging
    from pathlib import Path as _Path

    p = _Path(path)
    try:
        if p.suffix.lower() == ".json":
            with p.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            return {str(k).upper(): float(v) for k, v in raw.items()}
        # Default: CSV with columns "airport" and "q_fuel"
        result: dict[str, float] = {}
        with p.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                result[row["airport"].strip().upper()] = float(row["q_fuel"])
        return result
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Failed to load airport q_fuel mapping from %s: %s — using default q_fuel",
            path,
            exc,
        )
        return {}


@dataclass(frozen=True)
class NeatsTrajectoryParserParams(TrajectoryParserParams):
    """
    Parameters for parsing NM (Network Manager) trajectory data.

    Attributes
    ----------
    date_format : str
        Format string for parsing dates.
    timezone : str
        Output timezone; parsing is done as UTC then converted.
    airport_qfuel_path : str | None
        Optional path to a CSV or JSON file mapping airport codes to q_fuel values.
    """

    date_format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"  # output tz; parsing is done as UTC then converted
    airport_qfuel_path: str | None = None


@register(TrajectoryParser, "neats")  # type: ignore[type-abstract]
class NeatsTrajectoryParser(
    BaseStep[
        pd.DataFrame,
        Flight4D,
        NeatsTrajectoryParserParams,
    ]
):
    """
    Step for parsing NM or AO trajectory data (NEATS JSON format) into Flight4D format.

    Performs:
    - Data cleaning and validation
    - Custom fuel properties handling
    - Schema validation

    Ensures:
    - All required columns are present
    - Numeric values are valid
    - Timestamps are properly formatted and timezone-aware
    - No duplicate timestamps exist
    - No missing values in required columns
    """

    # ...existing code...

    default_params = NeatsTrajectoryParserParams

    def _post_init(self) -> None:
        self._airport_q_fuel: dict[str, float] = _load_airport_q_fuel(
            self.params.airport_qfuel_path
        )

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
                df = flight.copy()
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

            # 5.5) Airport-based q_fuel fallback (operator value takes precedence)
            if attrs.get("q_fuel") is None and self._airport_q_fuel:
                airport = str(attrs.get("departure_airport", "")).upper()
                if airport in self._airport_q_fuel:
                    attrs["q_fuel"] = self._airport_q_fuel[airport]
                    self.logger.debug(
                        "Airport q_fuel for %s: %s J/kg", airport, attrs["q_fuel"]
                    )

            # 6) Guard: list engine_uid is only supported by FleetRunner
            if isinstance(attrs.get("engine_uid"), list):
                raise TrajectoryParserStepError(
                    "engine_uid is a list of engine types; multi-engine flights must be "
                    "processed with FleetRunner, not FlightRunner."
                )

            # 7) Construct Custom Fuel Object based on available attributes
            fuel_obj: NEATSFuel = NEATSFuel.from_attrs(attrs)

            # 8) Construct base Flight with required + optional columns only
            optional_columns = [c for c in df.columns if c in Flight4D.OPTIONAL]
            data_req = df[list(Flight4D.REQUIRED) + list(optional_columns)]

            base = Flight(data=data_req, attrs=attrs, fuel=fuel_obj)

            # 9) Validate & return typed zero-copy view
            return Flight4D.from_flight(base)

        except ValidationError as e:
            raise TrajectoryParserStepError(str(e)) from e
        except TrajectoryParserStepError:
            raise
        except Exception as e:
            self.logger.exception("Unexpected NM parsing error")
            raise TrajectoryParserStepError(f"unexpected: {e}") from e
