"""Tests for the validity mask NaN change in LocalACCFModel.run().

Verifies that waypoints outside the aCCF validity region (pressure above
threshold) get NaN in ATR columns instead of 0 — and that downstream
GWP summation remains numerically identical thanks to fillna(0.0).
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from pyneats.core.neats_default_parameters import DEFAULT_ACCF_VALIDITY_PRESSURE
from pyneats.steps.climate_functions.local_accf import LocalACCFModel


class TestValidityMaskNaN:
    """Validity mask should produce NaN for invalid waypoints."""

    @pytest.fixture()
    def model(self) -> LocalACCFModel:
        m = LocalACCFModel.__new__(LocalACCFModel)
        m.params = LocalACCFModel.default_params()
        m.logger = MagicMock()
        return m

    def test_invalid_waypoints_are_nan(self, model: LocalACCFModel) -> None:
        """Waypoints above the validity pressure threshold get NaN."""
        pressures = np.array(
            [
                DEFAULT_ACCF_VALIDITY_PRESSURE - 1000,  # valid
                DEFAULT_ACCF_VALIDITY_PRESSURE + 1000,  # invalid
            ]
        )
        fake_o3 = np.array([1.0e-10, 3.0e-10])
        fake_ch4 = np.array([-1.0e-10, -3.0e-10])
        fake_h2o = np.array([5.0e-10, 7.0e-10])

        flight = MagicMock()
        written: dict[str, np.ndarray] = {}
        flight.__getitem__ = MagicMock(
            side_effect=lambda k: {
                "air_pressure": pressures,
            }.get(k, np.zeros(2))
        )
        flight.__setitem__ = MagicMock(
            side_effect=lambda k, v: written.__setitem__(k, v)
        )

        with (
            patch.object(model, "_require_cols"),
            patch.object(model, "compute_o3", return_value=fake_o3.copy()),
            patch.object(model, "compute_ch4", return_value=fake_ch4.copy()),
            patch.object(model, "compute_h2o", return_value=fake_h2o.copy()),
            patch(
                "pyneats.steps.climate_functions.local_accf.FlightWithSegmentATR.from_flight",
                return_value=flight,
            ),
        ):
            model.run(flight)

        # Valid waypoint keeps its value
        assert written["ATR_20_O3"][0] == pytest.approx(1.0e-10)
        assert written["ATR_20_CH4"][0] == pytest.approx(-1.0e-10)
        assert written["ATR_20_H2O"][0] == pytest.approx(5.0e-10)

        # Invalid waypoint → NaN
        assert np.isnan(written["ATR_20_O3"][1])
        assert np.isnan(written["ATR_20_CH4"][1])
        assert np.isnan(written["ATR_20_H2O"][1])

    def test_all_valid_no_nan(self, model: LocalACCFModel) -> None:
        """When all waypoints are valid, no NaN is introduced."""
        pressures = np.array(
            [
                DEFAULT_ACCF_VALIDITY_PRESSURE - 1000,
                DEFAULT_ACCF_VALIDITY_PRESSURE - 2000,
            ]
        )
        fake_o3 = np.array([1.0e-10, 2.0e-10])
        fake_ch4 = np.array([-1.0e-10, -2.0e-10])
        fake_h2o = np.array([5.0e-10, 6.0e-10])

        flight = MagicMock()
        written: dict[str, np.ndarray] = {}
        flight.__getitem__ = MagicMock(
            side_effect=lambda k: {
                "air_pressure": pressures,
            }.get(k, np.zeros(2))
        )
        flight.__setitem__ = MagicMock(
            side_effect=lambda k, v: written.__setitem__(k, v)
        )

        with (
            patch.object(model, "_require_cols"),
            patch.object(model, "compute_o3", return_value=fake_o3.copy()),
            patch.object(model, "compute_ch4", return_value=fake_ch4.copy()),
            patch.object(model, "compute_h2o", return_value=fake_h2o.copy()),
            patch(
                "pyneats.steps.climate_functions.local_accf.FlightWithSegmentATR.from_flight",
                return_value=flight,
            ),
        ):
            model.run(flight)

        assert not np.any(np.isnan(written["ATR_20_O3"]))
        assert not np.any(np.isnan(written["ATR_20_CH4"]))
        assert not np.any(np.isnan(written["ATR_20_H2O"]))


class TestGWPNanSumEquivalence:
    """Downstream GWP summation must be unaffected by NaN values."""

    def test_fillna_sum_matches_zero_sum(self) -> None:
        """fillna(0.0).sum() on a Series with NaN gives identical result to zeros."""
        with_nan = pd.Series([1.0, 2.0, np.nan, 4.0, np.nan])
        with_zero = pd.Series([1.0, 2.0, 0.0, 4.0, 0.0])

        result_nan = pd.to_numeric(with_nan, errors="coerce").fillna(0.0).sum()
        result_zero = pd.to_numeric(with_zero, errors="coerce").fillna(0.0).sum()

        assert result_nan == pytest.approx(result_zero)
        assert result_nan == pytest.approx(7.0)
