"""DataFrame input with a list-valued attr (bug DF-ME).

A multi-engine flight (``engine_uid`` given as a list) given as a DataFrame
(``FleetRunnerParams.trajectory_dataframe``, built with ``concat_neats_flight``)
must give the same flights as the same flight given as JSON.
``split_df_into_flights`` used ``pd.notna`` on each flight-level cell, and
``pd.notna`` on a list gives an array, so the split raised ``ValueError``.

Tests cover:
- ``split_df_into_flights``: list attrs are kept, tuple and array attrs are
  kept as lists, scalar missing values (None, NaN, NaT, pd.NA) are dropped as
  before
- ``concat_neats_flight`` -> ``split_df_into_flights`` round trip: the same
  attrs and trajectory as ``neats_json_to_flights``
- ``FleetRunner``: load, multi-engine expansion, parsing and interpolation give
  the same flights and error records for JSON and DataFrame input (no weather
  needed; these call the private steps that ``eval()`` calls)
- ``FleetRunnerLargeEmitter.eval()``: the same results for JSON and DataFrame
  input, including the merge of the engine copies (needs weather and BADA, so
  it is skipped in a run without weather)
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from pyneats.runners.fleet import FleetRunner
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.steps.parsing.neats_io import _is_missing_attr
from pyneats.steps.parsing.neats_io import concat_neats_flight
from pyneats.steps.parsing.neats_io import neats_json_to_flights
from pyneats.steps.parsing.neats_io import split_df_into_flights
from pyneats.steps.weather.weather_store import ZarrPaths


GOLDEN_INPUT = Path(__file__).parent / "data" / "golden" / "fleet_5_flights_input.json"
ENGINES = ["1IA001", "3CM026"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _golden_json(engine_uid: Any = None, n_flights: int | None = None) -> list[dict]:
    """Golden input flights; the first gets ``engine_uid`` if one is given."""
    with GOLDEN_INPUT.open(encoding="utf-8") as fh:
        flights = json.load(fh)
    if n_flights is not None:
        flights = flights[:n_flights]
    if engine_uid is not None:
        flights[0]["flight_information"]["aircraft_properties"]["engine_uid"] = (
            engine_uid
        )
    return flights


def _json_and_df_flights(
    raw: list[dict],
) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    """Per-flight DataFrames from the JSON path and from the DataFrame path."""
    json_flights = neats_json_to_flights(copy.deepcopy(raw))
    df_flights = split_df_into_flights(
        concat_neats_flight(neats_json_to_flights(copy.deepcopy(raw)))
    )
    return json_flights, df_flights


def _assert_same_flights(
    expected: list[pd.DataFrame], actual: list[pd.DataFrame]
) -> None:
    """Same attrs (keys, values, types) and same trajectory, flight by flight.

    The column order is not compared: ``split_df_into_flights`` reorders the
    trajectory columns.
    """
    assert len(actual) == len(expected)
    for exp, act in zip(expected, actual, strict=True):
        assert act.attrs.keys() == exp.attrs.keys()
        for key, value in exp.attrs.items():
            assert type(act.attrs[key]) is type(value), key
            assert act.attrs[key] == value, key
        assert sorted(act.columns) == sorted(exp.columns)
        pd.testing.assert_frame_equal(
            act[list(exp.columns)].reset_index(drop=True),
            exp.reset_index(drop=True),
        )


def _same_value(a: Any, b: Any) -> bool:
    """Recursive equality in which NaN equals NaN."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same_value(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(
            _same_value(x, y) for x, y in zip(a, b, strict=True)
        )
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or a == b
    return bool(a == b)


def _runner_params(tmp_path: Path, raw: list[dict], *, as_dataframe: bool) -> dict:
    """FleetRunnerParams kwargs for JSON (file) or DataFrame input."""
    if as_dataframe:
        df = concat_neats_flight(neats_json_to_flights(copy.deepcopy(raw)))
        return {"trajectory_dataframe": df}
    path = tmp_path / "flights.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return {"trajectory_json_filepath": str(path)}


# ---------------------------------------------------------------------------
# _is_missing_attr / split_df_into_flights
# ---------------------------------------------------------------------------


