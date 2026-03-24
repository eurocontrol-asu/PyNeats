"""Tests for data sanity guardrails (AXM-431).

Three guardrails:
1. Parsing: reject trajectories spanning >24 hours
2. Performance: reject total fuel burn exceeding (MTOW - OEW) x threshold
3. Climate: reject non-CO2 species with CO2eq > 100x CO2 baseline
"""

from __future__ import annotations

import pytest


# pyBADA is required for performance module imports
pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pandas as pd

from pyneats.steps.climate_metrics.gwp import GWPMetrics
from pyneats.steps.climate_metrics.gwp import GWPParams
from pyneats.steps.climate_metrics.protocol import ClimateImpactStepError
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParserParams
from pyneats.steps.parsing.protocol import TrajectoryParserStepError
from pyneats.steps.parsing.views import Flight4D
from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parser_df(
    *,
    hours: float = 2.0,
    n_points: int = 10,
) -> pd.DataFrame:
    """Build a minimal DataFrame that NeatsTrajectoryParser.run() can process.

    Parameters
    ----------
    hours : float
        Total trajectory duration in hours.
    n_points : int
        Number of trajectory points.
    """
    freq = (
        pd.Timedelta(hours=hours / max(n_points - 1, 1))
        if hours > 0
        else pd.Timedelta(seconds=1)
    )
    times = pd.date_range(
        "2023-06-15 10:00:00",
        periods=n_points,
        freq=freq,
        tz="UTC",
    )
    df = pd.DataFrame(
        {
            "time": times.strftime("%Y-%m-%d %H:%M:%S"),
            "latitude": np.linspace(48.0, 49.0, n_points),
            "longitude": np.linspace(2.0, 3.0, n_points),
            "altitude": np.linspace(350, 380, n_points),  # FL350-FL380
        }
    )
    df.attrs = {
        "flight_id": "TEST001",
        "aircraft_type": "A320",
        "departure_airport": "LFPG",
        "arrival_airport": "EGLL",
        "model_type": "BADA4",
        "aobt": "2023-06-15 10:00:00",
    }
    return df


# ---------------------------------------------------------------------------
# Task 1 — Parsing guardrail: 24h duration check
# ---------------------------------------------------------------------------


class TestParsingGuardrail24h:
    """Guardrail: reject trajectories spanning > 24 hours."""

    def test_parser_rejects_trajectory_over_24h(self) -> None:
        """25h trajectory raises TrajectoryParserStepError."""
        df = _make_parser_df(hours=25.0, n_points=5)
        parser = NeatsTrajectoryParser(params=NeatsTrajectoryParserParams())

        with pytest.raises(TrajectoryParserStepError, match="24"):
            parser.run(df)

    def test_parser_accepts_trajectory_under_24h(self) -> None:
        """2h trajectory is accepted normally."""
        df = _make_parser_df(hours=2.0, n_points=5)
        parser = NeatsTrajectoryParser(params=NeatsTrajectoryParserParams())

        result = parser.run(df)
        assert isinstance(result, Flight4D)

    def test_parser_accepts_trajectory_exactly_24h(self) -> None:
        """Exactly 24:00:00 passes (strictly greater triggers rejection)."""
        df = _make_parser_df(hours=24.0, n_points=5)
        parser = NeatsTrajectoryParser(params=NeatsTrajectoryParserParams())

        result = parser.run(df)
        assert isinstance(result, Flight4D)

    def test_parser_accepts_single_point(self) -> None:
        """Single-point trajectory: duration=0, passes 24h check."""
        df = _make_parser_df(hours=0.0, n_points=1)
        parser = NeatsTrajectoryParser(params=NeatsTrajectoryParserParams())

        result = parser.run(df)
        assert isinstance(result, Flight4D)


# ---------------------------------------------------------------------------
# Task 2 — Performance guardrail: fuel burn vs payload capacity
# ---------------------------------------------------------------------------


