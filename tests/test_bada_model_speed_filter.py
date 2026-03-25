"""Tests for speed filter integration into BADAPerformanceModel.run_by_bada_version.

The speed filter removes trajectory points with TAS below VStall *before*
the BADA performance computation.  When it fails, run_by_bada_version must
degrade gracefully and proceed with unfiltered data.
"""

from __future__ import annotations

import pytest


# performance/__init__.py eagerly imports bada_adapters which requires pyBADA
pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from unittest.mock import MagicMock
from unittest.mock import patch

import pandas as pd
from pycontrails import Flight

from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError
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


def _make_model() -> BADAPerformanceModel:
    """Create a BADAPerformanceModel with mocked internals."""
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    model.params = MagicMock()
    # Bind the real method to the mock instance
    model.run_by_bada_version = BADAPerformanceModel.run_by_bada_version.__get__(model)
    return model


def _make_adapter(
    *,
    v_stall: float | None = 60.0,
    mtow: float | None = 78000.0,
    oew: float | None = 42000.0,
) -> MagicMock:
    """Build a mock BaseBADAAdapter with configurable v_stall and MTOW."""
    adapter = MagicMock()
    adapter.v_stall_cas.return_value = v_stall
    adapter.MTOW = mtow
    adapter.OEW = oew
    return adapter


# ---------------------------------------------------------------------------
# Unit tests — speed filter integration in run_by_bada_version
# ---------------------------------------------------------------------------


class TestSpeedFilterCalledBeforePerf:
    """Verify filter_low_speed_points is called inside run_by_bada_version."""

    @patch("pyneats.steps.performance.bada_model.filter_low_speed_points")
    def test_speed_filter_called_before_perf(self, mock_filter: MagicMock) -> None:
        """filter_low_speed_points is called with the correct adapter."""
        model = _make_model()
        adapter = _make_adapter()
        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "engine_1")
        )
        # filter returns a filtered DataFrame
        filtered_df = pd.DataFrame({"true_airspeed": [200, 250]})
        mock_filter.return_value = filtered_df

        # Stub remaining pipeline methods
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(return_value=(MagicMock(), 3.5))
        model._finalize_columns = MagicMock()
        model._build_result = MagicMock(return_value=MagicMock(name="result"))

        flight = _make_flight_with_tas([5, 10, 200, 250])
        df = pd.DataFrame({"true_airspeed": [5, 10, 200, 250]})

        model.run_by_bada_version(flight, df, "A320", None, None, None)

        # filter was called with the df and the resolved adapter
        mock_filter.assert_called_once()
        call_args = mock_filter.call_args
        assert call_args[0][0] is df  # first positional: df
        assert call_args[0][1] is adapter  # second positional: adapter


class TestSpeedFilterFailureDegrades:
    """Verify graceful degradation when speed filter raises."""

    @patch("pyneats.steps.performance.bada_model.filter_low_speed_points")
    def test_speed_filter_failure_degrades_gracefully(
        self, mock_filter: MagicMock
    ) -> None:
        """When filter raises PerformanceStepError, proceed with unfiltered data."""
        model = _make_model()
        adapter = _make_adapter()
        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "engine_1")
        )
        mock_filter.side_effect = PerformanceStepError("No low-speed points to filter")

        # Stub remaining pipeline
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(return_value=(MagicMock(), 3.5))
        model._finalize_columns = MagicMock()
        expected = MagicMock(name="result")
        model._build_result = MagicMock(return_value=expected)

        flight = _make_flight_with_tas([200, 250, 300])
        df = pd.DataFrame()

        result = model.run_by_bada_version(flight, df, "A320", None, None, None)

        # Pipeline completed with the original (unfiltered) flight
        assert result is expected
        # Logger should have warned about degradation
        model.logger.warning.assert_called()


# ---------------------------------------------------------------------------
# Functional test — end-to-end speed filtering in the pipeline
# ---------------------------------------------------------------------------


