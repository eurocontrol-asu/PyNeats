"""Tests for the non-CO2 scaling of Methods C and D (``RunnerConfig.non_co2_scaling``).

``"accf_version"`` (default) must give the results of before the option
existed. ``"scaling_to_baseline_2026"`` replaces, for Method C, both
``ACCF_SCALE_*[accf_v]`` and ``RF_BACKWARD_FACTOR`` with one divisor, and
divides the Method D (OpenAirClim) AGWP. The tests that need values patch
test divisors in, so they do not depend on the values of core/physics.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from pycontrails import Flight

from pyneats.core import non_co2_scaling
from pyneats.core import physics
from pyneats.core.non_co2_scaling import non_co2_scaling_divisors
from pyneats.core.physics import ACCF_SCALE_03
from pyneats.core.physics import ACCF_SCALE_CH4
from pyneats.core.physics import ACCF_SCALE_H2O
from pyneats.core.physics import RF_BACKWARD_FACTOR
from pyneats.runners.flight import RunnerConfig
from pyneats.runners.flight import with_non_co2_scaling
from pyneats.steps.climate_functions.local_accf import LocalACCFModel
from pyneats.steps.climate_functions.local_accf import LocalACCFParams
from pyneats.steps.climate_functions.open_airclim import _agwp_attrs
from pyneats.steps.climate_functions.protocol import ACCFStepError
from pyneats.steps.climate_metrics.gwp import GWPMetrics
from pyneats.steps.climate_metrics.gwp import GWPParams


NEW = "scaling_to_baseline_2026"
C_DIVISORS = {"O3": 4.0, "CH4": 20.0, "H2O": 1.5}
D_DIVISORS = {"O3": 1.25, "CH4": 0.8, "H2O": 2.0}


@pytest.fixture()
def divisors_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the "scaling_to_baseline_2026" scaling test divisors."""
    monkeypatch.setitem(
        non_co2_scaling._DIVISORS, NEW, {"C": C_DIVISORS, "D": D_DIVISORS}
    )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_accf_version_has_no_divisors() -> None:
    assert non_co2_scaling_divisors("accf_version", "C") is None
    assert non_co2_scaling_divisors("accf_version", "D") is None


def test_unknown_scaling_raises() -> None:
    with pytest.raises(ValueError, match="Unknown non-CO2 scaling"):
        non_co2_scaling_divisors("V1.0B", "C")


