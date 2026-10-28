"""The fuel-burn guardrail also checks the operator fuel flow (audit A1).

When the aircraft operator (AO) provides fuel flow, engine efficiency and
aircraft mass, PyNEATS skips BADA and uses fuel_burn = fuel_flow x duration.
That path had no plausibility check, so a fuel flow sent in kg/h instead of
kg/s (3600 times too high) was accepted. The same guardrail as on the BADA
path now applies: total fuel <= fuel_burn_threshold x (MTOW - OEW). Its
rejection is final there: a BADA3 retry or the altitude fallback would take
the same path with the same operator fuel flow.
"""

from __future__ import annotations

import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from pyneats.steps.performance.protocol import PerformanceStepError
from tests.test_performance_retry_isolation import PLAUSIBLE_FUEL_FLOW
from tests.test_performance_retry_isolation import _make_df
from tests.test_performance_retry_isolation import _make_flight
from tests.test_performance_retry_isolation import _make_model


AO_ALL = {"ff", "ee", "am"}


def _model_with_ao_fuel_flow(fuel_flow: float):
    model, adapter = _make_model([], AO_ALL)
    df = _make_df(AO_ALL)
    df["fuel_flow"] = fuel_flow
    model._preprocess.return_value = df
    return model, adapter


def test_plausible_ao_fuel_flow_is_accepted() -> None:
    model, _adapter = _model_with_ao_fuel_flow(PLAUSIBLE_FUEL_FLOW)

    result = model.run(_make_flight())

    # 1 kg/s x 60 s x 4 segments; BADA was not run.
    assert result.dataframe["fuel_burn"].sum() == pytest.approx(240.0)
    model._choose_mass_strategy.assert_not_called()


def test_ao_fuel_flow_in_kg_per_hour_is_rejected_without_retry() -> None:
    # 1 kg/s sent as 3600 "kg/s": 864,000 kg against a limit of 42,000 kg.
    model, _adapter = _model_with_ao_fuel_flow(PLAUSIBLE_FUEL_FLOW * 3600)

    with pytest.raises(PerformanceStepError, match="kg/h") as exc_info:
        model.run(_make_flight())

    assert exc_info.value.retryable is False
    assert "864000 kg exceeds" in str(exc_info.value)
    # No BADA3 retry (one adapter resolution) and no altitude fallback.
    assert model._resolve_bada_adapter.call_count == 1
    model._run_with_altitude_fallback.assert_not_called()
    model._choose_mass_strategy.assert_not_called()


def test_ao_path_skips_guardrail_when_mtow_unknown() -> None:
    model, adapter = _model_with_ao_fuel_flow(PLAUSIBLE_FUEL_FLOW * 3600)
    adapter.MTOW = None

    result = model.run(_make_flight())

    assert result.dataframe["fuel_burn"].sum() == pytest.approx(864_000.0)
    model.logger.warning.assert_called()
