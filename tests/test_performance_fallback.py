"""Tests for the performance step altitude fallback mechanism.

The altitude fallback is triggered when the BADA performance model
fails on a flight — low-altitude points (< FL15) are filtered out and
the performance step is retried.
"""

from __future__ import annotations

import pytest

# performance/__init__.py eagerly imports bada_adapters which requires pyBADA
pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

import pandas as pd
from pycontrails import Flight
from pycontrails.physics.units import ft_to_m

from pyneats.core.neats_default_parameters import DEFAULT_MIN_ALTITUDE_FL
from pyneats.steps.performance.altitude_filter import filter_low_altitude_points
from pyneats.steps.performance.protocol import PerformanceStepError
from pyneats.steps.weather.weather_provider import FlightWithWeather


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flight_with_weather(
    altitudes_fl: list[float],
) -> FlightWithWeather:
    """Build a FlightWithWeather with altitudes already in metres (post-parser)."""
    n = len(altitudes_fl)
    altitudes_m = [ft_to_m(fl * 100) for fl in altitudes_fl]
    times = pd.date_range("2023-01-01 10:00", periods=n, freq="1min", tz="UTC")
    data = {
        "latitude": [51.5 + i * 0.1 for i in range(n)],
        "longitude": [-0.1 + i * 0.1 for i in range(n)],
        "altitude": altitudes_m,
        "time": times,
        "air_temperature": [220.0] * n,
        "specific_humidity": [0.001] * n,
        "u_wind": [10.0] * n,
        "v_wind": [5.0] * n,
    }
    df = pd.DataFrame(data)
    flight = Flight(
        data=df,
        attrs={
            "flight_id": "FL001",
            "aircraft_type": "A320",
            "departure_airport": "EGLL",
            "arrival_airport": "LFPG",
        },
    )
    return FlightWithWeather.from_flight(flight)


# ---------------------------------------------------------------------------
# Tests for filter_low_altitude_points
# ---------------------------------------------------------------------------


class TestFilterLowAltitudePoints:
    """Unit tests for the filter_low_altitude_points helper."""

    def test_filters_low_altitude_points(self) -> None:
        """Points below FL15 are removed."""
        flight = _make_flight_with_weather([5, 10, 100, 200, 350])
        filtered = filter_low_altitude_points(flight)
        # FL5 and FL10 should be filtered (below FL15)
        assert len(filtered.dataframe) == 3

    def test_keeps_points_at_threshold(self) -> None:
        """Points exactly at FL15 are kept (inclusive)."""
        flight = _make_flight_with_weather([15, 100, 350])
        filtered = filter_low_altitude_points(flight)
        assert len(filtered.dataframe) == 3

    def test_no_low_points_raises(self) -> None:
        """When no points are below threshold, raise (nothing to filter)."""
        flight = _make_flight_with_weather([100, 200, 350])
        with pytest.raises(PerformanceStepError, match="No low-altitude"):
            filter_low_altitude_points(flight)

    def test_too_many_filtered_raises(self) -> None:
        """When >80% of points are below threshold, raise."""
        altitudes = [5] * 9 + [350]
        flight = _make_flight_with_weather(altitudes)
        with pytest.raises(PerformanceStepError, match="Too many"):
            filter_low_altitude_points(flight)

    def test_custom_threshold(self) -> None:
        """Custom min_altitude_fl and max_filter_ratio work."""
        flight = _make_flight_with_weather([50, 100, 200, 350])
        filtered = filter_low_altitude_points(
            flight, min_altitude_fl=100, max_filter_ratio=0.5
        )
        assert len(filtered.dataframe) == 3

    def test_returns_flight_with_weather(self) -> None:
        """Returned object is a proper FlightWithWeather."""
        flight = _make_flight_with_weather([5, 10, 100, 350])
        filtered = filter_low_altitude_points(flight)
        assert isinstance(filtered, FlightWithWeather)
        assert "air_temperature" in filtered.dataframe.columns

    def test_preserves_attrs(self) -> None:
        """Flight attributes are preserved after filtering."""
        flight = _make_flight_with_weather([5, 100, 350])
        filtered = filter_low_altitude_points(flight)
        assert filtered.attrs["flight_id"] == "FL001"
        assert filtered.attrs["aircraft_type"] == "A320"

    def test_non_retryable_errors(self) -> None:
        """Errors from filter_low_altitude_points have retryable=False."""
        flight = _make_flight_with_weather([100, 200, 350])
        with pytest.raises(PerformanceStepError) as exc_info:
            filter_low_altitude_points(flight)
        assert exc_info.value.retryable is False


# ---------------------------------------------------------------------------
# Tests for PerformanceStepError.retryable
# ---------------------------------------------------------------------------


class TestPerformanceStepErrorRetryable:
    """Tests for the retryable attribute on PerformanceStepError."""

    def test_default_retryable_true(self) -> None:
        """PerformanceStepError defaults to retryable=True."""
        err = PerformanceStepError("test error")
        assert err.retryable is True

    def test_explicit_retryable_false(self) -> None:
        """PerformanceStepError supports retryable=False."""
        err = PerformanceStepError("structural error", retryable=False)
        assert err.retryable is False

    def test_message_preserved(self) -> None:
        """Error message is accessible."""
        err = PerformanceStepError("custom message", retryable=False)
        assert "custom message" in str(err)
