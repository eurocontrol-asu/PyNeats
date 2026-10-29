"""The AO load factor (``payload_factor``) is limited to 0-1 (audit A3).

``aircraft_properties.load_factor`` is payload mass / maximum payload mass,
used only when the AO gives neither ``am`` nor ``takeoff_mass``. It was copied
to ``payload_factor`` unchecked, so 1.5 or 80 (a percentage) gave more fuel
without a word, and -0.5 a take-off mass below OEW.

Now:
- 0 to 1 is kept unchanged, without a warning (0 is a ferry flight);
- above 1 is set to 1.0 with a warning naming the flight and the value, in
  ``neats_json_to_flights`` for JSON input and in the parser for DataFrame
  input (DLR test TC_LF_GT_ONE); it is not divided by 100;
- a negative value fails the flight at parsing, without retry; in a fleet the
  other flights go on;
- None and NaN keep their behaviour (default, with a warning for NaN, in the
  performance step).
"""

from __future__ import annotations

import copy
import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from pyneats.core.neats_default_parameters import DEFAULT_TRAJECTORY_PARSER
from pyneats.core.steps_registry import build
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.parsing.neats_io import concat_neats_flight
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.protocol import TrajectoryParser
from pyneats.steps.parsing.protocol import TrajectoryParserStepError
from pyneats.steps.weather.weather_store import ZarrPaths


GOLDEN_INPUT = Path(__file__).parent / "data" / "golden" / "fleet_5_flights_input.json"

REQUIRED_ATTRS = {
    "flight_id": "FL001",
    "aircraft_type": "A320",
    "departure_airport": "EGLL",
    "arrival_airport": "LFPG",
    "model_type": "BADA4",
    "aobt": "2023-01-01 10:00:00",
}


def _flight_df(**attrs: Any) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "latitude": [51.5, 51.6],
            "longitude": [-0.1, 0.0],
            "altitude": [100, 200],
            "time": ["2023-01-01 10:00:00", "2023-01-01 10:05:00"],
        }
    )
    df.attrs = {**REQUIRED_ATTRS, **attrs}
    return df


def _golden_flights() -> list[dict[str, Any]]:
    with GOLDEN_INPUT.open(encoding="utf-8") as fh:
        flights: list[dict[str, Any]] = json.load(fh)
    return flights


def _with_load_factor(
    flight: dict[str, Any], load_factor: Any, flight_id: str | None = None
) -> dict[str, Any]:
    out = copy.deepcopy(flight)
    fi = out["flight_information"]
    if flight_id is not None:
        fi["flight_identification"] = flight_id
    fi.setdefault("aircraft_properties", {})["load_factor"] = load_factor
    return out


def _load_factor_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING and "load_factor" in r.getMessage()
    ]


# ---------------------------------------------------------------------------
# JSON input (neats_json_to_flights)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("load_factor", [0.0, 0.8, 1.0])
def test_json_valid_load_factor_unchanged(
    load_factor: float, caplog: pytest.LogCaptureFixture
) -> None:
    flight = _with_load_factor(_golden_flights()[0], load_factor)
    with caplog.at_level(logging.WARNING):
        (df,) = neats_json_to_flights([flight])
    assert df.attrs["payload_factor"] == load_factor
    assert _load_factor_warnings(caplog) == []


@pytest.mark.parametrize("load_factor", [1.5, 80])
def test_json_load_factor_above_one_set_to_one(
    load_factor: float, caplog: pytest.LogCaptureFixture
) -> None:
    flight = _with_load_factor(_golden_flights()[0], load_factor, "LFHIGH")
    with caplog.at_level(logging.WARNING):
        (df,) = neats_json_to_flights([flight])
    assert df.attrs["payload_factor"] == 1.0
    (message,) = _load_factor_warnings(caplog)
    assert message == (
        f"Flight LFHIGH: payload_factor (AO load_factor) {load_factor:g} is above 1;"
        f" using 1.0"
    )