class TestPerformanceGuardrailFuelBurn:
    """Guardrail: reject total fuel burn exceeding useful payload capacity."""

    def _make_model(self) -> BADAPerformanceModel:
        """Create a BADAPerformanceModel with mocked internals."""
        model = MagicMock(spec=BADAPerformanceModel)
        model.logger = MagicMock()
        # Bind the real methods
        model.run_by_bada_version = BADAPerformanceModel.run_by_bada_version.__get__(
            model
        )
        model._build_result = BADAPerformanceModel._build_result.__get__(model)
        return model

    def _make_adapter(
        self,
        *,
        mtow: float | None = 80_000.0,
        oew: float | None = 45_000.0,
    ) -> MagicMock:
        adapter = MagicMock()
        adapter.MTOW = mtow
        adapter.OEW = oew
        adapter.span = 35.8
        adapter.nb_eng = 2
        adapter.bada_code = "A320"
        return adapter

    def _make_flight_df(self, total_fuel: float, n_points: int = 5) -> pd.DataFrame:
        """Build a DataFrame with fuel_burn column summing to total_fuel."""
        per_point = total_fuel / n_points
        times = pd.date_range(
            "2023-01-01 10:00", periods=n_points, freq="1min", tz="UTC"
        )
        return pd.DataFrame(
            {
                "latitude": [51.5 + i * 0.1 for i in range(n_points)],
                "longitude": [-0.1 + i * 0.1 for i in range(n_points)],
                "time": times,
                "altitude": [10000.0] * n_points,
                "fuel_burn": [per_point] * n_points,
                "fuel_flow": [per_point / 60] * n_points,
                "segment_duration": [60.0] * n_points,
                "thrust": [50000.0] * n_points,
                "aircraft_mass": [70000.0] * n_points,
                "phase": ["Cruise"] * n_points,
                "thrust_segment": ["TOTAL"] * n_points,
                "true_airspeed": [230.0] * n_points,
            }
        )

    def test_bada_rejects_unrealistic_fuel_burn(self) -> None:
        """fuel_burn=40000 > (80000-45000)*1.1=38500 → raises."""
        model = self._make_model()
        adapter = self._make_adapter(mtow=80_000, oew=45_000)
        df = self._make_flight_df(total_fuel=40_000)

        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "CFM56")
        )
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(
            return_value=(
                {
                    "mass": [70000.0] * 5,
                    "fuel_flow": [df["fuel_flow"].iloc[0]] * 5,
                    "thrust": [50000.0] * 5,
                    "phase": ["Cruise"] * 5,
                    "segment": ["TOTAL"] * 5,
                },
                43_130_000.0,
            )
        )
        model._finalize_columns = MagicMock(
            side_effect=lambda d, p: d.update({"fuel_burn": [40_000 / 5] * 5}) or None
        )
        model._compute_engine_efficiency_if_missing = MagicMock()
        model._attach_output_attrs = MagicMock()

        # Create params with default threshold
        model.params = MagicMock()
        model.params.fuel_burn_threshold = 1.1

        flight = MagicMock()
        flight.attrs = {"aircraft_type": "A320"}
        flight.fuel = MagicMock()

        with pytest.raises(PerformanceStepError, match="fuel burn"):
            model.run_by_bada_version(flight, df, "A320", None, None, None)

    def test_bada_accepts_realistic_fuel_burn(self) -> None:
        """fuel_burn=10000 < (80000-45000)*1.1=38500 → passes."""
        model = self._make_model()
        adapter = self._make_adapter(mtow=80_000, oew=45_000)
        df = self._make_flight_df(total_fuel=10_000)

        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "CFM56")
        )
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(
            return_value=(
                {
                    "mass": [70000.0] * 5,
                    "fuel_flow": [df["fuel_flow"].iloc[0]] * 5,
                    "thrust": [50000.0] * 5,
                    "phase": ["Cruise"] * 5,
                    "segment": ["TOTAL"] * 5,
                },
                43_130_000.0,
            )
        )

        def finalize(d, p):
            d["fuel_burn"] = [10_000 / 5] * 5

        model._finalize_columns = MagicMock(side_effect=finalize)
        model._compute_engine_efficiency_if_missing = MagicMock()
        model._attach_output_attrs = MagicMock()
        model.params = MagicMock()
        model.params.fuel_burn_threshold = 1.1

        flight = MagicMock()
        flight.attrs = {"aircraft_type": "A320"}
        flight.fuel = MagicMock()

        # Patch Flight and FlightWithPerformance to skip downstream validation
        with (
            patch(
                "pyneats.steps.performance.bada_model.Flight",
                return_value=MagicMock(),
            ),
            patch(
                "pyneats.steps.performance.bada_model.FlightWithPerformance.from_flight",
                return_value=MagicMock(),
            ),
        ):
            result = model.run_by_bada_version(flight, df, "A320", None, None, None)
            assert result is not None

    def test_bada_skips_guardrail_when_mtow_none(self) -> None:
        """MTOW=None → skip guardrail, log warning, don't crash."""
        model = self._make_model()
        adapter = self._make_adapter(mtow=None, oew=45_000)
        df = self._make_flight_df(total_fuel=99_999)

        model._resolve_bada_adapter = MagicMock(
            return_value=(adapter, "BADA4", 2, "CFM56")
        )
        model._early_exit_if_fuel_and_efficiency = MagicMock(return_value=None)
        model._derive_fuel_flow_from_mass_if_needed = MagicMock()
        model._choose_mass_strategy = MagicMock(
            return_value=(
                {
                    "mass": [70000.0] * 5,
                    "fuel_flow": [1.0] * 5,
                    "thrust": [50000.0] * 5,
                    "phase": ["Cruise"] * 5,
                    "segment": ["TOTAL"] * 5,
                },
                43_130_000.0,
            )
        )

        def finalize(d, p):
            d["fuel_burn"] = [99_999 / 5] * 5

        model._finalize_columns = MagicMock(side_effect=finalize)
        model._compute_engine_efficiency_if_missing = MagicMock()
        model._attach_output_attrs = MagicMock()
        model.params = MagicMock()
        model.params.fuel_burn_threshold = 1.1

        flight = MagicMock()
        flight.attrs = {"aircraft_type": "A320"}
        flight.fuel = MagicMock()

        # Patch Flight and FlightWithPerformance to skip downstream validation
        with (
            patch(
                "pyneats.steps.performance.bada_model.Flight",
                return_value=MagicMock(),
            ),
            patch(
                "pyneats.steps.performance.bada_model.FlightWithPerformance.from_flight",
                return_value=MagicMock(),
            ),
        ):
            result = model.run_by_bada_version(flight, df, "A320", None, None, None)
            assert result is not None
            model.logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Task 3 — Climate guardrail: non-CO2 ratio vs CO2 baseline
