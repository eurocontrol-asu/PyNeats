"""The mass decreases with the operator fuel flow when the AO gives no mass (audit A13).

When the aircraft operator (AO) provides ``fuel_flow`` but no
``aircraft_mass``, the reported fuel and CO2 come from the AO fuel flow. The
mass profile used to decrease with the BADA fuel flow, and the initial mass
estimate used the BADA trip fuel, so mass[0] - mass[-1] did not match the
reported fuel. Now:

- TOM given: mass[0] = TOM, then mass decreases with the AO fuel flow.
- No TOM: mass[0] = min(MTOW, OEW + payload_factor x MPL + 1.15 x AO trip
  fuel), then mass decreases with the AO fuel flow.

The AO fuel flow is checked by the fuel-burn guardrail before it is
integrated, and that rejection is final. Flights with an AO mass, and flights
without an AO fuel flow, keep their behaviour. BADA is mocked: its fuel flow
is proportional to the mass, so a mass integrated with it is easy to tell
from one integrated with the AO fuel flow.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError
from tests.test_performance_retry_isolation import FUEL_BURN_THRESHOLD
from tests.test_performance_retry_isolation import MTOW
from tests.test_performance_retry_isolation import N_POINTS
from tests.test_performance_retry_isolation import OEW
from tests.test_performance_retry_isolation import _make_df
from tests.test_performance_retry_isolation import _make_flight


MPL = 20_000.0  # kg; ZFW = OEW + payload_factor x MPL
RESERVE = 0.15
SEGMENT_S = 60.0  # _make_df: 60 s segments, last one NaN
BADA_FF_PER_KG = 1e-5  # mocked BADA fuel flow [kg/s] per kg of mass
TOM = 70_000.0
# AO fuel flow [kg/s], about twice the mocked BADA one (0.65-0.70 kg/s).
AO_FF = np.array([1.5, 1.4, 1.3, 1.2, 1.1])
AO_FUEL = float((AO_FF[:-1] * SEGMENT_S).sum())  # 324 kg; last segment NaN


def _bada(mass: float, *_: Any) -> tuple[float, float, str, str]:
    return BADA_FF_PER_KG * mass, 50_000.0, "Cruise", "TOTAL"


def _make_model(df: pd.DataFrame) -> tuple[MagicMock, MagicMock]:
    """Real performance step from ``run`` down; adapter and preprocessing mocked."""
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    for name in (
        "run",
        "run_by_bada_version",
        "_early_exit_if_fuel_and_efficiency",
        "_derive_fuel_flow_from_mass_if_needed",
        "_choose_mass_strategy",
        "_performance_from_ao_fuel_flow",
        "_single_pass_performance",
        "_estimate_initial_mass_iterative",
        "_finalize_columns",
        "_build_result",
        "_check_total_fuel_burn",
        "_check_ao_fuel_flow",
        "_compute_engine_efficiency_if_missing",
        "_attach_output_attrs",
    ):
        setattr(model, name, getattr(BADAPerformanceModel, name).__get__(model))

    model.params = MagicMock()
    model.params.fuel_burn_threshold = FUEL_BURN_THRESHOLD
    model.params.reference_q_fuel = 43.13e6
    model.params.bada_type = MagicMock(return_value=(2, "A320", "A320-214", "ENG"))
    model.params.airspeed_stall_config = "TO"
    model.params.true_air_speed_smoothing_window = 7
    model.params.payload_factor = 1.0
    model.params.fuel_reserve_fraction = RESERVE
    model.params.max_rel_mass_diff = 0.01
    model.params.max_mass_estimation_iter = 4
    model.params.max_consecutive_failures = 3
    model.params.ff_outlier_threshold = 10.0

    adapter = MagicMock()
    adapter.MTOW = MTOW
    adapter.OEW = OEW
    adapter.MPL = MPL
    adapter.nb_eng = 2
    adapter.span = 34.1
    adapter.bada_code = "A320"
    adapter.v_stall_cas = MagicMock(return_value=60.0)
    adapter.vmo_cas = MagicMock(return_value=180.06)
    adapter.thrust_fuel_segment = MagicMock(side_effect=_bada)

    def resolve(
        icao: str, series: Any, engine_id: Any, force_bada3: bool = False
    ) -> tuple[Any, str, int, str]:
        return adapter, ("BADA3" if force_bada3 else "BADA4"), 2, "ENG"

    model._resolve_bada_adapter = MagicMock(side_effect=resolve)
    model._preprocess = MagicMock(return_value=df)
    model._unsmoothed_true_airspeed = MagicMock(return_value=None)
    model._extract_aircraft_attrs = MagicMock(return_value=("A320", None, None, None))
    model._run_with_altitude_fallback = MagicMock(
        side_effect=AssertionError("altitude fallback must not run")
    )
    return model, adapter


def _flight(**attrs: Any) -> MagicMock:
    flight = _make_flight()
    flight.attrs.update(attrs)
    return flight


def _ao_df(ao: set[str], fuel_flow: Any = AO_FF) -> pd.DataFrame:
    df = _make_df(ao)
    if "ff" in ao:
        df["fuel_flow"] = fuel_flow
    return df


def _run(df: pd.DataFrame, **attrs: Any) -> tuple[pd.DataFrame, MagicMock, MagicMock]:
    model, adapter = _make_model(df)
    result = model.run(_flight(**attrs))
    return result.dataframe, model, adapter


def _bada_masses(adapter: MagicMock) -> list[float]:
    return [c.args[0] for c in adapter.thrust_fuel_segment.call_args_list]


# ---------------------------------------------------------------------------
# (a) AO fuel flow + TOM
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ao", [{"ff"}, {"ff", "ee"}], ids=["ff", "ff_ee"])
def test_tom_mass_decreases_with_ao_fuel_flow(ao: set[str]) -> None:
    out, _model, adapter = _run(_ao_df(ao), takeoff_weight=TOM)

    mass = out["aircraft_mass"].to_numpy()
    assert mass[0] == TOM
    np.testing.assert_allclose(-np.diff(mass), AO_FF[:-1] * SEGMENT_S)
    assert mass[0] - mass[-1] == pytest.approx(AO_FUEL)
    # Reported fuel unchanged: AO fuel flow x duration.
    assert out["fuel_burn"].sum() == pytest.approx(AO_FUEL)
    np.testing.assert_allclose(out["fuel_flow"].to_numpy(), AO_FF)
    # BADA runs once, at the mass integrated from the AO fuel flow.
    np.testing.assert_allclose(_bada_masses(adapter), mass)


def test_tom_engine_efficiency_still_from_bada_fuel_flow() -> None:
    out, _model, _adapter = _run(_ao_df({"ff"}), takeoff_weight=TOM)

    # Unchanged rule: thrust x TAS / (BADA fuel flow x q_fuel), BADA at the new mass.
    bada_ff = BADA_FF_PER_KG * out["aircraft_mass"].to_numpy()
    expected = 50_000.0 * 230.0 / (bada_ff * 43.13e6)
    np.testing.assert_allclose(out["engine_efficiency"].to_numpy(), expected)


def test_empty_ao_fuel_flow_point_counts_as_zero() -> None:
    fuel_flow = AO_FF.copy()
    fuel_flow[2] = np.nan

    out, _model, _adapter = _run(_ao_df({"ff"}, fuel_flow), takeoff_weight=TOM)

    mass = out["aircraft_mass"].to_numpy()
    assert np.isfinite(mass).all()
    assert mass[2] - mass[3] == 0.0
    # Same total as the reported fuel (NaN skipped).
    assert mass[0] - mass[-1] == pytest.approx(out["fuel_burn"].sum())


def test_end_mass_below_oew_is_warned_not_clipped() -> None:
    out, model, _adapter = _run(_ao_df({"ff"}), takeoff_weight=OEW + 100.0)

    assert out["aircraft_mass"].iloc[-1] == pytest.approx(OEW + 100.0 - AO_FUEL)
    (call,) = model.logger.warning.call_args_list
    assert "below OEW" in call.args[0]
    assert call.args[1] == "TEST1"


# ---------------------------------------------------------------------------
# (b) AO fuel flow, no TOM
# ---------------------------------------------------------------------------


def test_initial_mass_from_ao_trip_fuel() -> None:
    out, _model, adapter = _run(_ao_df({"ff"}))

    mass = out["aircraft_mass"].to_numpy()
    expected_m0 = OEW + 1.0 * MPL + (1 + RESERVE) * AO_FUEL  # 65,372.6 kg < MTOW
    assert mass[0] == pytest.approx(expected_m0)
    assert mass[-1] == pytest.approx(expected_m0 - AO_FUEL)
    np.testing.assert_allclose(-np.diff(mass), AO_FF[:-1] * SEGMENT_S)
    # One BADA pass, no iteration: the trip fuel is known.
    assert adapter.thrust_fuel_segment.call_count == N_POINTS


def test_initial_mass_from_ao_trip_fuel_capped_at_mtow() -> None:
    # ZFW = 45,000 + 1.75 x 20,000 = 80,000 kg = MTOW.
    out, _model, _adapter = _run(_ao_df({"ff"}), payload_factor=1.75)

    mass = out["aircraft_mass"].to_numpy()
    assert mass[0] == MTOW
    assert mass[-1] == pytest.approx(MTOW - AO_FUEL)


def test_non_finite_payload_factor_uses_default_with_warning() -> None:
    # A NaN payload factor must not give min(MTOW, NaN) = MTOW silently.
    out, model, _adapter = _run(_ao_df({"ff"}), payload_factor=np.nan)

    expected_m0 = OEW + 1.0 * MPL + (1 + RESERVE) * AO_FUEL
    assert out["aircraft_mass"].iloc[0] == pytest.approx(expected_m0)
    (call,) = model.logger.warning.call_args_list
    assert "not finite" in call.args[0]
    assert call.args[1] == "TEST1"


# ---------------------------------------------------------------------------
# (c) AO mass provided: unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ao", [{"am"}, {"am", "ff"}], ids=["am", "am_ff"])
def test_ao_mass_is_used_as_given(ao: set[str]) -> None:
    df = _ao_df(ao)
    ao_mass = df["aircraft_mass"].to_numpy().copy()

    # TOM and payload factor are ignored when the AO gives the mass.
    out, _model, adapter = _run(df, takeoff_weight=TOM + 5_000.0, payload_factor=0.5)

    np.testing.assert_array_equal(out["aircraft_mass"].to_numpy(), ao_mass)
    np.testing.assert_array_equal(_bada_masses(adapter), ao_mass)


# ---------------------------------------------------------------------------
# (d) No AO fuel flow: unchanged (BADA integration, iterative estimate)
# ---------------------------------------------------------------------------


def test_no_ao_fuel_flow_tom_mass_decreases_with_bada_fuel_flow() -> None:
    out, _model, _adapter = _run(_ao_df(set()), takeoff_weight=TOM)

    mass = out["aircraft_mass"].to_numpy()
    expected = [TOM]
    for _ in range(N_POINTS - 1):
        expected.append(expected[-1] * (1 - BADA_FF_PER_KG * SEGMENT_S))
    np.testing.assert_allclose(mass, expected)
    np.testing.assert_allclose(
        out["fuel_flow"].to_numpy(), BADA_FF_PER_KG * np.array(expected)
    )


def test_no_ao_fuel_flow_iterative_estimate_with_bada_trip_fuel() -> None:
    out, _model, adapter = _run(_ao_df(set()))

    mass = out["aircraft_mass"].to_numpy()
    bada_fuel = float(out["fuel_burn"].sum())
    assert mass[0] - mass[-1] == pytest.approx(bada_fuel)
    # Iterative: one constant-mass pass, then passes until the 1 % criterion.
    assert adapter.thrust_fuel_segment.call_count == 2 * N_POINTS
    first_guess = OEW + 1.0 * (MTOW - OEW)
    first_trip = BADA_FF_PER_KG * first_guess * SEGMENT_S * (N_POINTS - 1)
    assert mass[0] == pytest.approx(OEW + MPL + (1 + RESERVE) * first_trip)


# ---------------------------------------------------------------------------
# (e) AO fuel flow in kg/h: rejected before the mass is integrated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ao", "attrs"),
    [({"ff"}, {"takeoff_weight": TOM}), ({"ff"}, {}), ({"ff", "ee"}, {})],
    ids=["ff_tom", "ff", "ff_ee"],
)
def test_ao_fuel_flow_in_kg_per_hour_rejected_without_retry(
    ao: set[str], attrs: dict[str, float]
) -> None:
    df = _ao_df(ao, AO_FF * 3600)
    model, adapter = _make_model(df)

    with pytest.raises(PerformanceStepError, match="kg/h") as exc_info:
        model.run(_flight(**attrs))

    assert exc_info.value.retryable is False
    assert f"{AO_FUEL * 3600:.0f} kg exceeds" in str(exc_info.value)
    # BADA never ran (no mass integrated), no BADA3 retry, no altitude fallback.
    adapter.thrust_fuel_segment.assert_not_called()
    assert model._resolve_bada_adapter.call_count == 1
    model._run_with_altitude_fallback.assert_not_called()