class TestIsMissingAttr:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            np.nan,
            float("nan"),
            pd.NaT,
            pd.NA,
            np.datetime64("NaT"),
            0,
            0.0,
            "",
            "nan",
            " ",
            "A320",
            1.5,
            np.float64(2.0),
            True,
            pd.Timestamp("2025-01-01"),
            np.array(np.nan),
            np.array(None),
            np.array("A320"),
        ],
    )
    def test_scalar_matches_pd_notna(self, value):
        assert _is_missing_attr(value) is (not pd.notna(value))

    @pytest.mark.parametrize(
        "value",
        [
            ["1IA001", "3CM026"],
            ["1IA001"],
            [],
            [np.nan],
            ("1IA001", "3CM026"),
            np.array(["1IA001", "3CM026"]),
            np.array([np.nan, np.nan]),
            {"a": 1},
        ],
    )
    def test_list_or_array_is_a_value(self, value):
        assert _is_missing_attr(value) is False


class TestSplitListAttrs:
    def test_list_engine_uid_does_not_raise(self):
        raw = _golden_json(engine_uid=ENGINES, n_flights=1)
        flights = split_df_into_flights(concat_neats_flight(neats_json_to_flights(raw)))
        assert len(flights) == 1
        assert flights[0].attrs["engine_uid"] == ENGINES

    def test_list_engine_uid_same_as_json(self):
        json_flights, df_flights = _json_and_df_flights(_golden_json(ENGINES))
        _assert_same_flights(json_flights, df_flights)
        assert df_flights[0].attrs["engine_uid"] == ENGINES

    @pytest.mark.parametrize(
        "engine_uid", [["1IA001", "3CM026", "3CM026", "1IA001"], ["3CM026"]]
    )
    def test_list_lengths_same_as_json(self, engine_uid):
        """JSON and DataFrame agree for 4 engines and for 1 engine.

        The 1-engine case is an agreement check only: on dev ``pd.notna`` on a
        1-element list gives a 1-element array, which ``if`` accepts.
        """
        json_flights, df_flights = _json_and_df_flights(_golden_json(engine_uid))
        _assert_same_flights(json_flights, df_flights)

    def test_any_list_or_array_attr_is_kept(self):
        """Not only engine_uid: any list or array cell is kept unchanged."""
        n = 3
        df = pd.DataFrame(
            {
                "flight_id": ["F1"] * n,
                "departure_airport": ["EGLL"] * n,
                "arrival_airport": ["LFPG"] * n,
                "aobt": ["2025-01-01 08:00:00"] * n,
                "latitude": [51.0, 51.5, 52.0],
                "longitude": [0.0, 0.5, 1.0],
                "altitude": [100.0, 300.0, 350.0],
                "time": pd.date_range("2025-01-01 08:00", periods=n, freq="1min"),
                "tags": [["a", "b"]] * n,
                "empty": [[]] * n,
                "nan_list": [[np.nan]] * n,
                "array": [np.array([1.0, 2.0])] * n,
            }
        )
        (flight,) = split_df_into_flights(df)
        assert flight.attrs["tags"] == ["a", "b"]
        assert flight.attrs["empty"] == []
        assert len(flight.attrs["nan_list"]) == 1
        assert math.isnan(flight.attrs["nan_list"][0])
        assert flight.attrs["array"] == [1.0, 2.0]
        assert type(flight.attrs["array"]) is list

    @pytest.mark.parametrize(
        "cell", [tuple(ENGINES), np.array(ENGINES), np.array(ENGINES, dtype=object)]
    )
    def test_tuple_or_array_engine_uid_becomes_list(self, cell):
        """A tuple or array cell (e.g. read back from Parquet) is a list in attrs."""
        json_flights, _ = _json_and_df_flights(_golden_json(ENGINES))
        df = concat_neats_flight(neats_json_to_flights(_golden_json(ENGINES)))
        cells = np.empty(len(df), dtype=object)
        for i, (fid, value) in enumerate(zip(df["flight_id"], df["engine_uid"])):
            cells[i] = cell if fid == df["flight_id"].iloc[0] else value
        df["engine_uid"] = cells
        df_flights = split_df_into_flights(df)
        _assert_same_flights(json_flights, df_flights)
        assert df_flights[0].attrs["engine_uid"] == ENGINES


