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

from pyneats.steps.performance.protocol import PerformanceStepError
from pyneats.steps.performance.speed_filter import filter_low_speed_points


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(
    tas_values: list[float],
) -> pd.DataFrame:
    """Build a DataFrame with given TAS values (m/s)."""
    n = len(tas_values)
    times = pd.date_range("2023-01-01 10:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
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
    )


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
        df = _make_df([10, 20, 200, 250])
        adapter = _make_adapter(v_stall=60)
        filtered = filter_low_speed_points(df, adapter)
        assert len(filtered) == 2

    def test_keeps_points_above_vstall(self) -> None:
        """All points above VStall are kept; raises because nothing to filter."""
        df = _make_df([100, 200, 300])
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError, match="No") as exc_info:
            filter_low_speed_points(df, adapter)
        assert exc_info.value.retryable is False

    def test_no_slow_points_raises(self) -> None:
        """When all TAS > VStall, raise PerformanceStepError."""
        df = _make_df([100, 200, 300])
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError, match="No"):
            filter_low_speed_points(df, adapter)

    def test_too_many_filtered_raises(self) -> None:
        """When >ratio of points are below VStall, raise non-retryable."""
        # 9 below + 1 above, ratio=0.3 → 90% filtered > 30% threshold
        tas_values = [10.0] * 9 + [200.0]
        df = _make_df(tas_values)
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError) as exc_info:
            filter_low_speed_points(df, adapter, max_filter_ratio=0.3)
        assert exc_info.value.retryable is False

    def test_returns_dataframe(self) -> None:
        """Filtered result is a DataFrame with reset index."""
        df = _make_df([10, 20, 200, 250])
        adapter = _make_adapter(v_stall=60)
        filtered = filter_low_speed_points(df, adapter)
        assert isinstance(filtered, pd.DataFrame)
        assert list(filtered.index) == [0, 1]

    def test_vstall_none_skips_filter(self) -> None:
        """When adapter returns v_stall_cas() → None, return original unchanged."""
        df = _make_df([10, 20, 200, 250])
        adapter = _make_adapter(v_stall=None)
        result = filter_low_speed_points(df, adapter)
        assert len(result) == len(df)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestFilterLowSpeedEdgeCases:
    """Edge-case tests for filter_low_speed_points."""

    def test_adapter_no_mtow_skips_filter(self) -> None:
        """When adapter.MTOW is None, log warning and skip filter."""
        df = _make_df([10, 20, 200, 250])
        adapter = _make_adapter(mtow=None)
        result = filter_low_speed_points(df, adapter)
        assert len(result) == len(df)

    def test_all_points_below_vstall_raises(self) -> None:
        """When every TAS < VStall, ratio=1.0 exceeds threshold → non-retryable."""
        df = _make_df([10, 20, 30, 40])
        adapter = _make_adapter(v_stall=60)
        with pytest.raises(PerformanceStepError) as exc_info:
            filter_low_speed_points(df, adapter)
        assert exc_info.value.retryable is False

    def test_tas_column_missing_raises(self) -> None:
        """When true_airspeed column is absent, raise clearly."""
        n = 4
        times = pd.date_range("2023-01-01 10:00", periods=n, freq="1min", tz="UTC")
        df = pd.DataFrame(
            {
                "latitude": [51.5 + i * 0.1 for i in range(n)],
                "longitude": [-0.1 + i * 0.1 for i in range(n)],
                "altitude": [10000.0] * n,
                "time": times,
                # no true_airspeed column
            }
        )
        adapter = _make_adapter(v_stall=60)
        with pytest.raises((KeyError, PerformanceStepError)):
            filter_low_speed_points(df, adapter)
