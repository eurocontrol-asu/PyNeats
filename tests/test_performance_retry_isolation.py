"""A failed performance attempt must not leak columns into the retry.

``run()`` passes the same preprocessed DataFrame to the first attempt and to
the BADA3 retry (the altitude fallback does the same). ``run_by_bada_version``
writes ``aircraft_mass``, ``thrust``, ``fuel_flow``... before the fuel-burn
guardrail. Without a copy, a flight with AO fuel flow and engine efficiency
rejected by the guardrail on BADA4 reached the BADA3 retry with a BADA
``aircraft_mass`` column, took the "all AO data provided" early exit and was
accepted without the guardrail.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pandas as pd
import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError


N_POINTS = 5
MTOW = 80_000.0
OEW = 45_000.0
FUEL_BURN_THRESHOLD = 1.2  # limit = 1.2 x (MTOW - OEW) = 42,000 kg
AO_FUEL_FLOW = 200.0  # kg/s x 60 s x 4 segments = 48,000 kg > limit


def _make_df() -> pd.DataFrame:
    """Preprocessed flight with AO fuel flow and engine efficiency, no mass."""
    times = pd.date_range("2023-01-01 10:00", periods=N_POINTS, freq="1min")
    return pd.DataFrame(
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
            "fuel_flow": [AO_FUEL_FLOW] * N_POINTS,
            "engine_efficiency": [0.3] * N_POINTS,
            "u_wind": [0.0] * N_POINTS,
            "v_wind": [0.0] * N_POINTS,
            "air_temperature": [220.0] * N_POINTS,
            "specific_humidity": [1e-4] * N_POINTS,
        }
    )


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


def _make_model() -> MagicMock:
    """Real run / run_by_bada_version / early exit / finalize / guardrail;
    adapter resolution and the BADA calculation are mocked."""
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    for name in (
        "run",
        "run_by_bada_version",
        "_early_exit_if_fuel_and_efficiency",
        "_derive_fuel_flow_from_mass_if_needed",
        "_finalize_columns",
        "_build_result",
    ):
        setattr(model, name, getattr(BADAPerformanceModel, name).__get__(model))

    model.params = MagicMock()
    model.params.fuel_burn_threshold = FUEL_BURN_THRESHOLD
    model.params.reference_q_fuel = 43.13e6
    model.params.bada_type = MagicMock(return_value=(2, "A320", "A320-214", "ENG"))

    adapter = MagicMock()
    adapter.MTOW = MTOW
    adapter.OEW = OEW
    adapter.nb_eng = 2
    adapter.span = 34.1
    adapter.bada_code = "A320"

    def resolve(
        icao: str, series: Any, engine_id: Any, force_bada3: bool = False
    ) -> tuple[Any, str, int, str]:
        return adapter, ("BADA3" if force_bada3 else "BADA4"), 2, "ENG"

    model._resolve_bada_adapter = MagicMock(side_effect=resolve)
    model._choose_mass_strategy = MagicMock(
        return_value=(
            {
                "mass": [70_000.0] * N_POINTS,
                "fuel_flow": [1.0] * N_POINTS,
                "thrust": [50_000.0] * N_POINTS,
                "phase": ["Cruise"] * N_POINTS,
                "segment": ["TOTAL"] * N_POINTS,
            },
            43.13e6,
        )
    )
    model._compute_engine_efficiency_if_missing = MagicMock()
    model._run_with_altitude_fallback = MagicMock(
        side_effect=AssertionError("altitude fallback must not run")
    )
    return model


def _speed_filter_fails(*_: Any, **__: Any) -> pd.DataFrame:
    # As for BADA4 today: the filter raises and the step goes on unfiltered,
    # so the attempt works on the DataFrame it was given.
    raise TypeError("VStall signature")


@patch(
    "pyneats.steps.performance.bada_model.filter_low_speed_points",
    side_effect=_speed_filter_fails,
)
def test_attempt_does_not_modify_callers_dataframe(_: MagicMock) -> None:
    model = _make_model()
    df = _make_df()
    before = df.copy()
    flight = _make_flight()

    with pytest.raises(PerformanceStepError, match="fuel burn"):
        model.run_by_bada_version(flight, df, "A320", None, None, None)

    pd.testing.assert_frame_equal(df, before)


@patch(
    "pyneats.steps.performance.bada_model.filter_low_speed_points",
    side_effect=_speed_filter_fails,
)
def test_guardrail_rejection_not_bypassed_by_bada3_retry(_: MagicMock) -> None:
    model = _make_model()
    model._preprocess = MagicMock(return_value=_make_df())
    model._extract_aircraft_attrs = MagicMock(return_value=("A320", None, None, None))
    flight = _make_flight()

    with pytest.raises(PerformanceStepError, match="fuel burn"):
        model.run(flight)

    # Both attempts ran the BADA calculation: the BADA3 retry did not take
    # the "all AO data provided" early exit on columns left by BADA4.
    assert model._choose_mass_strategy.call_count == 2
    forced = [c.args[3] for c in model._resolve_bada_adapter.call_args_list]
    assert forced == [False, True]
