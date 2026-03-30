"""Tests for zero-value climate results for low-altitude flights (AXM-907).

Tests that _build_zero_climate_result produces correct structure, values,
and markers, and that _extract_results properly separates low-altitude
errors from other errors.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


def _import_symbols():
    """Import implementation symbols — will fail until implementation exists."""
    from pyneats.core.physics import METRICS_HORIZONS
    from pyneats.runners.fleet import _LOW_ALTITUDE_ERROR_MARKER
    from pyneats.runners.fleet import _build_zero_climate_result

    return METRICS_HORIZONS, _build_zero_climate_result, _LOW_ALTITUDE_ERROR_MARKER


# Sentinel: attempt import at module level for --collect-only;
# tests that need these symbols call _import_symbols() in their body.
try:
    METRICS_HORIZONS, _build_zero_climate_result, _LOW_ALTITUDE_ERROR_MARKER = (
        _import_symbols()
    )
    _SYMBOLS_AVAILABLE = True
except ImportError:
    _SYMBOLS_AVAILABLE = False
    METRICS_HORIZONS = (20, 50, 100)  # fallback for helpers
    _LOW_ALTITUDE_ERROR_MARKER = "low_altitude"  # fallback for helpers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPECIES = ("CO2", "CH4", "O3", "H2O", "Contrails")


def _make_error_record(
    *,
    flight_id: str = "TEST001",
    departure_airport: str = "LFPG",
    arrival_airport: str = "EGLL",
    aobt: str = "2023-06-15 10:00:00",
    aircraft_type: str = "A320",
    engine_uid: str = "ENG001",
    error_msg: str = "Failed at some_step: some error",
) -> dict[str, Any]:
    """Build a minimal error record matching _create_error_record output."""
    return {
        "flight_information": {
            "flight_id": flight_id,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
            "aobt": aobt,
            "aircraft_type": aircraft_type,
            "engine_uid": engine_uid,
        },
        "error": error_msg,
    }


def _make_low_altitude_error(**kwargs: Any) -> dict[str, Any]:
    """Build an error record with the low-altitude marker in the error message."""
    kwargs.setdefault(
        "error_msg", f"Failed at altitude_check: {_LOW_ALTITUDE_ERROR_MARKER}"
    )
    return _make_error_record(**kwargs)


# ---------------------------------------------------------------------------
# Unit tests — _build_zero_climate_result
# ---------------------------------------------------------------------------


_need_symbols = pytest.mark.skipif(
    not _SYMBOLS_AVAILABLE,
    reason="_build_zero_climate_result not yet implemented",
)


@_need_symbols
class TestBuildZeroClimateResultStructure:
    """Test that the result has the correct top-level structure."""

    def test_build_zero_climate_result_structure(self) -> None:
        error_record = _make_low_altitude_error()
        result = _build_zero_climate_result(error_record)

        assert "flight_information" in result
        assert "climate_metrics" in result
        assert len(result["climate_metrics"]) == 5  # CO2, CH4, O3, H2O, Contrails


@_need_symbols
class TestBuildZeroClimateResultValues:
    """Test that all metric values are zero and scalars are correct."""

    def test_build_zero_climate_result_values(self) -> None:
        error_record = _make_low_altitude_error()
        result = _build_zero_climate_result(error_record)

        # All species EAGWP and CO2eq must be 0.0
        for species_block in result["climate_metrics"]:
            for val in species_block["value"]:
                assert val["EAGWP_Wm2yr"] == 0.0
                assert val["CO2eq_kg"] == 0.0

        # Scalar fields
        fi = result["flight_information"]
        assert fi["contrails_ef_J"] == 0.0
        assert math.isnan(fi["co2_baseline_kg"])
        assert math.isnan(fi["fuel_burn_kg"])


@_need_symbols
class TestBuildZeroClimateResultMarker:
    """Test that the low-altitude marker flag is set."""

    def test_build_zero_climate_result_marker(self) -> None:
        error_record = _make_low_altitude_error()
        result = _build_zero_climate_result(error_record)

        assert result["flight_information"]["low_altitude_flight"] is True


@_need_symbols
class TestBuildZeroClimateResultHorizons:
    """Test that horizons match METRICS_HORIZONS."""

    def test_build_zero_climate_result_horizons(self) -> None:
        error_record = _make_low_altitude_error()
        result = _build_zero_climate_result(error_record)

        for species_block in result["climate_metrics"]:
            horizons = tuple(v["horizon"] for v in species_block["value"])
            assert horizons == METRICS_HORIZONS


@_need_symbols
class TestBuildZeroClimateResultPreservesFlightInfo:
    """Test that flight information fields are preserved from the error record."""

    def test_build_zero_climate_result_preserves_flight_info(self) -> None:
        error_record = _make_error_record(
            flight_id="FLT42",
            departure_airport="KJFK",
            arrival_airport="EGLL",
            aobt="2024-01-15 08:30:00",
            aircraft_type="B777",
            engine_uid="GE90",
        )
        result = _build_zero_climate_result(error_record)

        fi = result["flight_information"]
        assert fi["flight_id"] == "FLT42"
        assert fi["departure_airport"] == "KJFK"
        assert fi["arrival_airport"] == "EGLL"
        assert fi["aobt"] == "2024-01-15 08:30:00"
        assert fi["aircraft_type"] == "B777"
        assert fi["engine_uid"] == "GE90"


# ---------------------------------------------------------------------------
# Functional tests — _extract_results
# ---------------------------------------------------------------------------


class TestExtractResultsSeparatesLowAltitude:
    """Test that _extract_results separates low-altitude errors into zero-results."""

    def test_extract_results_separates_low_altitude(self) -> None:
        """1 low-altitude error + 1 other error + successful flights.

        Expected: flight_results has successful + 1 zero-result + 1 error (3 total).
        """
        # Import here to avoid top-level pyBADA dependency
        pytest.importorskip("pyBADA", reason="pyBADA required")

        from pyneats.runners.fleet import FleetRunner

        runner = FleetRunner.__new__(FleetRunner)
        runner._pipeline_aborted = False

        # Mock successful flight
        successful_flight = MagicMock()
        successful_flight.attrs = {
            "climate_impact": {
                "flight_information": {"flight_id": "OK1"},
                "climate_metrics": [],
            }
        }
        runner.fleet_with_climate_impact = [successful_flight]

        # Set error records: 1 low-altitude + 1 other
        low_alt_error = _make_low_altitude_error(flight_id="LOW1")
        other_error = _make_error_record(
            flight_id="ERR1",
            error_msg="Failed at performance: engine not found",
        )
        runner.error_records = [low_alt_error, other_error]

        with (
            patch("pyneats.runners.fleet.FleetReport.collect", return_value={}),
            patch("pyneats.runners.fleet.clear_dataset_cache"),
        ):
            runner._extract_results()

        flight_results = runner.results["flight_results"]
        assert len(flight_results) == 3

        # Check the zero-result entry exists (has climate_metrics, no error key)
        zero_results = [
            r
            for r in flight_results
            if r.get("flight_information", {}).get("low_altitude_flight") is True
        ]
        assert len(zero_results) == 1
        assert "error" not in zero_results[0]
        assert "climate_metrics" in zero_results[0]


class TestExtractResultsAbortedWithLowAltitude:
    """Test aborted pipeline with low-altitude errors."""

    def test_extract_results_aborted_with_low_altitude(self) -> None:
        """Pipeline aborted: low-altitude errors → zero-results, others → raw errors."""
        pytest.importorskip("pyBADA", reason="pyBADA required")

        from pyneats.runners.fleet import FleetRunner

        runner = FleetRunner.__new__(FleetRunner)
        runner._pipeline_aborted = True
        runner.fleet_with_climate_impact = None

        low_alt_error = _make_low_altitude_error(flight_id="LOW1")
        other_error = _make_error_record(
            flight_id="ERR1",
            error_msg="Failed at parsing: invalid trajectory",
        )
        runner.error_records = [low_alt_error, other_error]

        with (
            patch("pyneats.runners.fleet.FleetReport.collect", return_value={}),
            patch("pyneats.runners.fleet.clear_dataset_cache"),
        ):
            runner._extract_results()

        flight_results = runner.results["flight_results"]

        # Should have zero-result entries + raw error entries
        zero_results = [
            r
            for r in flight_results
            if r.get("flight_information", {}).get("low_altitude_flight") is True
        ]
        raw_errors = [r for r in flight_results if "error" in r]

        assert len(zero_results) == 1
        assert len(raw_errors) == 1
        assert raw_errors[0]["flight_information"]["flight_id"] == "ERR1"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCaseNoLowAltitudeErrors:
    """No low-altitude errors — all errors passed through unchanged."""

    def test_no_low_altitude_errors(self) -> None:
        pytest.importorskip("pyBADA", reason="pyBADA required")

        from pyneats.runners.fleet import FleetRunner

        runner = FleetRunner.__new__(FleetRunner)
        runner._pipeline_aborted = True
        runner.fleet_with_climate_impact = None

        other_error = _make_error_record(
            flight_id="ERR1",
            error_msg="Failed at parsing: invalid trajectory",
        )
        runner.error_records = [other_error]

        with (
            patch("pyneats.runners.fleet.FleetReport.collect", return_value={}),
            patch("pyneats.runners.fleet.clear_dataset_cache"),
        ):
            runner._extract_results()

        flight_results = runner.results["flight_results"]

        # No zero-results generated
        zero_results = [
            r
            for r in flight_results
            if r.get("flight_information", {}).get("low_altitude_flight") is True
        ]
        assert len(zero_results) == 0
        # Original error passed through
        assert len(flight_results) == 1
        assert "error" in flight_results[0]


class TestEdgeCaseAllLowAltitude:
    """All errors are low-altitude — all transformed to zero-results."""

    def test_all_errors_are_low_altitude(self) -> None:
        pytest.importorskip("pyBADA", reason="pyBADA required")

        from pyneats.runners.fleet import FleetRunner

        runner = FleetRunner.__new__(FleetRunner)
        runner._pipeline_aborted = True
        runner.fleet_with_climate_impact = None

        runner.error_records = [
            _make_low_altitude_error(flight_id="LOW1"),
            _make_low_altitude_error(flight_id="LOW2"),
            _make_low_altitude_error(flight_id="LOW3"),
        ]

        with (
            patch("pyneats.runners.fleet.FleetReport.collect", return_value={}),
            patch("pyneats.runners.fleet.clear_dataset_cache"),
        ):
            runner._extract_results()

        flight_results = runner.results["flight_results"]

        # All transformed to zero-results
        zero_results = [
            r
            for r in flight_results
            if r.get("flight_information", {}).get("low_altitude_flight") is True
        ]
        assert len(zero_results) == 3
        # No raw error entries
        raw_errors = [r for r in flight_results if "error" in r]
        assert len(raw_errors) == 0


class TestEdgeCaseEmptyErrorRecords:
    """Empty error_records — no zero-results or errors generated."""

    def test_empty_error_records(self) -> None:
        pytest.importorskip("pyBADA", reason="pyBADA required")

        from pyneats.runners.fleet import FleetRunner

        runner = FleetRunner.__new__(FleetRunner)
        runner._pipeline_aborted = False

        successful_flight = MagicMock()
        successful_flight.attrs = {
            "climate_impact": {
                "flight_information": {"flight_id": "OK1"},
                "climate_metrics": [],
            }
        }
        runner.fleet_with_climate_impact = [successful_flight]
        runner.error_records = []

        with (
            patch("pyneats.runners.fleet.FleetReport.collect", return_value={}),
            patch("pyneats.runners.fleet.clear_dataset_cache"),
        ):
            runner._extract_results()

        flight_results = runner.results["flight_results"]

        # Only successful results, no zero-results or errors
        assert len(flight_results) == 1
        assert flight_results[0]["flight_information"]["flight_id"] == "OK1"
