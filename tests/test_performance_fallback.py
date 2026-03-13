"""Tests for the performance step altitude fallback mechanism.

The altitude fallback is triggered when the BADA performance model
fails on a flight — low-altitude points (< FL15) are filtered out and
the performance step is retried with both BADA4 and BADA3.
"""

from __future__ import annotations

import pytest

# performance/__init__.py eagerly imports bada_adapters which requires pyBADA
pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from unittest.mock import MagicMock

import pandas as pd
from pycontrails import Flight
from pycontrails.physics.units import ft_to_m

from pyneats.core.neats_default_parameters import DEFAULT_MIN_ALTITUDE_FL
from pyneats.steps.performance.altitude_filter import filter_low_altitude_points
from pyneats.steps.performance.bada_model import BADAPerformanceModel
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
            "model_type": "BADA4",
            "aobt": "2023-01-01 10:00:00",
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
        assert len(filtered.dataframe) == 3

    def test_keeps_points_at_threshold(self) -> None:
        """Points exactly at FL15 are kept (inclusive)."""
        flight = _make_flight_with_weather([5, 15, 100, 350])
        filtered = filter_low_altitude_points(flight)
        assert len(filtered.dataframe) == 3

    def test_no_low_points_raises(self) -> None:
        """When no points are below threshold, raise non-retryable."""
        flight = _make_flight_with_weather([100, 200, 350])
        with pytest.raises(PerformanceStepError, match="No low-altitude") as exc_info:
            filter_low_altitude_points(flight)
        assert exc_info.value.retryable is False

    def test_too_many_filtered_raises(self) -> None:
        """When >80% of points are below threshold, raise non-retryable."""
        altitudes = [5] * 9 + [350]
        flight = _make_flight_with_weather(altitudes)
        with pytest.raises(PerformanceStepError, match="Too many") as exc_info:
            filter_low_altitude_points(flight)
        assert exc_info.value.retryable is False

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


# ---------------------------------------------------------------------------
# Tests for _run_with_altitude_fallback (BADA4 → BADA3 chain)
# ---------------------------------------------------------------------------


class TestRunWithAltitudeFallback:
    """Tests for the BADA4→BADA3 retry chain inside _run_with_altitude_fallback."""

    def _make_model(self) -> BADAPerformanceModel:
        """Create a BADAPerformanceModel with mocked internals."""
        model = MagicMock(spec=BADAPerformanceModel)
        model.logger = MagicMock()
        # Bind the real method to the mock instance
        model._run_with_altitude_fallback = (
            BADAPerformanceModel._run_with_altitude_fallback.__get__(model)
        )
        model._preprocess = MagicMock(return_value=pd.DataFrame())
        return model

    def test_bada4_succeeds_on_filtered_data(self) -> None:
        """If BADA4 works on filtered data, BADA3 is not attempted."""
        model = self._make_model()
        expected = MagicMock(name="result")
        model.run_by_bada_version = MagicMock(return_value=expected)

        flight = _make_flight_with_weather([5, 10, 100, 200, 350])
        result = model._run_with_altitude_fallback(
            flight, "A320", None, None, None,
            PerformanceStepError("original"),
        )

        assert result is expected
        # run_by_bada_version called once (BADA4 succeeded)
        model.run_by_bada_version.assert_called_once()
        call_kwargs = model.run_by_bada_version.call_args
        assert not call_kwargs.kwargs.get("force_bada3", False)

    def test_bada4_fails_bada3_succeeds_on_filtered(self) -> None:
        """If BADA4 fails on filtered data, BADA3 is tried and succeeds."""
        model = self._make_model()
        expected = MagicMock(name="result")
        model.run_by_bada_version = MagicMock(
            side_effect=[PerformanceStepError("BADA4 NaN"), expected],
        )

        flight = _make_flight_with_weather([5, 10, 100, 200, 350])
        result = model._run_with_altitude_fallback(
            flight, "A320", None, None, None,
            PerformanceStepError("original"),
        )

        assert result is expected
        assert model.run_by_bada_version.call_count == 2
        second_call = model.run_by_bada_version.call_args_list[1]
        assert second_call.kwargs.get("force_bada3") is True

    def test_both_bada_fail_on_filtered_raises(self) -> None:
        """If both BADA4 and BADA3 fail on filtered data, raise with context."""
        model = self._make_model()
        model.run_by_bada_version = MagicMock(
            side_effect=[
                PerformanceStepError("BADA4 NaN"),
                PerformanceStepError("BADA3 NaN"),
            ],
        )

        flight = _make_flight_with_weather([5, 10, 100, 200, 350])
        with pytest.raises(PerformanceStepError, match="altitude fallback"):
            model._run_with_altitude_fallback(
                flight, "A320", None, None, None,
                PerformanceStepError("original"),
            )

        assert model.run_by_bada_version.call_count == 2

    def test_no_low_points_propagates_original_error(self) -> None:
        """If flight has no low-altitude points, the original error is re-raised."""
        model = self._make_model()
        flight = _make_flight_with_weather([100, 200, 350])
        original = PerformanceStepError("the original error")

        with pytest.raises(PerformanceStepError, match="the original error"):
            model._run_with_altitude_fallback(
                flight, "A320", None, None, None, original,
            )

        # run_by_bada_version never called — filter itself failed
        model.run_by_bada_version.assert_not_called()

    def test_preprocess_failure_on_filtered_raises(self) -> None:
        """If _preprocess fails on filtered data, raise with altitude fallback context."""
        model = self._make_model()
        model._preprocess = MagicMock(
            side_effect=PerformanceStepError("preprocess fail"),
        )

        flight = _make_flight_with_weather([5, 10, 100, 200, 350])
        with pytest.raises(PerformanceStepError, match="altitude fallback"):
            model._run_with_altitude_fallback(
                flight, "A320", None, None, None,
                PerformanceStepError("original"),
            )