class TestSplitScalarAttrsUnchanged:
    def test_golden_round_trip_same_as_json(self):
        """Scalar-only fleet: concat -> split gives the JSON attrs."""
        json_flights, df_flights = _json_and_df_flights(_golden_json())
        _assert_same_flights(json_flights, df_flights)

    @pytest.mark.parametrize("f1_engine", [["1IA001", "3CM026"], "1IA001"])
    def test_missing_scalars_are_dropped(self, f1_engine):
        """None, NaN, NaT and pd.NA cells stay missing; other scalars are kept.

        With a scalar ``f1_engine`` the fleet has no list cell, as on dev.
        """
        n = 2
        base = {
            "departure_airport": ["EGLL"] * n,
            "arrival_airport": ["LFPG"] * n,
            "aobt": ["2025-01-01 08:00:00"] * n,
            "latitude": [51.0, 52.0],
            "longitude": [0.0, 1.0],
            "altitude": [300.0, 350.0],
            "time": pd.date_range("2025-01-01 08:00", periods=n, freq="1min"),
        }
        f1 = pd.DataFrame(
            {
                **base,
                "flight_id": ["F1"] * n,
                "engine_uid": [f1_engine] * n,
                "q_fuel": [43.0e6] * n,
                "aircraft_type": ["A320"] * n,
                "none_col": [None] * n,
                "nat_col": [pd.NaT] * n,
                "na_col": pd.array([pd.NA] * n, dtype="Int64"),
                "zero": [0.0] * n,
                "blank": [""] * n,
            }
        )
        # F2 has no q_fuel and a scalar engine_uid: concat fills NaN
        f2 = pd.DataFrame(
            {
                **base,
                "flight_id": ["F2"] * n,
                "engine_uid": ["3CM026"] * n,
                "aircraft_type": ["A320"] * n,
                "zero": [0.0] * n,
                "blank": [""] * n,
            }
        )
        out = split_df_into_flights(pd.concat([f1, f2], ignore_index=True))
        assert [f.attrs["flight_id"] for f in out] == ["F1", "F2"]
        a1, a2 = out[0].attrs, out[1].attrs
        for key in ("none_col", "nat_col", "na_col"):
            assert key not in a1
            assert key not in a2
        assert "q_fuel" not in a2
        assert a1["q_fuel"] == 43.0e6
        assert a1["engine_uid"] == f1_engine
        assert a2["engine_uid"] == "3CM026"
        assert a1["zero"] == 0.0
        assert a1["blank"] == ""


# ---------------------------------------------------------------------------
# FleetRunner: JSON vs DataFrame
# ---------------------------------------------------------------------------