@pytest.fixture()
def divisors_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the "scaling_to_baseline_2026" scaling divisors that are not set."""
    not_set = dict.fromkeys(("O3", "CH4", "H2O"))
    monkeypatch.setitem(non_co2_scaling._DIVISORS, NEW, {"C": not_set, "D": not_set})


@pytest.mark.parametrize("method", ["C", "D"])
def test_placeholders_raise(divisors_not_set: None, method: str) -> None:
    """A divisor that is not set (None): the scaling cannot be used."""
    with pytest.raises(ValueError, match=r"no Method .* divisor yet"):
        non_co2_scaling_divisors(NEW, method)  # type: ignore[arg-type]


@pytest.mark.parametrize("method", ["C", "D"])
def test_values_resolve(method: str) -> None:
    """The values of core/physics.py resolve, PMO with a divisor of its own."""
    divisors = non_co2_scaling_divisors(NEW, method)  # type: ignore[arg-type]
    assert divisors is not None
    assert set(divisors) == {"O3", "CH4", "PMO", "H2O"}
    assert all(v > 0.0 for v in divisors.values())
    assert divisors["PMO"] != divisors["CH4"]


def test_method_c_divisors_combine_the_two_steps() -> None:
    """C* = C x (C to D) x (D to Lee et al.), from the "accf_version" divisor."""
    c = non_co2_scaling_divisors(NEW, "C")
    d = non_co2_scaling_divisors(NEW, "D")
    assert c is not None and d is not None
    scale = {"O3": ACCF_SCALE_03, "CH4": ACCF_SCALE_CH4, "PMO": ACCF_SCALE_CH4}
    scale["H2O"] = ACCF_SCALE_H2O
    for sp, c_to_d in physics._BASELINE_2026_C_TO_D.items():
        legacy = scale[sp]["V1.0A"] * RF_BACKWARD_FACTOR[sp]
        assert legacy / c[sp] == pytest.approx(c_to_d / d[sp], rel=1e-12)


def test_divisors_pmo_uses_ch4(divisors_set: None) -> None:
    assert non_co2_scaling_divisors(NEW, "C") == {**C_DIVISORS, "PMO": 20.0}
    assert non_co2_scaling_divisors(NEW, "D") == {**D_DIVISORS, "PMO": 0.8}


def test_divisors_own_pmo_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        non_co2_scaling._DIVISORS,
        NEW,
        {"C": C_DIVISORS, "D": {**D_DIVISORS, "PMO": 0.5}},
    )
    assert non_co2_scaling_divisors(NEW, "D") == {**D_DIVISORS, "PMO": 0.5}


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_non_positive_divisor_raises(
    monkeypatch: pytest.MonkeyPatch, bad: float
) -> None:
    monkeypatch.setitem(
        non_co2_scaling._DIVISORS,
        NEW,
        {"C": {**C_DIVISORS, "O3": bad}, "D": D_DIVISORS},
    )
    with pytest.raises(ValueError, match="must be positive"):
        non_co2_scaling_divisors(NEW, "C")


# ---------------------------------------------------------------------------
# Method C: local_accf
# ---------------------------------------------------------------------------


def _model(**params: object) -> LocalACCFModel:
    m = LocalACCFModel.__new__(LocalACCFModel)
    m.params = LocalACCFParams(**params)  # type: ignore[arg-type]
    m.logger = MagicMock()
    return m


def _flight(n: int = 3) -> Flight:
    df = pd.DataFrame(
        {
            "longitude": np.linspace(0.0, 1.0, n),
            "latitude": np.full(n, 45.0),
            "altitude": np.full(n, 11000.0),
            "time": pd.date_range("2025-07-09 12:00", periods=n, freq="1min"),
            "air_temperature": np.full(n, 220.0),
            "geopotential": np.full(n, 105000.0),
            "potential_vorticity": np.full(n, 2e-6),
            "nox_ei": np.full(n, 0.015),
            "fuel_burn": np.full(n, 40.0),
        }
    )
    return Flight(df)


@pytest.mark.parametrize(
    ("compute", "table"),
    [
        ("compute_o3", ACCF_SCALE_03),
        ("compute_ch4", ACCF_SCALE_CH4),
        ("compute_h2o", ACCF_SCALE_H2O),
    ],
)
def test_local_accf_accf_version_divides_by_version_scale(
    compute: str, table: dict[str, float]
) -> None:
    """Default scaling: the V1.0A divisor, as before (same operations)."""
    flight = _flight()
    got = getattr(_model(), compute)(flight)
    v1 = getattr(_model(accf_kwargs={"accf_v": "V1.0", "PMO": True}), compute)(flight)
    np.testing.assert_allclose(
        got * table["V1.0A"], v1 * table["V1.0"], rtol=1e-12, atol=0.0
    )


@pytest.mark.parametrize(
    ("compute", "species", "table"),
    [
        ("compute_o3", "O3", ACCF_SCALE_03),
        ("compute_ch4", "CH4", ACCF_SCALE_CH4),
        ("compute_h2o", "H2O", ACCF_SCALE_H2O),
    ],
)
def test_local_accf_new_scaling_replaces_version_scale(
    divisors_set: None, compute: str, species: str, table: dict[str, float]
) -> None:
    """The new divisor replaces ACCF_SCALE[V1.0A]; it is not applied on top."""
    flight = _flight()
    legacy = getattr(_model(), compute)(flight)
    new = getattr(_model(non_co2_scaling=NEW), compute)(flight)
    np.testing.assert_allclose(
        new, legacy * table["V1.0A"] / C_DIVISORS[species], rtol=1e-12, atol=0.0
    )


def test_local_accf_params_reject_placeholders(divisors_not_set: None) -> None:
    with pytest.raises(ACCFStepError, match="no Method C divisor yet"):
        LocalACCFParams(non_co2_scaling=NEW)


@pytest.mark.parametrize(
    ("divisors", "factor"),
    [
        (C_DIVISORS, 1.0),  # no PMO divisor: PMO uses the CH4 one
        ({**C_DIVISORS, "PMO": 8.0}, 20.0 / 8.0),
    ],
)
def test_local_accf_pmo_factor(
    monkeypatch: pytest.MonkeyPatch, divisors: dict[str, float], factor: float
) -> None:
    """PMO is 0.29 x CH4, scaled by its own divisor when it has one."""
    assert _model()._pmo_factor() == 1.0
    monkeypatch.setitem(
        non_co2_scaling._DIVISORS, NEW, {"C": divisors, "D": D_DIVISORS}
    )
    assert _model(non_co2_scaling=NEW)._pmo_factor() == pytest.approx(factor)


# ---------------------------------------------------------------------------
# Method C: gwp (RF backward factor)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("species", ["O3", "CH4", "PMO", "H2O"])
def test_gwp_rf_backward_is_one_under_new_scaling(species: str) -> None:
    legacy = GWPMetrics(params=GWPParams())._eagwp_spec_Wm2yr(species, 1e-12)
    new = GWPMetrics(params=GWPParams(non_co2_scaling=NEW))._eagwp_spec_Wm2yr(
        species, 1e-12
    )
    for h, value in legacy.items():
        assert new[h] == pytest.approx(
            value * RF_BACKWARD_FACTOR[species], rel=1e-12, abs=0.0
        )


# ---------------------------------------------------------------------------
# Method D: open_airclim AGWP attributes
# ---------------------------------------------------------------------------

_RESULTS = {
    h: {
        "O3": 1e-14 * h,
        "CH4": -2e-14 * h,
        "PMO": -6e-15 * h,
        "H2O": 3e-15 * h,
        "cont": 5e-14 * h,
    }
    for h in (20, 50, 100)
}


def test_agwp_attrs_accf_version_unchanged() -> None:
    attrs = _agwp_attrs(_RESULTS, (20, 50, 100), None)
    for h, by_sp in _RESULTS.items():
        for sp in ("O3", "CH4", "PMO", "H2O"):
            assert attrs[f"AGWP_{h}_{sp}"] == by_sp[sp]
        assert attrs[f"AGWP_{h}_CONT"] == by_sp["cont"]


def test_agwp_attrs_divided_except_contrails(divisors_set: None) -> None:
    divisors = non_co2_scaling_divisors(NEW, "D")
    attrs = _agwp_attrs(_RESULTS, (20, 50, 100), divisors)
    assert divisors is not None
    for h, by_sp in _RESULTS.items():
        for sp in ("O3", "CH4", "PMO", "H2O"):
            assert attrs[f"AGWP_{h}_{sp}"] == pytest.approx(
                by_sp[sp] / divisors[sp], rel=1e-12, abs=0.0
            )
        assert attrs[f"AGWP_{h}_CONT"] == by_sp["cont"]


def test_agwp_attrs_follow_horizons() -> None:
    attrs = _agwp_attrs(_RESULTS, (20,), None)
    assert set(attrs) == {f"AGWP_20_{sp}" for sp in ("O3", "CH4", "PMO", "H2O", "CONT")}


# ---------------------------------------------------------------------------
# Runner config
# ---------------------------------------------------------------------------


def test_runner_config_default_is_accf_version() -> None:
    assert RunnerConfig().non_co2_scaling == "accf_version"


def test_with_non_co2_scaling_sets_steps_and_copies_params() -> None:
    given = {"non_co2_model": {"accf_kwargs": {"accf_v": "V1.0", "PMO": True}}}
    cfg = RunnerConfig(params=given)
    out = with_non_co2_scaling(cfg)
    assert out.params["non_co2_model"]["non_co2_scaling"] == "accf_version"
    assert out.params["climate_impact"]["non_co2_scaling"] == "accf_version"
    # the caller's params are not changed
    assert given == {"non_co2_model": {"accf_kwargs": {"accf_v": "V1.0", "PMO": True}}}
    assert cfg.params is given


def test_with_non_co2_scaling_rejects_conflicting_step_param() -> None:
    cfg = RunnerConfig(params={"climate_impact": {"non_co2_scaling": NEW}})
    with pytest.raises(ValueError, match="differs from non_co2_scaling"):
        with_non_co2_scaling(cfg)


@pytest.mark.parametrize(
    ("non_co2_model", "match"),
    [
        ("local_accf", "no Method C divisor yet"),
        ("open_airclim", "no Method D divisor yet"),
        ("accf", "not supported by the 'accf'"),
    ],
)
def test_with_non_co2_scaling_fails_at_start_up(
    divisors_not_set: None, non_co2_model: str, match: str
) -> None:
    cfg = RunnerConfig(non_co2_model=non_co2_model, non_co2_scaling=NEW)
    with pytest.raises(Exception, match=match):
        with_non_co2_scaling(cfg)


def test_with_non_co2_scaling_accepts_set_divisors(divisors_set: None) -> None:
    for name in ("local_accf", "open_airclim"):
        out = with_non_co2_scaling(
            RunnerConfig(non_co2_model=name, non_co2_scaling=NEW)
        )
        assert out.params["non_co2_model"]["non_co2_scaling"] == NEW


def test_fleet_meta_data_reports_scaling() -> None:
    pytest.importorskip("pyBADA", reason="pyBADA required")
    from pyneats.runners.fleet import FleetRunner

    runner = FleetRunner.__new__(FleetRunner)
    runner.cfg = RunnerConfig()
    assert runner._fleet_meta_data()["non_co2_scaling"] == "accf_version"
