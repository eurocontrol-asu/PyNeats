"""Retries in the performance step: clean start, and fuel-burn rejections.

``run()`` passes the same preprocessed DataFrame to the first attempt and to
the BADA3 retry (the altitude fallback does the same). ``run_by_bada_version``
writes ``aircraft_mass``, ``thrust``, ``fuel_flow``... into it. Without a copy,
the BADA3 retry took the columns left by a failed BADA4 attempt as AO data:
with AO fuel flow and engine efficiency it saw "all AO data provided", took
the early exit and was accepted without the fuel-burn guardrail.

Each attempt now works on its own copy. A fuel-burn rejection goes through the
whole fallback chain: BADA3 retry, then altitude fallback.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError


N_POINTS = 5
MTOW = 80_000.0
OEW = 45_000.0
FUEL_BURN_THRESHOLD = 1.2  # limit = 1.2 x (MTOW - OEW) = 42,000 kg
IMPOSSIBLE_FUEL_FLOW = 200.0  # kg/s x 60 s x 4 segments = 48,000 kg > limit
PLAUSIBLE_FUEL_FLOW = 1.0  # kg/s


def _make_df(ao: set[str]) -> pd.DataFrame:
    """Preprocessed flight; ``ao`` names the AO columns: ff, ee, am."""
    times = pd.date_range("2023-01-01 10:00", periods=N_POINTS, freq="1min")
    df = pd.DataFrame(
        {
            "latitude": [51.5 + i * 0.1 for i in range(N_POINTS)],
            "longitude": [-0.1 + i * 0.1 for i in range(N_POINTS)],
            "time": times,
            "altitude": [10_000.0] * N_POINTS,
            "true_airspeed": [230.0] * N_POINTS,
            "rocd": [0.0] * N_POINTS,
            "acceleration": [0.0] * N_POINTS,
            "delta_tau": [0.0] * N_POINTS,
            "segment_duration": [60.0] * (N_POINTS - 1) + [float("nan")],
            "u_wind": [0.0] * N_POINTS,
            "v_wind": [0.0] * N_POINTS,
            "air_temperature": [220.0] * N_POINTS,
            "specific_humidity": [1e-4] * N_POINTS,
        }
    )
    if "ff" in ao:
        df["fuel_flow"] = IMPOSSIBLE_FUEL_FLOW
    if "ee" in ao:
        df["engine_efficiency"] = 0.3
    if "am" in ao:
        df["aircraft_mass"] = [70_000.0 - 60.0 * i for i in range(N_POINTS)]
    return df


def _make_flight() -> MagicMock:
    flight = MagicMock()
    flight.attrs = {
        "aircraft_type": "A320",
        "flight_id": "TEST1",
        "departure_airport": "EGLL",
        "arrival_airport": "LFPG",
        "model_type": "test",
        "aobt": "2023-01-01 10:00:00",
    }
    flight.fuel = None
    return flight


def _perf(fuel_flow: float) -> tuple[dict[str, list[Any]], float]:
    return (
        {
            "mass": [70_000.0] * N_POINTS,
            "fuel_flow": [fuel_flow] * N_POINTS,
            "thrust": [50_000.0] * N_POINTS,
            "phase": ["Cruise"] * N_POINTS,
            "segment": ["TOTAL"] * N_POINTS,
        },
        43.13e6,
    )


def _make_model(bada_results: list[Any], ao: set[str]) -> tuple[MagicMock, MagicMock]:
    """Real run / run_by_bada_version / early exit / finalize / guardrail.

    Adapter resolution and the BADA calculation are mocked: each attempt that
    reaches the BADA calculation takes the next item of ``bada_results`` (a
    BADA fuel flow in kg/s, or an exception to raise).
    """
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    for name in (
        "run",
        "run_by_bada_version",
        "_early_exit_if_fuel_and_efficiency",
        "_derive_fuel_flow_from_mass_if_needed",
        "_finalize_columns",
        "_build_result",
        "_check_total_fuel_burn",
        "_check_ao_fuel_flow",
        "_attach_output_attrs",
    ):
        setattr(model, name, getattr(BADAPerformanceModel, name).__get__(model))

    model.params = MagicMock()
    model.params.fuel_burn_threshold = FUEL_BURN_THRESHOLD
    model.params.reference_q_fuel = 43.13e6
    model.params.bada_type = MagicMock(return_value=(2, "A320", "A320-214", "ENG"))
    model.params.airspeed_stall_config = "TO"
    model.params.true_air_speed_smoothing_window = 7

    adapter = MagicMock()
    adapter.MTOW = MTOW
    adapter.OEW = OEW
    adapter.nb_eng = 2
    adapter.span = 34.1
    adapter.bada_code = "A320"
    # The real airspeed trust step runs; every point of _make_df is trusted
    # (TAS 230 m/s at 10,000 m: CAS about 135 m/s, Mach 0.77), so the
    # attempt keeps the TAS it was given.
    adapter.v_stall_cas = MagicMock(return_value=60.0)
    adapter.vmo_cas = MagicMock(return_value=180.06)  # m/s CAS (A320, 350 kt)

    def resolve(
        icao: str, series: Any, engine_id: Any, force_bada3: bool = False
    ) -> tuple[Any, str, int, str]:
        return adapter, ("BADA3" if force_bada3 else "BADA4"), 2, "ENG"

    model._resolve_bada_adapter = MagicMock(side_effect=resolve)
    model._choose_mass_strategy = MagicMock(
        side_effect=[r if isinstance(r, Exception) else _perf(r) for r in bada_results]
    )

    def efficiency(df: pd.DataFrame, perf: Any, q_fuel_used: float) -> None:
        # As the real step: fill engine_efficiency only when it is absent.
        if "engine_efficiency" not in df.columns:
            df["engine_efficiency"] = 0.3

    model._compute_engine_efficiency_if_missing = MagicMock(side_effect=efficiency)
    model._preprocess = MagicMock(return_value=_make_df(ao))
    # The fixture provides true_airspeed, as an AO TAS: no unsmoothed TAS.
    model._unsmoothed_true_airspeed = MagicMock(return_value=None)
    model._extract_aircraft_attrs = MagicMock(return_value=("A320", None, None, None))
    model._run_with_altitude_fallback = MagicMock(
        side_effect=AssertionError("altitude fallback must not run")
    )
    return model, adapter


def test_attempt_does_not_modify_callers_dataframe() -> None:
    model, _adapter = _make_model([PLAUSIBLE_FUEL_FLOW], {"ff", "ee"})
    df = _make_df({"ff", "ee"})
    before = df.copy()

    with pytest.raises(PerformanceStepError, match="fuel burn"):
        model.run_by_bada_version(_make_flight(), df, "A320", None, None, None)

    pd.testing.assert_frame_equal(df, before)


@pytest.mark.parametrize("ao", [set(), {"ee"}], ids=["no_ao", "ao_ee"])
def test_guardrail_rejection_retried_with_bada3(ao: set[str]) -> None:
    # BADA4 fuel is impossible, BADA3 fuel is plausible: the flight is
    # accepted with BADA3. Before the fix, the BADA3 retry reused the rejected
    # BADA4 columns (rejected again, or accepted via the early exit with "ee").
    model, _adapter = _make_model([IMPOSSIBLE_FUEL_FLOW, PLAUSIBLE_FUEL_FLOW], ao)

    result = model.run(_make_flight())

    forced = [c.args[3] for c in model._resolve_bada_adapter.call_args_list]
    assert forced == [False, True]
    assert model._choose_mass_strategy.call_count == 2
    assert result.attrs["bada_version"] == "BADA3"
    model._run_with_altitude_fallback.assert_not_called()


def test_guardrail_rejection_reaches_altitude_fallback() -> None:
    # BADA4 and BADA3 fuel are both impossible: both are rejected, then the
    # altitude fallback runs. Before the fix, the BADA3 retry saw the BADA4
    # fuel flow and mass + the AO efficiency, skipped the guardrail and
    # accepted the flight. (An impossible AO fuel flow is now rejected without
    # retry: tests/test_mass_from_ao_fuel_flow.py.)
    model, _adapter = _make_model([IMPOSSIBLE_FUEL_FLOW, IMPOSSIBLE_FUEL_FLOW], {"ee"})
    fallback_result = MagicMock(name="altitude fallback result")
    model._run_with_altitude_fallback = MagicMock(return_value=fallback_result)

    result = model.run(_make_flight())

    assert result is fallback_result
    forced = [c.args[3] for c in model._resolve_bada_adapter.call_args_list]
    assert forced == [False, True]
    assert model._choose_mass_strategy.call_count == 2
    (call,) = model._run_with_altitude_fallback.call_args_list
    assert "fuel burn" in str(call.args[-1])


def test_retry_after_bada4_failure_starts_clean() -> None:
    # AO mass and efficiency. BADA4 fails (retryable) after the fuel flow was
    # derived from the mass. Before the fix, the BADA3 retry saw that derived
    # fuel flow as AO data, skipped BADA and returned no bada_version.
    model, _adapter = _make_model(
        [PerformanceStepError("BADA4 failure"), PLAUSIBLE_FUEL_FLOW], {"am", "ee"}
    )

    result = model.run(_make_flight())

    forced = [c.args[3] for c in model._resolve_bada_adapter.call_args_list]
    assert forced == [False, True]
    assert model._choose_mass_strategy.call_count == 2
    assert result.attrs["bada_version"] == "BADA3"