class TestFleetRunnerDataFrameMultiEngine:
    """Load, expand, parse and interpolate: no weather is read."""

    @staticmethod
    def _interpolated(
        tmp_path: Path,
        raw: list[dict],
        *,
        as_dataframe: bool,
        dataframe: pd.DataFrame | None = None,
    ):
        source = (
            {"trajectory_dataframe": dataframe}
            if dataframe is not None
            else _runner_params(tmp_path, raw, as_dataframe=as_dataframe)
        )
        cfg = FleetRunnerParams(
            zarr_paths=ZarrPaths("unused_met.zarr", "unused_rad.zarr", None),
            njobs=1,
            params={},
            **source,
        )
        runner = FleetRunner(cfg)
        runner._load_trajectories()
        runner._parse_flight()
        runner._interpolate()
        return runner

    def test_same_interpolated_fleet(self, tmp_path):
        raw = _golden_json(ENGINES)
        from_json = self._interpolated(tmp_path, raw, as_dataframe=False)
        from_df = self._interpolated(tmp_path, raw, as_dataframe=True)

        assert from_df.error_records == from_json.error_records
        assert from_json.interpolated_fleet is not None
        assert from_df.interpolated_fleet is not None
        # 5 flights, the first one expanded into one copy per engine
        assert len(from_json.interpolated_fleet) == 6
        assert len(from_df.interpolated_fleet) == len(from_json.interpolated_fleet)

        for fj, fd in zip(
            from_json.interpolated_fleet, from_df.interpolated_fleet, strict=True
        ):
            assert _same_value(dict(fd.attrs), dict(fj.attrs))
            dj, dd = fj.dataframe, fd.dataframe
            assert sorted(dd.columns) == sorted(dj.columns)
            pd.testing.assert_frame_equal(
                dd[list(dj.columns)].reset_index(drop=True),
                dj.reset_index(drop=True),
            )

        engines = [f.attrs["engine_uid"] for f in from_df.interpolated_fleet[:2]]
        assert engines == ENGINES

    def test_tuple_engine_uid_cell_same_as_json_list(self, tmp_path):
        """A tuple cell is expanded like the JSON list (it is not left as is)."""
        raw = _golden_json(ENGINES)
        df = concat_neats_flight(neats_json_to_flights(copy.deepcopy(raw)))
        first_fid = df["flight_id"].iloc[0]
        cells = np.empty(len(df), dtype=object)
        for i, (fid, value) in enumerate(zip(df["flight_id"], df["engine_uid"])):
            cells[i] = tuple(ENGINES) if fid == first_fid else value
        df["engine_uid"] = cells

        from_json = self._interpolated(tmp_path, raw, as_dataframe=False)
        from_df = self._interpolated(tmp_path, raw, as_dataframe=True, dataframe=df)
        assert from_df.error_records == from_json.error_records
        assert from_df.interpolated_fleet is not None
        assert from_json.interpolated_fleet is not None
        assert [f.attrs["flight_id"] for f in from_df.interpolated_fleet] == [
            f.attrs["flight_id"] for f in from_json.interpolated_fleet
        ]
        engines = [f.attrs["engine_uid"] for f in from_df.interpolated_fleet[:2]]
        assert engines == ENGINES

    def test_empty_engine_list_gives_error_record(self, tmp_path):
        """An empty engine list is an error record, not a silently lost flight."""
        raw = _golden_json([])
        fid = neats_json_to_flights(copy.deepcopy(raw))[0].attrs["flight_id"]
        from_json = self._interpolated(tmp_path, raw, as_dataframe=False)
        from_df = self._interpolated(tmp_path, raw, as_dataframe=True)

        assert from_df.error_records == from_json.error_records
        assert len(from_json.error_records) == 1
        record = from_json.error_records[0]
        assert record["flight_information"]["flight_id"] == fid
        assert record["flight_information"]["engine_uid"] == []
        assert record["error"].startswith("Failed at parsing: engine_uid is an empty")
        assert from_json.interpolated_fleet is not None
        assert len(from_json.interpolated_fleet) == 4
        assert len(from_df.interpolated_fleet or []) == 4

    @pytest.mark.parametrize("as_dataframe", [False, True])
    def test_only_empty_engine_list_aborts(self, tmp_path, as_dataframe):
        """No flight left after the expansion: the run stops with the error."""
        runner = self._interpolated(
            tmp_path, _golden_json([], n_flights=1), as_dataframe=as_dataframe
        )
        assert runner._pipeline_aborted
        assert len(runner.error_records) == 1
        assert runner.interpolated_fleet == []


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_fleet_runner_eval_json_vs_dataframe(
    tmp_path, weather, weather_path, bada_path
):
    """Full eval(): a multi-engine flight gives the same results for both inputs."""
    from pyneats.runners.large_emitter import FleetRunnerLargeEmitter

    if weather is None or weather_path is None:
        pytest.skip("Weather data not available")
    if bada_path is None or not bada_path.exists():
        pytest.skip("BADA data not available")

    wind_store = weather_path / "icon_wind.zarr"
    zarr_paths = ZarrPaths(
        weather_path / "icon_met.zarr",
        weather_path / "icon_rad.zarr",
        wind_store if wind_store.is_dir() else None,
    )
    raw = _golden_json(ENGINES, n_flights=1)

    results = []
    for as_dataframe in (False, True):
        cfg = FleetRunnerParams(
            zarr_paths=zarr_paths,
            bada_path=str(bada_path),
            params={},
            **_runner_params(tmp_path, raw, as_dataframe=as_dataframe),
        )
        runner = FleetRunnerLargeEmitter(cfg)
        runner.eval()
        assert runner.results is not None
        results.append(runner.results["flight_results"])

    from_json, from_df = results
    assert len(from_json) == 1
    assert from_json[0]["flight_information"]["engine_uid"] == ENGINES
    assert _same_value(from_df, from_json)
