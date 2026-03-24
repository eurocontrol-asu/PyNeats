"""Tests for the speed filter — removes trajectory points below VStall threshold.

The speed filter uses the BADA adapter's v_stall_cas() to determine the
minimum acceptable TAS.  Points below that threshold are filtered out,
analogous to how altitude_filter removes low-altitude points.
"""

from __future__ import annotations

import pytest


# performance/__init__.py eagerly imports bada_adapters which requires pyBADA
pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from unittest.mock import MagicMock

import pandas as pd
from pycontrails import Flight

from pyneats.steps.performance.protocol import PerformanceStepError
from pyneats.steps.performance.speed_filter import filter_low_speed_points
from pyneats.steps.weather.weather_provider import FlightWithWeather


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flight_with_tas(
    tas_values: list[float],
    *,
    flight_id: str = "FL001",
) -> FlightWithWeather:
    """Build a FlightWithWeather with given TAS values (m/s)."""
    n = len(tas_values)
    times = pd.date_range("2023-01-01 10:00", periods=n, freq="1min", tz="UTC")
    data = {
        "latitude": [51.5 + i * 0.1 for i in range(n)],
        "longitude": [-0.1 + i * 0.1 for i in range(n)],
        "altitude": [10000.0] * n,
        "time": times,
        "true_airspeed": tas_values,
        "air_temperature": [220.0] * n,
        "specific_humidity": [0.001] * n,
        "u_wind": [10.0] * n,
        "v_wind": [5.0] * n,
    }
    df = pd.DataFrame(data)
    flight = Flight(
        data=df,
        attrs={
            "flight_id": flight_id,
            "aircraft_type": "A320",
            "departure_airport": "EGLL",
            "arrival_airport": "LFPG",
            "model_type": "BADA4",
            "aobt": "2023-01-01 10:00:00",
        },
    )
    return FlightWithWeather.from_flight(flight)


def _make_adapter(
    *,
    v_stall: float | None = 60.0,
    mtow: float | None = 78000.0,
) -> MagicMock:
    """Build a mock BaseBADAAdapter with configurable v_stall and MTOW."""
    adapter = MagicMock()
    adapter.v_stall_cas.return_value = v_stall
    adapter.MTOW = mtow
    return adapter


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestFilterLowSpeedPoints:
    """Unit tests for filter_low_speed_points."""

    def test_filters_low_speed_points(self) -> None:
        """Points with TAS < VStall are removed."""
        flight = _make_flight_with_tas([10, 20, 200, 250])
        adapter = _make_adapter(v_stall=60)
        filtered = filter_low_speed_points(flight, adapter)
        assert len(filtered.dataframe) == 2

    def test_keeps_points_above_vstall(self) -> None:
        """All points above VStall are kept; raises because nothing to filter."""
        flight = _make_flight_with_tas([100, 200, 300])
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError, match="No") as exc_info:
            filter_low_speed_points(flight, adapter)
        assert exc_info.value.retryable is False

    def test_no_slow_points_raises(self) -> None:
        """When all TAS > VStall, raise PerformanceStepError."""
        flight = _make_flight_with_tas([100, 200, 300])
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError, match="No"):
            filter_low_speed_points(flight, adapter)

    def test_too_many_filtered_raises(self) -> None:
        """When >ratio of points are below VStall, raise non-retryable."""
        # 9 below + 1 above, ratio=0.3 → 90% filtered > 30% threshold
        tas_values = [10.0] * 9 + [200.0]
        flight = _make_flight_with_tas(tas_values)
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError) as exc_info:
            filter_low_speed_points(flight, adapter, max_filter_ratio=0.3)
        assert exc_info.value.retryable is False

    def test_preserves_attrs(self) -> None:
        """Flight attributes are preserved after filtering."""
        flight = _make_flight_with_tas([10, 20, 200, 250], flight_id="TEST42")
        adapter = _make_adapter(v_stall=60)
        filtered = filter_low_speed_points(flight, adapter)
        assert filtered.attrs["flight_id"] == "TEST42"

    def test_vstall_none_skips_filter(self) -> None:
        """When adapter returns v_stall_cas() → None, return original unchanged."""
        flight = _make_flight_with_tas([10, 20, 200, 250])
        adapter = _make_adapter(v_stall=None)
        result = filter_low_speed_points(flight, adapter)
        assert len(result.dataframe) == len(flight.dataframe)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestFilterLowSpeedEdgeCases:
    """Edge-case tests for filter_low_speed_points."""

    def test_adapter_no_mtow_skips_filter(self) -> None:
        """When adapter.MTOW is None, log warning and skip filter."""
        flight = _make_flight_with_tas([10, 20, 200, 250])
        adapter = _make_adapter(mtow=None)
        result = filter_low_speed_points(flight, adapter)
        assert len(result.dataframe) == len(flight.dataframe)

    def test_all_points_below_vstall_raises(self) -> None:
        """When every TAS < VStall, ratio=1.0 exceeds threshold → non-retryable."""
        flight = _make_flight_with_tas([10, 20, 30, 40])
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError) as exc_info:
            filter_low_speed_points(flight, adapter)
        assert exc_info.value.retryable is False

    def test_tas_column_missing_raises(self) -> None:
        """When true_airspeed column is absent, raise clearly."""
        n = 4
        times = pd.date_range("2023-01-01 10:00", periods=n, freq="1min", tz="UTC")
        data = {
            "latitude": [51.5 + i * 0.1 for i in range(n)],
            "longitude": [-0.1 + i * 0.1 for i in range(n)],
            "altitude": [10000.0] * n,
            "time": times,
            # no true_airspeed column
            "air_temperature": [220.0] * n,
            "specific_humidity": [0.001] * n,
            "u_wind": [10.0] * n,
            "v_wind": [5.0] * n,
        }
        df = pd.DataFrame(data)
        flight_obj = Flight(
            data=df,
            attrs={
                "flight_id": "FL001",
                "aircraft_type": "A320",
                "departure_airport": "EGLL",
                "arrival_airport": "LFPG",
                "model_type": "BADA4",
                "aobt": "2023-01-01 10:00:00",
            },
        )
        flight = FlightWithWeather.from_flight(flight_obj)
        adapter = _make_adapter(v_stall=60)
        with pytest.raises((KeyError, PerformanceStepError)):
            filter_low_speed_points(flight, adapter)
