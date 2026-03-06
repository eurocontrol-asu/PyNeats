"""Unit tests for multi-engine flight support (engine_uid as list).

Tests cover:
- _merge_engine_group: averages numeric columns, restores flight_id, sets engine_uid list
- _expand_multi_engine_sources: expands 1 df with list engine_uid → N copies
- _aggregate_multi_engine_flights: groups by parent key and merges
- NeatsTrajectoryParser guard: raises TrajectoryParserStepError for list engine_uid
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pycontrails import Flight

from pyneats.runners.fleet import _FLIGHT_KEY_ATTRS
from pyneats.runners.fleet import _MULTI_ENGINE_ORIG_FID_KEY
from pyneats.runners.fleet import _MULTI_ENGINE_PARENT_KEY
from pyneats.runners.fleet import FleetRunner
from pyneats.runners.fleet import _merge_engine_group
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.protocol import TrajectoryParserStepError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flight_with_emissions(
    flight_id: str,
    engine_uid: str,
    fuel_burn: float = 1000.0,
    nvpm_ei_m: float = 0.5,
    nox_ei: float = 0.01,
    **extra_attrs,
) -> FlightWithEmissions:
    """Create a minimal FlightWithEmissions for testing (no BADA/weather required)."""
    n = 5
    times = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
    data = pd.DataFrame(
        {
            "latitude": np.linspace(51.0, 52.0, n),
            "longitude": np.linspace(-0.5, 0.5, n),
            "altitude": np.linspace(1000.0, 12000.0, n),
            "time": times,
            "u_wind": np.zeros(n),
            "v_wind": np.zeros(n),
            "air_temperature": np.full(n, 220.0),
            "specific_humidity": np.full(n, 1e-4),
            "true_airspeed": np.full(n, 250.0),
            "fuel_flow": np.full(n, 0.5),
            "engine_efficiency": np.full(n, 0.35),
            "aircraft_mass": np.linspace(80000.0, 79000.0, n),
            "nvpm_ei_m": np.full(n, nvpm_ei_m),
            "nox_ei": np.full(n, nox_ei),
        }
    )
    attrs: dict = {
        "flight_id": flight_id,
        "aircraft_type": "B77W",
        "departure_airport": "EGLL",
        "arrival_airport": "KJFK",
        "model_type": "bada4",
        "aobt": "2025-01-01 08:00:00",
        "engine_uid": engine_uid,
        "fuel_burn": fuel_burn,
        "total_co2": fuel_burn * 3.16,
        **extra_attrs,
    }
    f = Flight(data=data, attrs=attrs)
    return FlightWithEmissions.from_flight(f)


def _make_source_df(
    flight_id: str = "FLT001",
    engine_uid=None,
    **extra_attrs,
) -> pd.DataFrame:
    """Create a minimal source DataFrame (pre-parse) for testing."""
    n = 5
    times = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "latitude": np.linspace(51.0, 52.0, n),
            "longitude": np.linspace(-0.5, 0.5, n),
            "altitude": np.linspace(100, 350, n),  # FL (feet/100)
            "time": times.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    df.attrs = {
        "flight_id": flight_id,
        "aircraft_type": "B77W",
        "departure_airport": "EGLL",
        "arrival_airport": "KJFK",
        "model_type": "bada4",
        "aobt": "2025-01-01 08:00:00",
        "engine_uid": engine_uid,
        **extra_attrs,
    }
    return df


# ---------------------------------------------------------------------------
# Tests for _merge_engine_group
# ---------------------------------------------------------------------------


class TestMergeEngineGroup:
    def _make_group(
        self, parent_key: str, original_fid: str, n_engines: int = 2
    ) -> list[FlightWithEmissions]:
        """Create a group of N engine copies ready for merging."""
        group = []
        for i in range(n_engines):
            fid = f"{original_fid}__eng{i}"
            eng_id = f"ENG_{chr(65 + i)}"  # ENG_A, ENG_B, ...
            fuel_burn = 1000.0 + i * 200.0  # 1000, 1200
            f = _make_flight_with_emissions(
                flight_id=fid,
                engine_uid=eng_id,
                fuel_burn=fuel_burn,
                nvpm_ei_m=0.4 + i * 0.2,  # 0.4, 0.6
                nox_ei=0.01 + i * 0.01,  # 0.01, 0.02
            )
            # Inject expansion attrs
            f.attrs[_MULTI_ENGINE_PARENT_KEY] = parent_key
            f.attrs[_MULTI_ENGINE_ORIG_FID_KEY] = original_fid
            group.append(f)
        return group

    def test_returns_single_flight_with_emissions(self):
        group = self._make_group("FLT001_EGLL_KJFK_2025", "FLT001")
        result = _merge_engine_group(group, "FLT001_EGLL_KJFK_2025")
        assert isinstance(result, FlightWithEmissions)

    def test_restores_original_flight_id(self):
        original_fid = "FLT001__special_case"
        group = self._make_group("pk", original_fid)
        result = _merge_engine_group(group, "pk")
        assert result.attrs["flight_id"] == original_fid

    def test_engine_uid_becomes_list(self):
        group = self._make_group("pk", "FLT001", n_engines=2)
        result = _merge_engine_group(group, "pk")
        assert isinstance(result.attrs["engine_uid"], list)
        assert result.attrs["engine_uid"] == ["ENG_A", "ENG_B"]

    def test_numeric_df_columns_are_averaged(self):
        group = self._make_group("pk", "FLT001", n_engines=2)
        # nvpm_ei_m: eng0=0.4, eng1=0.6 → mean=0.5
        result = _merge_engine_group(group, "pk")
        np.testing.assert_allclose(result["nvpm_ei_m"], 0.5, rtol=1e-6)

    def test_numeric_df_columns_nox_ei_averaged(self):
        group = self._make_group("pk", "FLT001", n_engines=2)
        # nox_ei: eng0=0.01, eng1=0.02 → mean=0.015
        result = _merge_engine_group(group, "pk")
        np.testing.assert_allclose(result["nox_ei"], 0.015, rtol=1e-6)

    def test_numeric_scalar_attrs_are_averaged(self):
        group = self._make_group("pk", "FLT001", n_engines=2)
        # fuel_burn: eng0=1000, eng1=1200 → mean=1100
        result = _merge_engine_group(group, "pk")
        assert result.attrs["fuel_burn"] == pytest.approx(1100.0)

    def test_internal_keys_removed_from_attrs(self):
        group = self._make_group("pk", "FLT001")
        result = _merge_engine_group(group, "pk")
        assert _MULTI_ENGINE_PARENT_KEY not in result.attrs
        assert _MULTI_ENGINE_ORIG_FID_KEY not in result.attrs

    def test_three_engines_averaged(self):
        group = self._make_group("pk", "FLT001", n_engines=3)
        # nvpm_ei_m: 0.4, 0.6, 0.8 → mean=0.6
        result = _merge_engine_group(group, "pk")
        np.testing.assert_allclose(result["nvpm_ei_m"], 0.6, rtol=1e-6)

    def test_single_engine_passthrough(self):
        """A group of 1 should still produce a valid merged flight."""
        group = self._make_group("pk", "FLT001", n_engines=1)
        result = _merge_engine_group(group, "pk")
        assert result.attrs["flight_id"] == "FLT001"
        np.testing.assert_allclose(result["nvpm_ei_m"], 0.4, rtol=1e-6)

    def test_flight_id_with_underscores_preserved(self):
        """flight_id containing underscores must survive (no string-split)."""
        original_fid = "ACA812__tc_mass_below_oew"
        group = self._make_group("pk", original_fid, n_engines=2)
        result = _merge_engine_group(group, "pk")
        assert result.attrs["flight_id"] == original_fid


# ---------------------------------------------------------------------------
# Tests for _expand_multi_engine_sources
# ---------------------------------------------------------------------------


class _MinimalRunner:
    """Minimal duck-type object to test FleetRunner instance methods in isolation."""

    def __init__(self, source_fleet=None, fleet_with_emissions=None):
        self.source_fleet = source_fleet
        self.fleet_with_emissions = fleet_with_emissions


class TestExpandMultiEngineSources:
    def test_scalar_engine_uid_unchanged(self):
        df = _make_source_df(flight_id="FLT001", engine_uid="ENG_A")
        runner = _MinimalRunner(source_fleet=[df])
        FleetRunner._expand_multi_engine_sources(runner)
        assert len(runner.source_fleet) == 1
        assert runner.source_fleet[0].attrs["engine_uid"] == "ENG_A"
        assert runner.source_fleet[0].attrs["flight_id"] == "FLT001"

    def test_list_engine_uid_expands_to_n_copies(self):
        df = _make_source_df(flight_id="FLT001", engine_uid=["ENG_A", "ENG_B"])
        runner = _MinimalRunner(source_fleet=[df])
        FleetRunner._expand_multi_engine_sources(runner)
        assert len(runner.source_fleet) == 2

    def test_expanded_copies_have_scalar_engine_uid(self):
        df = _make_source_df(flight_id="FLT001", engine_uid=["ENG_A", "ENG_B"])
        runner = _MinimalRunner(source_fleet=[df])
        FleetRunner._expand_multi_engine_sources(runner)
        for copy_df in runner.source_fleet:
            assert isinstance(copy_df.attrs["engine_uid"], str)

    def test_expanded_copies_have_distinct_flight_ids(self):
        df = _make_source_df(flight_id="FLT001", engine_uid=["ENG_A", "ENG_B"])
        runner = _MinimalRunner(source_fleet=[df])
        FleetRunner._expand_multi_engine_sources(runner)
        fids = [d.attrs["flight_id"] for d in runner.source_fleet]
        assert fids[0] == "FLT001__eng0"
        assert fids[1] == "FLT001__eng1"

    def test_expanded_copies_have_parent_key(self):
        df = _make_source_df(flight_id="FLT001", engine_uid=["ENG_A", "ENG_B"])
        runner = _MinimalRunner(source_fleet=[df])
        FleetRunner._expand_multi_engine_sources(runner)
        expected_parent = "_".join(str(df.attrs.get(k, "")) for k in _FLIGHT_KEY_ATTRS)
        for copy_df in runner.source_fleet:
            assert copy_df.attrs[_MULTI_ENGINE_PARENT_KEY] == expected_parent

    def test_expanded_copies_store_original_fid(self):
        df = _make_source_df(flight_id="FLT001__special", engine_uid=["ENG_A", "ENG_B"])
        runner = _MinimalRunner(source_fleet=[df])
        FleetRunner._expand_multi_engine_sources(runner)
        for copy_df in runner.source_fleet:
            assert copy_df.attrs[_MULTI_ENGINE_ORIG_FID_KEY] == "FLT001__special"

    def test_mixed_fleet_preserves_order(self):
        df_scalar = _make_source_df(flight_id="FLT_SCALAR", engine_uid="ENG_X")
        df_list = _make_source_df(flight_id="FLT_LIST", engine_uid=["ENG_A", "ENG_B"])
        runner = _MinimalRunner(source_fleet=[df_scalar, df_list])
        FleetRunner._expand_multi_engine_sources(runner)
        assert len(runner.source_fleet) == 3
        assert runner.source_fleet[0].attrs["flight_id"] == "FLT_SCALAR"

    def test_none_source_fleet_is_noop(self):
        runner = _MinimalRunner(source_fleet=None)
        FleetRunner._expand_multi_engine_sources(runner)  # Should not raise
        assert runner.source_fleet is None


# ---------------------------------------------------------------------------
# Tests for _aggregate_multi_engine_flights
# ---------------------------------------------------------------------------


class TestAggregateMultiEngineFlights:
    def _make_group_pair(
        self, parent_key: str, original_fid: str
    ) -> list[FlightWithEmissions]:
        """Create 2 engine copies with multi-engine attrs injected."""
        group = []
        for i in range(2):
            fid = f"{original_fid}__eng{i}"
            f = _make_flight_with_emissions(
                flight_id=fid,
                engine_uid=f"ENG_{chr(65 + i)}",
                fuel_burn=1000.0 + i * 200.0,
            )
            f.attrs[_MULTI_ENGINE_PARENT_KEY] = parent_key
            f.attrs[_MULTI_ENGINE_ORIG_FID_KEY] = original_fid
            group.append(f)
        return group

    def test_multi_engine_flights_collapsed_to_one(self):
        group = self._make_group_pair("FLT001_EGLL_KJFK_2025", "FLT001")
        regular = _make_flight_with_emissions("FLT_REG", "ENG_R")
        runner = _MinimalRunner(fleet_with_emissions=[regular] + group)
        FleetRunner._aggregate_multi_engine_flights(runner)
        assert len(runner.fleet_with_emissions) == 2  # 1 regular + 1 merged

    def test_regular_flights_unchanged(self):
        regular = _make_flight_with_emissions("FLT_REG", "ENG_R")
        group = self._make_group_pair("pk", "FLT_MULTI")
        runner = _MinimalRunner(fleet_with_emissions=[regular] + group)
        FleetRunner._aggregate_multi_engine_flights(runner)
        result_ids = [f.attrs["flight_id"] for f in runner.fleet_with_emissions]
        assert "FLT_REG" in result_ids

    def test_merged_flight_has_original_flight_id(self):
        group = self._make_group_pair("pk", "FLT_MULTI")
        runner = _MinimalRunner(fleet_with_emissions=group)
        FleetRunner._aggregate_multi_engine_flights(runner)
        assert len(runner.fleet_with_emissions) == 1
        assert runner.fleet_with_emissions[0].attrs["flight_id"] == "FLT_MULTI"

    def test_empty_fleet_is_noop(self):
        runner = _MinimalRunner(fleet_with_emissions=[])
        FleetRunner._aggregate_multi_engine_flights(runner)
        assert runner.fleet_with_emissions == []

    def test_none_fleet_is_noop(self):
        runner = _MinimalRunner(fleet_with_emissions=None)
        FleetRunner._aggregate_multi_engine_flights(runner)  # Should not raise
        assert runner.fleet_with_emissions is None


# ---------------------------------------------------------------------------
# Tests for NeatsTrajectoryParser guard
# ---------------------------------------------------------------------------


class TestParserGuardOnListEngineUid:
    def _make_parser_input(self, engine_uid) -> pd.DataFrame:
        """Create minimal parser-ready DataFrame with engine_uid in attrs."""
        n = 5
        times = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
        df = pd.DataFrame(
            {
                "latitude": np.linspace(51.0, 52.0, n),
                "longitude": np.linspace(-0.5, 0.5, n),
                "altitude": np.linspace(100, 350, n),  # FL
                "time": times.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        df.attrs = {
            "flight_id": "FLT001",
            "aircraft_type": "B77W",
            "departure_airport": "EGLL",
            "arrival_airport": "KJFK",
            "model_type": "bada4",
            "aobt": "2025-01-01 08:00:00",
            "engine_uid": engine_uid,
        }
        return df

    def test_list_engine_uid_raises_step_error(self):
        parser = NeatsTrajectoryParser()
        df = self._make_parser_input(engine_uid=["ENG_A", "ENG_B"])
        with pytest.raises(TrajectoryParserStepError, match="FleetRunner"):
            parser(df)

    def test_scalar_engine_uid_does_not_raise(self):
        parser = NeatsTrajectoryParser()
        df = self._make_parser_input(engine_uid="ENG_A")
        # Should not raise (may raise for other validation reasons, but not the guard)
        try:
            parser(df)
        except TrajectoryParserStepError as exc:
            assert "FleetRunner" not in str(exc), (
                f"Unexpected FleetRunner guard error: {exc}"
            )

    def test_error_message_mentions_fleet_runner(self):
        parser = NeatsTrajectoryParser()
        df = self._make_parser_input(engine_uid=["ENG_A", "ENG_B", "ENG_C"])
        with pytest.raises(TrajectoryParserStepError) as exc_info:
            parser(df)
        assert "FleetRunner" in str(exc_info.value)