# ---------------------------------------------------------------------------


class TestClimateGuardrailNonCO2:
    """Guardrail: reject non-CO2 species with CO2eq > 100x CO2 baseline."""

    def _make_gwp(self) -> GWPMetrics:
        return GWPMetrics(params=GWPParams())

    def _make_flight_with_global_agwp(
        self,
        total_co2: float,
        ch4_agwp_20: float = 0.0,
        o3_agwp_20: float = 0.0,
        h2o_agwp_20: float = 0.0,
    ) -> MagicMock:
        """Build a mock FlightWithGlobalAGWP."""
        from pyneats.steps.climate_functions.views import FlightWithGlobalAGWP

        flight = MagicMock(spec=FlightWithGlobalAGWP)
        flight.attrs = {
            "total_co2": total_co2,
            "flight_id": "TEST001",
            "aircraft_type": "A320",
            "departure_airport": "LFPG",
            "arrival_airport": "EGLL",
            "AGWP_20_CH4": ch4_agwp_20,
            "AGWP_50_CH4": ch4_agwp_20,
            "AGWP_100_CH4": ch4_agwp_20,
            "AGWP_20_O3": o3_agwp_20,
            "AGWP_50_O3": o3_agwp_20,
            "AGWP_100_O3": o3_agwp_20,
            "AGWP_20_H2O": h2o_agwp_20,
            "AGWP_50_H2O": h2o_agwp_20,
            "AGWP_100_H2O": h2o_agwp_20,
        }
        # Ensure isinstance checks work
        flight.__class__ = FlightWithGlobalAGWP
        # Mock __contains__ for "fuel_burn" in flight
        flight.__contains__ = MagicMock(return_value=False)
        return flight

    def test_gwp_rejects_implausible_nonco2(self) -> None:
        """CH4 CO2eq=200000 > 100x1000 -> raises."""
        gwp = self._make_gwp()

        # We need a very large AGWP to produce CO2eq > 100x CO2
        # CO2eq = EAGWP / (C(H) * s_yr)
        # So AGWP must be large enough: AGWP * efficacy / (C(H) * s_yr) > 100 * 1000
        # C(20) ~ 2.495e-14, s_yr = 31556926
        # => AGWP > 100 * 1000 * 2.495e-14 * 31556926 ≈ 0.0787
        huge_agwp = 1e6  # Far exceeds threshold

        flight = self._make_flight_with_global_agwp(
            total_co2=1000.0,
            ch4_agwp_20=huge_agwp,
        )

        with pytest.raises(ClimateImpactStepError, match="100"):
            gwp.run(flight)

    def test_gwp_accepts_plausible_nonco2(self) -> None:
        """Tiny CO2eq < 100x1000 -> passes."""
        gwp = self._make_gwp()

        # Very small AGWP → CO2eq will be tiny
        flight = self._make_flight_with_global_agwp(
            total_co2=1000.0,
            ch4_agwp_20=1e-15,
            o3_agwp_20=1e-15,
            h2o_agwp_20=1e-15,
        )

        # Mock the FlightReport.extract and FlightWithClimateImpact.from_flight
        with (
            patch(
                "pyneats.steps.climate_metrics.gwp.FlightReport.extract",
                return_value={"flight_id": "TEST001"},
            ),
            patch(
                "pyneats.steps.climate_metrics.gwp.FlightWithClimateImpact.from_flight",
                return_value=MagicMock(),
            ),
        ):
            result = gwp.run(flight)
            assert result is not None

    def test_gwp_skips_ratio_when_co2_zero(self) -> None:
        """total_co2=0.0 → skip ratio check, no crash."""
        gwp = self._make_gwp()

        flight = self._make_flight_with_global_agwp(
            total_co2=0.0,
            ch4_agwp_20=1e6,  # Would exceed ratio if CO2 > 0
        )

        with (
            patch(
                "pyneats.steps.climate_metrics.gwp.FlightReport.extract",
                return_value={"flight_id": "TEST001"},
            ),
            patch(
                "pyneats.steps.climate_metrics.gwp.FlightWithClimateImpact.from_flight",
                return_value=MagicMock(),
            ),
        ):
            result = gwp.run(flight)
            assert result is not None
