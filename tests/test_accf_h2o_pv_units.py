"""Potential vorticity units in the local aCCF H2O regression (audit O1).

pycontrails supplies potential vorticity in SI units (K m^2 kg^-1 s^-1). The
H2O aCCF regression (CLIMaCCF; Matthes et al., 2023, Annex A) is defined for
PV in PVU (1 PVU = 1e-6 SI). ``LocalACCFModel`` must convert SI to PVU before
it applies the regression. See docs/internal/pyneats_units_audit.md, O1.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from pycontrails import Flight

from pyneats.steps.climate_functions.local_accf import LocalACCFModel


# Regression coefficients, CLIMaCCF aCCF V1.0 H2O: [K/kg(fuel)] and [K/kg(fuel)/PVU]
_H2O_CONST = 4.05e-16
_H2O_SLOPE_PER_PVU = 1.48e-16
# pytest.approx has a default absolute tolerance of 1e-12, which would accept any
# value of this magnitude (1e-16 to 1e-14), so every approx below sets abs=0.


@pytest.fixture()
def model() -> LocalACCFModel:
    m = LocalACCFModel.__new__(LocalACCFModel)
    m.params = LocalACCFModel.default_params()
    m.logger = MagicMock()
    return m


def _flight(pv_si: np.ndarray, fuel_burn: np.ndarray) -> Flight:
    n = len(pv_si)
    df = pd.DataFrame(
        {
            "longitude": np.linspace(0.0, 1.0, n),
            "latitude": np.full(n, 45.0),
            "altitude": np.full(n, 11000.0),
            "time": pd.date_range("2025-07-09 12:00", periods=n, freq="1min"),
            "potential_vorticity": pv_si,
            "fuel_burn": fuel_burn,
        }
    )
    return Flight(df)


def test_pvu_per_si_constant() -> None:
    # Imported here so that the behaviour tests below still run (and fail on
    # their assertions) against a source tree without the constant.
    from pyneats.core.physics import PVU_PER_SI

    assert PVU_PER_SI == 1e6


def test_raw_formula_applies_regression_to_pv_in_pvu() -> None:
    """PV 2e-6 SI = 2 PVU gives 4.05e-16 + 1.48e-16 * 2."""
    pv_si = np.array([2e-6, 0.0, 1.3e-5])
    got = LocalACCFModel.h2o_raw_formula(pv_si)
    expected = _H2O_CONST + _H2O_SLOPE_PER_PVU * np.abs(pv_si * 1e6)
    np.testing.assert_allclose(got, expected, rtol=1e-12)
    assert got[0] == pytest.approx(4.05e-16 + 2.96e-16, rel=1e-12, abs=0.0)


def test_pv_term_is_not_negligible() -> None:
    """The result depends on PV at realistic SI magnitudes (|PV| ~ 1e-7 to 1e-5)."""
    low, high = LocalACCFModel.h2o_raw_formula(np.array([1e-7, 1e-5]))
    # 10 PVU: 4.05e-16 + 1.48e-15 = 1.885e-15, about 4.65 times the constant term
    assert high / low > 4.0
    assert high == pytest.approx(
        _H2O_CONST + 10 * _H2O_SLOPE_PER_PVU, rel=1e-12, abs=0.0
    )
    # The PV term at 2 PVU is about 73 % of the constant term, not ~1e-6 of it
    (two_pvu,) = LocalACCFModel.h2o_raw_formula(np.array([2e-6]))
    assert (two_pvu - _H2O_CONST) / _H2O_CONST == pytest.approx(
        2.96e-16 / 4.05e-16, rel=1e-12, abs=0.0
    )


def test_sign_of_pv_is_ignored() -> None:
    """Southern-hemisphere PV is negative; the regression uses |PV|."""
    pv_si = np.array([3e-6, -3e-6])
    pos, neg = LocalACCFModel.h2o_raw_formula(pv_si)
    assert pos == neg
    assert pos == pytest.approx(_H2O_CONST + 3 * _H2O_SLOPE_PER_PVU, rel=1e-12, abs=0.0)


def test_raw_formula_keeps_nan() -> None:
    got = LocalACCFModel.h2o_raw_formula(np.array([np.nan, 1e-6]))
    assert np.isnan(got[0])
    assert np.isfinite(got[1])


def test_compute_h2o_converts_flight_pv_from_si(model: LocalACCFModel) -> None:
    """compute_h2o: K per segment = regression(|PV| in PVU) / scale * fuel_burn."""
    pv_si = np.array([2e-6, -5e-6, 1e-7])
    fuel_burn = np.array([100.0, 50.0, 10.0])  # kg
    flight = _flight(pv_si, fuel_burn)

    got = model.compute_h2o(flight)

    scale = model.params.scale_h2o[model.params.accf_kwargs["accf_v"]]
    expected = (
        (_H2O_CONST + _H2O_SLOPE_PER_PVU * np.abs(pv_si * 1e6)) / scale * fuel_burn
    )
    np.testing.assert_allclose(got, expected, rtol=1e-12)
    # Per kg of fuel the result is no longer the constant term alone
    per_kg = got * scale / fuel_burn
    assert not np.allclose(per_kg, _H2O_CONST, rtol=1e-3, atol=0.0)