def test_json_negative_load_factor_left_to_the_parser() -> None:
    # Rejected in NeatsTrajectoryParser, as an out-of-range q_fuel is.
    failures: list[Any] = []
    flight = _with_load_factor(_golden_flights()[0], -0.5)
    (df,) = neats_json_to_flights([flight], failures=failures)
    assert failures == []
    assert df.attrs["payload_factor"] == -0.5
    with pytest.raises(TrajectoryParserStepError, match="is negative"):
        NeatsTrajectoryParser().run(df)


def test_json_missing_load_factor_still_absent() -> None:
    flight = _with_load_factor(_golden_flights()[0], None)
    (df,) = neats_json_to_flights([flight])
    assert "payload_factor" not in df.attrs


def test_json_then_parser_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    flight = _with_load_factor(_golden_flights()[0], 1.5, "LFHIGH")
    with caplog.at_level(logging.WARNING):
        (df,) = neats_json_to_flights([flight])
        parsed = NeatsTrajectoryParser().run(df)
    assert parsed.attrs["payload_factor"] == 1.0
    assert len(_load_factor_warnings(caplog)) == 1


# ---------------------------------------------------------------------------
# DataFrame input (NeatsTrajectoryParser, used by FlightRunner and FleetRunner)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("load_factor", [0.0, 0.8, 1.0])
def test_parser_valid_load_factor_unchanged(
    load_factor: float, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        flight = NeatsTrajectoryParser().run(_flight_df(payload_factor=load_factor))
    assert flight.attrs["payload_factor"] == load_factor
    assert _load_factor_warnings(caplog) == []


@pytest.mark.parametrize("load_factor", [1.5, 80.0])
def test_parser_load_factor_above_one_set_to_one(
    load_factor: float, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        flight = NeatsTrajectoryParser().run(_flight_df(payload_factor=load_factor))
    assert flight.attrs["payload_factor"] == 1.0
    (message,) = _load_factor_warnings(caplog)
    assert message == (
        f"Flight FL001: payload_factor (AO load_factor) {load_factor:g} is above 1;"
        f" using 1.0"
    )


def test_parser_numpy_load_factor_warning_shows_the_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # FleetRunner trajectory_dataframe input gives numpy scalars.
    with caplog.at_level(logging.WARNING):
        flight = NeatsTrajectoryParser().run(_flight_df(payload_factor=np.float64(1.5)))
    assert flight.attrs["payload_factor"] == 1.0
    assert _load_factor_warnings(caplog) == [
        "Flight FL001: payload_factor (AO load_factor) 1.5 is above 1; using 1.0"
    ]


@pytest.mark.parametrize("load_factor", [-0.5, -1e-9])
def test_parser_negative_load_factor_fails(load_factor: float) -> None:
    with pytest.raises(TrajectoryParserStepError) as exc_info:
        NeatsTrajectoryParser().run(_flight_df(payload_factor=load_factor))
    assert str(exc_info.value) == (
        f"payload_factor (AO load_factor) = {load_factor:g} is negative. It is a "
        f"fraction of the maximum payload, from 0 (no payload) to 1 (full payload)."
    )


def test_parser_load_factor_not_a_number_fails() -> None:
    with pytest.raises(TrajectoryParserStepError, match="is not a number"):
        NeatsTrajectoryParser().run(_flight_df(payload_factor="full"))


@pytest.mark.parametrize(
    ("load_factor", "expected"), [("0.8", 0.8), ("0", 0.0), ("1.5", 1.0)]
)
def test_parser_numeric_string_load_factor_stored_as_float(
    load_factor: str, expected: float
) -> None:
    flight = NeatsTrajectoryParser().run(_flight_df(payload_factor=load_factor))
    assert flight.attrs["payload_factor"] == expected
    assert isinstance(flight.attrs["payload_factor"], float)


def test_parser_numeric_string_negative_load_factor_fails() -> None:
    with pytest.raises(TrajectoryParserStepError, match="is negative"):
        NeatsTrajectoryParser().run(_flight_df(payload_factor="-0.5"))


def test_parser_pd_na_load_factor_stored_as_nan() -> None:
    # Treated as NaN: default with a warning in the performance step.
    flight = NeatsTrajectoryParser().run(_flight_df(payload_factor=pd.NA))
    assert math.isnan(flight.attrs["payload_factor"])


def test_parser_nan_load_factor_left_to_the_performance_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # bada_model._zero_fuel_weight uses the default with a warning (unchanged).
    with caplog.at_level(logging.WARNING):
        flight = NeatsTrajectoryParser().run(_flight_df(payload_factor=float("nan")))
    assert math.isnan(flight.attrs["payload_factor"])
    assert _load_factor_warnings(caplog) == []


def test_runner_default_parser_rejects_negative_load_factor() -> None:
    # FlightRunner and FleetRunner build their parser this way (default "neats").
    parser = build(TrajectoryParser, DEFAULT_TRAJECTORY_PARSER)  # type: ignore[type-abstract]
    assert isinstance(parser, NeatsTrajectoryParser)
    with pytest.raises(TrajectoryParserStepError, match="is negative"):
        parser(_flight_df(payload_factor=-0.5))


# ---------------------------------------------------------------------------
# FleetRunner: one bad flight fails alone, at parsing (no BADA or weather)
# ---------------------------------------------------------------------------


def _fleet_runner(tmp_path: Path, **source: Any) -> FleetRunnerLargeEmitter:
    cfg = FleetRunnerParams(
        zarr_paths=ZarrPaths(tmp_path / "met.zarr", tmp_path / "rad.zarr", None),
        bada_path=str(tmp_path),
        njobs=1,
        params={},
        **source,
    )
    return FleetRunnerLargeEmitter(cfg)


def _fleet_flights() -> list[dict[str, Any]]:
    flights = _golden_flights()
    return [
        _with_load_factor(flights[0], -0.5, "LFNEG"),
        _with_load_factor(flights[1], 1.5, "LFHIGH"),
        _with_load_factor(flights[2], 0.0, "LFZERO"),
        flights[3],
    ]


def _check_fleet(
    runner: FleetRunnerLargeEmitter, caplog: pytest.LogCaptureFixture
) -> None:
    runner._load_trajectories()
    with caplog.at_level(logging.WARNING):
        runner._parse_flight()

    assert not runner._pipeline_aborted
    assert runner.parsed_fleet is not None
    by_id = {f.attrs["flight_id"]: f for f in runner.parsed_fleet}
    assert set(by_id) == {
        "LFHIGH",
        "LFZERO",
        _golden_flights()[3]["flight_information"]["flight_identification"],
    }
    assert by_id["LFHIGH"].attrs["payload_factor"] == 1.0
    assert by_id["LFZERO"].attrs["payload_factor"] == 0.0
    assert {m for m in _load_factor_warnings(caplog) if "above 1" in m} == {
        "Flight LFHIGH: payload_factor (AO load_factor) 1.5 is above 1; using 1.0"
    }

    # Failed at parsing, so before the performance step and its retries.
    (record,) = runner.error_records
    assert record["flight_information"]["flight_id"] == "LFNEG"
    assert record["error"].startswith(
        "Failed at parsing: TrajectoryParserStepError('payload_factor (AO "
        "load_factor) = -0.5 is negative."
    )


def test_fleet_json_bad_flight_fails_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(_fleet_flights()), encoding="utf-8")
    _check_fleet(_fleet_runner(tmp_path, trajectory_json_filepath=str(path)), caplog)


def test_fleet_dataframe_bad_flight_fails_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Built without neats_json_to_flights, so the 1.5 reaches the parser.
    frames = neats_json_to_flights(_fleet_flights())
    frames[1].attrs["payload_factor"] = 1.5
    df = concat_neats_flight(frames)
    _check_fleet(_fleet_runner(tmp_path, trajectory_dataframe=df), caplog)