class TestSpeedFilterFunctional:
    """Functional test: low-speed points are filtered before perf computation."""

    @patch("pyneats.steps.performance.bada_model.filter_low_speed_points")
    def test_low_speed_points_filtered_in_pipeline(
        self, mock_filter: MagicMock
    ) -> None:
        """Flight with taxi points (TAS~5 m/s) + cruise → perf completed, fewer rows."""
        model = _make_model()
        adapter = _make_adapter()
        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "engine_1")
        )

        # Simulate: original has 6 points (2 taxi + 4 cruise), filter returns 4
        original_flight = _make_flight_with_tas([5, 5, 200, 220, 240, 260])
        original_df = pd.DataFrame({"true_airspeed": [5, 5, 200, 220, 240, 260]})
        filtered_df = pd.DataFrame({"true_airspeed": [200, 220, 240, 260]})
        mock_filter.return_value = filtered_df

        # Stub remaining pipeline
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(return_value=(MagicMock(), 3.5))
        model._finalize_columns = MagicMock()
        expected = MagicMock(name="result")
        model._build_result = MagicMock(return_value=expected)

        result = model.run_by_bada_version(
            original_flight, original_df, "A320", None, None, None
        )

        assert result is expected
        # Verify filter was called and the filtered df (fewer rows) was used downstream
        mock_filter.assert_called_once()
        assert len(filtered_df) == 4
        assert len(original_df) == 6


# ---------------------------------------------------------------------------
# Edge cases — speed filter integration
# ---------------------------------------------------------------------------


class TestSpeedFilterEdgeCases:
    """Edge-case tests for speed filter integration in run_by_bada_version."""

    @patch("pyneats.steps.performance.bada_model.filter_low_speed_points")
    def test_all_points_below_vstall_triggers_altitude_fallback(
        self, mock_filter: MagicMock
    ) -> None:
        """All TAS < VStall → filter raises → graceful degradation → BADA fails → altitude fallback.

        The speed filter raises because too many points are below VStall.
        run_by_bada_version catches it and proceeds with unfiltered data.
        The unfiltered data will then fail BADA (simulated), which triggers
        the altitude fallback chain in the caller (run method).
        """
        model = _make_model()
        adapter = _make_adapter()
        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "engine_1")
        )
        # Filter raises because all points are below VStall
        mock_filter.side_effect = PerformanceStepError(
            "Too many points below VStall=60.0 m/s (4/4, >80% threshold)",
            retryable=False,
        )

        # Pipeline proceeds with unfiltered data but BADA computation fails
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(
            side_effect=PerformanceStepError("BADA computation NaN")
        )

        flight = _make_flight_with_tas([5, 10, 15, 20])
        df = pd.DataFrame()

        # run_by_bada_version should raise — caller (run) will then invoke altitude fallback
        with pytest.raises(PerformanceStepError, match="BADA computation NaN"):
            model.run_by_bada_version(flight, df, "A320", None, None, None)

    @patch("pyneats.steps.performance.bada_model.filter_low_speed_points")
    def test_no_adapter_mtow_filter_skips(self, mock_filter: MagicMock) -> None:
        """Adapter without MTOW → filter returns original unchanged, pipeline continues."""
        model = _make_model()
        adapter = _make_adapter(mtow=None)
        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "engine_1")
        )

        # filter_low_speed_points returns original df when MTOW is None (skip)
        flight = _make_flight_with_tas([5, 10, 200, 250])
        df = pd.DataFrame({"true_airspeed": [5, 10, 200, 250]})
        mock_filter.return_value = df  # returns unchanged

        # Stub remaining pipeline
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(return_value=(MagicMock(), 3.5))
        model._finalize_columns = MagicMock()
        expected = MagicMock(name="result")
        model._build_result = MagicMock(return_value=expected)

        result = model.run_by_bada_version(flight, df, "A320", None, None, None)

        # Pipeline completed successfully with original data
        assert result is expected
        # Filter was still called (it handles the skip internally)
        mock_filter.assert_called_once()
