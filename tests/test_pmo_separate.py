"""PMO (primary-mode ozone) is computed apart from CH4 and added into "CH4" (O14).

Method C: local_accf writes ``ATR_20_CH4`` without the old x1.29 and a separate
``ATR_20_PMO`` = 0.29 x ``ATR_20_CH4``. GWPMetrics converts each with its own
efficacy, RF backward factor and Dahlmann factors, then adds them into the
"CH4" entry. Method D: open_airclim stores ``AGWP_{H}_PMO`` apart and
GWPMetrics adds efficacy_PMO x AGWP_PMO into "CH4". A species without a
factor raises instead of falling back to 1.0.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from pyneats.core.neats_default_parameters import DEFAULT_ACCF_VALIDITY_PRESSURE
from pyneats.core.physics import CONVERSION_FACTORS_AGWP_TO_RF
from pyneats.core.physics import CONVERSION_FACTORS_ATR_TO_RF
from pyneats.core.physics import EFFICACY
from pyneats.core.physics import RF_BACKWARD_FACTOR
from pyneats.steps.climate_functions.local_accf import LocalACCFModel
from pyneats.steps.climate_metrics.gwp import GWPMetrics
from pyneats.steps.climate_metrics.gwp import GWPParams
from pyneats.steps.climate_metrics.protocol import ClimateImpactStepError


HORIZONS = (20, 50, 100)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _accf_model(pmo: bool) -> LocalACCFModel:
    m = LocalACCFModel.__new__(LocalACCFModel)
    params = LocalACCFModel.default_params()
    kwargs = {**params.accf_kwargs, "PMO": pmo}
    m.params = dataclasses.replace(params, accf_kwargs=kwargs)
    m.logger = MagicMock()
    return m


def _accf_flight() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "geopotential": [100_000.0, 105_000.0, 110_000.0],
            "time": pd.to_datetime(
                ["2025-07-09 10:00", "2025-07-09 10:01", "2025-07-09 10:02"]
            ),
            "latitude": [45.0, 46.0, 47.0],
            "nox_ei": [0.015, 0.016, 0.014],
            "fuel_burn": [40.0, 41.0, 39.0],
        }
    )


def _run_accf_written(model: LocalACCFModel, ch4: np.ndarray) -> dict[str, Any]:
    """Run LocalACCFModel.run with mocked species outputs; return written cols."""
    pressures = np.full(ch4.shape, DEFAULT_ACCF_VALIDITY_PRESSURE - 1000.0)
    pressures[-1] = DEFAULT_ACCF_VALIDITY_PRESSURE + 1000.0  # invalid -> NaN
    flight = MagicMock()
    written: dict[str, Any] = {}
    flight.__getitem__ = MagicMock(
        side_effect=lambda k: {"air_pressure": pressures}.get(k, np.zeros(ch4.shape))
    )
    flight.__setitem__ = MagicMock(side_effect=written.__setitem__)
    zeros = np.zeros(ch4.shape)
    with (
        patch.object(model, "_require_cols"),
        patch.object(model, "compute_o3", return_value=zeros.copy()),
        patch.object(model, "compute_ch4", return_value=ch4.copy()),
        patch.object(model, "compute_h2o", return_value=zeros.copy()),
        patch(
            "pyneats.steps.climate_functions.local_accf.FlightWithSegmentATR.from_flight",
            return_value=flight,
        ),
    ):
        model.run(flight)
    return written


def _gwp(**overrides: Any) -> GWPMetrics:
    return GWPMetrics(params=GWPParams(**overrides))


def _segment_flight(df: pd.DataFrame) -> MagicMock:
    flight = MagicMock()
    flight.to_dataframe = MagicMock(return_value=df)
    return flight


def _species(results: list[dict[str, Any]], name: str) -> dict[int, dict[str, float]]:
    entries = [r for r in results if r["species"] == name]
    assert len(entries) == 1, results
    return {v["horizon"]: v for v in entries[0]["value"]}


ATR_CH4_K = -2.0e-10
ATR_PMO_K = 0.29 * ATR_CH4_K


def _segment_df(with_pmo: bool) -> pd.DataFrame:
    data = {
        "ef": [0.0, 0.0],
        "ATR_20_CH4": [ATR_CH4_K / 2, ATR_CH4_K / 2],
        "ATR_20_O3": [1.0e-10, 1.0e-10],
        "ATR_20_H2O": [1.0e-11, 1.0e-11],
    }
    if with_pmo:
        data["ATR_20_PMO"] = [ATR_PMO_K / 2, ATR_PMO_K / 2]
    return pd.DataFrame(data)


def _global_flight(ch4: float, pmo: float | None) -> SimpleNamespace:
    attrs: dict[str, float] = {}
    for h in HORIZONS:
        attrs[f"AGWP_{h}_CH4"] = ch4
        attrs[f"AGWP_{h}_O3"] = 1.0e-13
        attrs[f"AGWP_{h}_H2O"] = 1.0e-14
        if pmo is not None:
            attrs[f"AGWP_{h}_PMO"] = pmo
    return SimpleNamespace(attrs=attrs)


# ---------------------------------------------------------------------------
# physics constants
# ---------------------------------------------------------------------------


def test_pmo_rf_backward_factor_is_ch4_value() -> None:
    assert RF_BACKWARD_FACTOR["PMO"] == RF_BACKWARD_FACTOR["CH4"] == 0.492


def test_pmo_efficacy_is_rsts_value() -> None:
    assert EFFICACY["PMO"] == 1.0


# ---------------------------------------------------------------------------
# Method C: local_accf
# ---------------------------------------------------------------------------


def test_compute_ch4_has_no_pmo_multiplier() -> None:
    """ATR_20_CH4 is the same with PMO on and off (no x1.29)."""
    flight = _accf_flight()
    on = _accf_model(pmo=True).compute_ch4(flight)
    off = _accf_model(pmo=False).compute_ch4(flight)
    assert np.all(on < 0.0)
    np.testing.assert_allclose(on, off, rtol=0, atol=0)


def test_run_writes_separate_pmo_column() -> None:
    ch4 = np.array([-1.0e-10, -3.0e-10, -5.0e-10])
    written = _run_accf_written(_accf_model(pmo=True), ch4)
    np.testing.assert_allclose(written["ATR_20_CH4"][:2], ch4[:2], rtol=1e-15)
    np.testing.assert_allclose(written["ATR_20_PMO"][:2], 0.29 * ch4[:2], rtol=1e-15)
    # The validity mask also applies to PMO
    assert np.isnan(written["ATR_20_CH4"][2])
    assert np.isnan(written["ATR_20_PMO"][2])


def test_run_without_pmo_writes_no_pmo_column() -> None:
    written = _run_accf_written(_accf_model(pmo=False), np.array([-1.0e-10, -2.0e-10]))
    assert "ATR_20_PMO" not in written


# ---------------------------------------------------------------------------
# Method C: GWPMetrics
# ---------------------------------------------------------------------------


def test_gwp_c_ch4_entry_is_ch4_part_plus_pmo_part() -> None:
    gwp = _gwp()
    with_pmo = _species(
        gwp._compute_from_segment_atr(_segment_flight(_segment_df(True))), "CH4"
    )
    ch4_only = _species(
        gwp._compute_from_segment_atr(_segment_flight(_segment_df(False))), "CH4"
    )
    pmo_part = gwp._eagwp_spec_Wm2yr("PMO", ATR_PMO_K)
    ch4_part = gwp._eagwp_spec_Wm2yr("CH4", ATR_CH4_K)
    for h in HORIZONS:
        assert ch4_only[h]["EAGWP_Wm2yr"] == pytest.approx(ch4_part[h], rel=1e-12)
        assert with_pmo[h]["EAGWP_Wm2yr"] == pytest.approx(
            ch4_part[h] + pmo_part[h], rel=1e-12
        )
        assert with_pmo[h]["CO2eq_kg"] == pytest.approx(
            with_pmo[h]["EAGWP_Wm2yr"] / gwp.params.agwp_coeff_wm2yr_per_kg[h],
            rel=1e-12,
        )


def test_gwp_c_pmo_part_ratio_with_unit_efficacy() -> None:
    """With eps_PMO = 1.0: PMO part = 0.29 x 0.9754 x CH4 part (at H=20).

    0.9754 = (k_AGWP,PMO / k_AGWP,CH4) x (k_ATR,CH4 / k_ATR,PMO) / 1.04**2
    with the same RF backward factor (0.492). A PMO falling back to an RF
    backward factor of 1.0 would give about half of that.
    """
    gwp = _gwp()
    with_pmo = _species(
        gwp._compute_from_segment_atr(_segment_flight(_segment_df(True))), "CH4"
    )
    ch4_part = gwp._eagwp_spec_Wm2yr("CH4", ATR_CH4_K)
    for h in HORIZONS:
        pmo_part = with_pmo[h]["EAGWP_Wm2yr"] - ch4_part[h]
        r = (
            CONVERSION_FACTORS_AGWP_TO_RF[h]["PMO"]
            / CONVERSION_FACTORS_AGWP_TO_RF[h]["CH4"]
            * CONVERSION_FACTORS_ATR_TO_RF[20]["CH4"]
            / CONVERSION_FACTORS_ATR_TO_RF[20]["PMO"]
            / 1.04**2
        )
        assert pmo_part == pytest.approx(0.29 * r * ch4_part[h], rel=1e-9)
    assert r == pytest.approx(0.9754, abs=5e-4)  # H=100 value
    assert with_pmo[20]["EAGWP_Wm2yr"] - ch4_part[20] == pytest.approx(
        0.29 * 0.9754 * ch4_part[20], rel=1e-3
    )


def test_gwp_c_pmo_efficacy_changes_only_pmo_part() -> None:
    base = _gwp()
    eff = {**EFFICACY, "PMO": 2.0}
    changed = _gwp(efficacy=eff)
    flight = _segment_flight(_segment_df(True))
    r_base = base._compute_from_segment_atr(flight)
    r_changed = changed._compute_from_segment_atr(flight)
    ch4_part = base._eagwp_spec_Wm2yr("CH4", ATR_CH4_K)
    b = _species(r_base, "CH4")
    c = _species(r_changed, "CH4")
    for h in HORIZONS:
        assert b[h]["EAGWP_Wm2yr"] - ch4_part[h] != 0.0
        # Method C: efficacy enters squared
        assert c[h]["EAGWP_Wm2yr"] - ch4_part[h] == pytest.approx(
            4.0 * (b[h]["EAGWP_Wm2yr"] - ch4_part[h]), rel=1e-12
        )
    for sp in ("O3", "H2O", "Contrails"):
        assert _species(r_base, sp) == _species(r_changed, sp)


# ---------------------------------------------------------------------------
# Method D: GWPMetrics
# ---------------------------------------------------------------------------


AGWP_CH4 = -3.0e-12
AGWP_PMO = -8.0e-13


def test_gwp_d_ch4_entry_is_eps_ch4_ch4_plus_eps_pmo_pmo() -> None:
    gwp = _gwp()
    ch4 = _species(
        gwp._compute_from_global_agwp(_global_flight(AGWP_CH4, AGWP_PMO)), "CH4"
    )
    for h in HORIZONS:
        expected = 1.04 * AGWP_CH4 + 1.0 * AGWP_PMO
        assert ch4[h]["EAGWP_Wm2yr"] == pytest.approx(expected, rel=1e-12)
        assert ch4[h]["CO2eq_kg"] == pytest.approx(
            expected / gwp.params.agwp_coeff_wm2yr_per_kg[h], rel=1e-12
        )


def test_gwp_d_pmo_efficacy_changes_only_pmo_part() -> None:
    flight = _global_flight(AGWP_CH4, AGWP_PMO)
    r_base = _gwp()._compute_from_global_agwp(flight)
    r_changed = _gwp(efficacy={**EFFICACY, "PMO": 1.5})._compute_from_global_agwp(
        flight
    )
    c = _species(r_changed, "CH4")
    for h in HORIZONS:
        assert c[h]["EAGWP_Wm2yr"] == pytest.approx(
            1.04 * AGWP_CH4 + 1.5 * AGWP_PMO, rel=1e-12
        )
    for sp in ("O3", "H2O"):
        assert _species(r_base, sp) == _species(r_changed, sp)


def test_open_airclim_stores_ch4_and_pmo_apart() -> None:
    """open_airclim no longer sums CH4 + PMO into AGWP_{h}_CH4."""
    import inspect

    from pyneats.steps.climate_functions import open_airclim

    src = inspect.getsource(open_airclim.OpenAirClimModel.run)
    assert 'flight.attrs[f"AGWP_{h}_PMO"]' in src
    assert '["CH4"] + results' not in src


# ---------------------------------------------------------------------------
# Missing factors raise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {
            "rf_backward_factor": {
                k: v for k, v in RF_BACKWARD_FACTOR.items() if k != "PMO"
            }
        },
        {"efficacy": {k: v for k, v in EFFICACY.items() if k != "PMO"}},
        {
            "k_atr_from_rf": {
                h: {k: v for k, v in d.items() if k != "PMO"}
                for h, d in CONVERSION_FACTORS_ATR_TO_RF.items()
            }
        },
        {
            "k_agwp_from_rf": {
                h: {k: v for k, v in d.items() if k != "PMO"}
                for h, d in CONVERSION_FACTORS_AGWP_TO_RF.items()
            }
        },
    ],
    ids=["rf_backward", "efficacy", "k_atr", "k_agwp"],
)
def test_gwp_c_missing_pmo_factor_raises(override: dict[str, Any]) -> None:
    gwp = _gwp(**override)
    with pytest.raises(ClimateImpactStepError, match="PMO"):
        gwp._compute_from_segment_atr(_segment_flight(_segment_df(True)))


def test_gwp_d_missing_pmo_efficacy_raises() -> None:
    gwp = _gwp(efficacy={k: v for k, v in EFFICACY.items() if k != "PMO"})
    with pytest.raises(ClimateImpactStepError, match="PMO"):
        gwp._compute_from_global_agwp(_global_flight(AGWP_CH4, AGWP_PMO))


def test_missing_ch4_rf_backward_raises() -> None:
    gwp = _gwp(rf_backward_factor={"O3": 0.508, "H2O": 0.52, "PMO": 0.492})
    with pytest.raises(ClimateImpactStepError, match="CH4"):
        gwp._eagwp_spec_Wm2yr("CH4", ATR_CH4_K)


# ---------------------------------------------------------------------------
# CLIMaCCF backend (climaccf.py): the library never merges PMO into CH4
# ---------------------------------------------------------------------------


def _climaccf_model(pmo: bool) -> Any:
    from pyneats.steps.climate_functions.climaccf import ACCFModel

    m = ACCFModel.__new__(ACCFModel)
    params = ACCFModel.default_params()
    kwargs = {**params.accf_kwargs, "PMO": pmo}
    m.params = dataclasses.replace(
        params, accf_kwargs=kwargs, met=MagicMock(), surface=MagicMock()
    )
    m.logger = MagicMock()
    return m


@pytest.mark.parametrize("pmo", [True, False])
def test_climaccf_library_called_without_pmo(pmo: bool) -> None:
    m = _climaccf_model(pmo)
    target = "pyneats.steps.climate_functions.climaccf"
    with (
        patch(f"{target}.make_accf_surface_view", return_value=MagicMock()),
        patch(f"{target}.ACCF") as accf_cls,
    ):
        m._post_init()
    assert accf_cls.call_args.kwargs["PMO"] is False


@pytest.mark.parametrize("pmo", [True, False])
def test_climaccf_run_writes_pmo_apart(pmo: bool) -> None:
    m = _climaccf_model(pmo)
    df = _accf_flight()
    df["aCCF_CH4"] = [-1.0e-12, -2.0e-12, -3.0e-12]
    df["aCCF_O3"] = [1.0e-12, 1.0e-12, 1.0e-12]
    df["aCCF_H2O"] = [1.0e-15, 1.0e-15, 1.0e-15]
    out = MagicMock()
    out.to_dataframe = MagicMock(return_value=df)
    m._impl = MagicMock()
    m._impl.eval = MagicMock(return_value=out)
    written: dict[str, Any] = {}
    flight = MagicMock()
    flight.__setitem__ = MagicMock(side_effect=written.__setitem__)
    flight.__getitem__ = MagicMock(side_effect=written.__getitem__)
    # default unit_K_per_kg_fuel=False: aCCF_CH4 is per kg NOx, times nox_ei
    expected_ch4 = (df["fuel_burn"] * df["aCCF_CH4"] * df["nox_ei"]).to_numpy()
    with patch(
        "pyneats.steps.climate_functions.climaccf.FlightWithSegmentATR.from_flight",
        return_value=flight,
    ):
        m.run(flight)
    np.testing.assert_allclose(written["ATR_20_CH4"], expected_ch4, rtol=1e-15)
    if pmo:
        np.testing.assert_allclose(
            written["ATR_20_PMO"], 0.29 * expected_ch4, rtol=1e-15
        )
    else:
        assert "ATR_20_PMO" not in written
