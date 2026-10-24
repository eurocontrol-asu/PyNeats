"""Airspeed trust step inside BADAPerformanceModel.run_by_bada_version.

The step runs after the BADA adapter is resolved and before every path (early
exit with AO data included). It removes no row and adds no column. A failure
in it ends the flight: non-retryable, so no BADA3 retry and no altitude
fallback. On the early-exit path (AO fuel flow, engine efficiency and aircraft
mass; no BADA fuel flow) the 80 % rule does not fail the flight.
"""

from __future__ import annotations

import pytest


# performance/__init__.py eagerly imports bada_adapters which requires pyBADA
pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pandas as pd
from pycontrails import Flight

from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError
from pyneats.steps.weather.weather_provider import FlightWithWeather


KT = 1852.0 / 3600.0  # m/s per kt
STALL_CAS = 70.0  # m/s, fake BADA stall CAS at MTOW
VMO_CAS = 350.0 * KT  # m/s, A320 BADA VMO (350 kt CAS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flight(
    speeds_kt: list[float], *, tas: list[float] | None = None
) -> FlightWithWeather:
    """Flight east along the equator at 3,000 m, 1 min per segment.

    ``tas`` [m/s], when given, is a provided (AO) ``true_airspeed`` column.
    """
    n = len(speeds_kt) + 1
    step_deg = np.degrees(np.asarray(speeds_kt) * KT * 60.0 / 6_371_229.0)
    data = {
        "longitude": np.concatenate([[0.0], np.cumsum(step_deg)]),
        "latitude": np.zeros(n),
        "altitude": np.full(n, 3_000.0),
        "time": pd.date_range("2025-07-09 08:00", periods=n, freq="1min"),
        "air_temperature": np.full(n, 268.65),  # ISA at 3,000 m
        "specific_humidity": np.full(n, 1e-3),
        "u_wind": np.full(n, 5.0),
        "v_wind": np.full(n, -3.0),
    }
    if tas is not None:
        data["true_airspeed"] = np.asarray(tas, dtype=float)
    flight = Flight(
        data=pd.DataFrame(data),
        attrs={
            "flight_id": "FL001",
            "aircraft_type": "A320",
            "departure_airport": "EGLL",
            "arrival_airport": "LFPG",
            "model_type": "NM",
            "aobt": "2025-07-09 08:00:00",
        },
    )
    return FlightWithWeather.from_flight(flight)


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.MTOW = 78_000.0
    adapter.OEW = 42_000.0
    adapter.v_stall_cas = MagicMock(return_value=STALL_CAS)
    adapter.vmo_cas = MagicMock(return_value=VMO_CAS)
    return adapter


def _make_model(adapter: MagicMock) -> MagicMock:
    """Real preprocessing and run_by_bada_version; BADA calculation stubbed.

    ``model.seen`` receives the DataFrame the BADA calculation was given.
    """
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    model.params = MagicMock()
    model.params.true_air_speed_smoothing_window = 7
    model.params.airspeed_stall_config = "TO"
    model.params.delta_tau_compute_method = "point"
    model.params.delta_tau_fill_method = "bffill"
    model.params.bada_type = MagicMock(return_value=(2, "A320", "A320-214", "ENG"))
    for name in (
        "run",
        "run_by_bada_version",
        "_preprocess",
        "_compute_ground_and_true_airspeed",
        "_compute_kinematics",
        "_compute_delta_tau",
        "_unsmoothed_true_airspeed",
        "_extract_aircraft_attrs",
        "_early_exit_if_fuel_and_efficiency",
    ):
        setattr(model, name, getattr(BADAPerformanceModel, name).__get__(model))

    model._resolve_bada_adapter = MagicMock(return_value=(adapter, "BADA4", 2, "ENG"))
    model.seen = []

    def choose(_adapter: Any, df: pd.DataFrame, *_: Any) -> tuple[Any, float]:
        model.seen.append(df.copy())
        return MagicMock(), 43.217e6

    model._derive_fuel_flow_from_mass_if_needed = MagicMock()
    model._choose_mass_strategy = MagicMock(side_effect=choose)
    model._finalize_columns = MagicMock()
    model._build_result = MagicMock(return_value=MagicMock(name="result"))
    model._run_with_altitude_fallback = MagicMock(
        side_effect=AssertionError("altitude fallback must not run")
    )
    return model


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unsmoothed_true_airspeed() -> None:
    model = _make_model(_make_adapter())
    flight = _make_flight([250.0] * 10)

    raw = model._unsmoothed_true_airspeed(flight)

    expected = flight.segment_true_airspeed(
        u_wind=np.full(11, 5.0), v_wind=np.full(11, -3.0), smooth=False
    )
    np.testing.assert_array_equal(raw, expected)
    assert np.isnan(raw[-1])
    # Provided (AO) TAS: no unsmoothed TAS, trust is decided on the provided one.
    assert (
        model._unsmoothed_true_airspeed(_make_flight([250.0] * 3, tas=[1.0] * 4))
        is None
    )


def test_trust_step_runs_before_bada_and_keeps_every_row() -> None:
    adapter = _make_adapter()
    model = _make_model(adapter)
    # A 3-min slow stretch (40 kt raw) inside a 250 kt flight.
    flight = _make_flight([250.0] * 10 + [40.0] * 3 + [250.0] * 10)
    df = model._preprocess(flight)
    smoothed = df["true_airspeed"].to_numpy().copy()

    model.run_by_bada_version(flight, df, "A320", None, None, None)

    (seen,) = model.seen
    assert len(seen) == len(df) == 24
    assert list(seen.columns) == list(df.columns)  # no column added
    assert smoothed[10:13].max() < 200.0 * KT  # smoothed slow stretch
    assert seen["true_airspeed"].min() > 240.0 * KT
    adapter.v_stall_cas.assert_called_once_with(78_000.0, "TO")
    # The caller's DataFrame is not modified.
    np.testing.assert_array_equal(df["true_airspeed"], smoothed)


def test_stall_config_parameter_is_used() -> None:
    adapter = _make_adapter()
    model = _make_model(adapter)
    model.params.airspeed_stall_config = "LD"
    flight = _make_flight([250.0] * 10)

    model.run_by_bada_version(
        flight, model._preprocess(flight), "A320", None, None, None
    )

    adapter.v_stall_cas.assert_called_once_with(78_000.0, "LD")


def test_clean_flight_reaches_bada_with_its_smoothed_tas() -> None:
    model = _make_model(_make_adapter())
    flight = _make_flight([240.0 + 3.0 * i for i in range(20)])
    df = model._preprocess(flight)

    model.run_by_bada_version(flight, df, "A320", None, None, None)

    (seen,) = model.seen
    np.testing.assert_array_equal(
        seen["true_airspeed"].to_numpy()[:-1], df["true_airspeed"].to_numpy()[:-1]
    )
    np.testing.assert_array_equal(seen["acceleration"], df["acceleration"])


def test_early_exit_path_gets_the_trusted_tas() -> None:
    # AO fuel flow, efficiency and mass: no BADA calculation, but the output
    # TAS (used by emissions and contrails) is the trusted one.
    model = _make_model(_make_adapter())
    flight = _make_flight([250.0] * 5 + [30.0] + [250.0] * 5)
    df = model._preprocess(flight)
    df["fuel_flow"] = 0.8
    df["engine_efficiency"] = 0.3
    df["aircraft_mass"] = 70_000.0

    with patch(
        "pyneats.steps.performance.bada_model.FlightWithPerformance.from_flight",
        side_effect=lambda f: f,
    ):
        out = model.run_by_bada_version(flight, df, "A320", None, None, None)

    model._choose_mass_strategy.assert_not_called()
    assert out["true_airspeed"][5] > 240.0 * KT


def _with_ao_fuel_and_efficiency(df: pd.DataFrame) -> pd.DataFrame:
    df["fuel_flow"] = 0.8  # kg/s
    df["engine_efficiency"] = 0.3
    df["aircraft_mass"] = 70_000.0  # kg
    return df


def test_early_exit_path_is_not_failed_by_the_80_percent_rule() -> None:
    # 9 of 10 minutes slow (90 % of the time untrusted): with AO fuel flow,
    # efficiency and mass the BADA fuel flow is not used, so the flight is
    # kept, with its TAS replaced, and no column is added to the output.
    model = _make_model(_make_adapter())
    flight = _make_flight([250.0] + [20.0] * 9)
    df = _with_ao_fuel_and_efficiency(model._preprocess(flight))
    columns = list(df.columns)
    model._preprocess = MagicMock(return_value=df)

    with patch(
        "pyneats.steps.performance.bada_model.FlightWithPerformance.from_flight",
        side_effect=lambda f: f,
    ):
        out = model.run(flight)

    model._choose_mass_strategy.assert_not_called()
    model._resolve_bada_adapter.assert_called_once()
    tas = np.asarray(out["true_airspeed"], dtype=float)
    assert tas.min() > 240.0 * KT  # the slow minutes take the trusted CAS
    assert set(out.dataframe.columns) == set(columns) | {"fuel_burn", "fuel"}


def test_partial_ao_data_still_fails_the_80_percent_rule() -> None:
    # Without engine efficiency, BADA computes the thrust (and efficiency):
    # not the early-exit path, so the rule applies.
    model = _make_model(_make_adapter())
    flight = _make_flight([250.0] + [20.0] * 9)
    df = _with_ao_fuel_and_efficiency(model._preprocess(flight))
    model._preprocess = MagicMock(return_value=df.drop(columns="engine_efficiency"))

    with pytest.raises(PerformanceStepError, match="Untrusted true airspeed") as exc:
        model.run(flight)

    assert not exc.value.retryable


def test_too_much_untrusted_time_fails_without_retry() -> None:
    model = _make_model(_make_adapter())
    flight = _make_flight([250.0] + [20.0] * 9)
    model._preprocess = MagicMock(return_value=model._preprocess(flight))

    with pytest.raises(PerformanceStepError, match="Untrusted true airspeed") as exc:
        model.run(flight)

    assert not exc.value.retryable
    model._resolve_bada_adapter.assert_called_once()  # no BADA3 retry
    model._choose_mass_strategy.assert_not_called()


def test_unexpected_error_in_the_step_fails_without_retry() -> None:
    adapter = _make_adapter()
    adapter.v_stall_cas = MagicMock(side_effect=TypeError("VStall signature"))
    model = _make_model(adapter)
    flight = _make_flight([250.0] * 10)
    model._preprocess = MagicMock(return_value=model._preprocess(flight))

    with pytest.raises(PerformanceStepError, match="Airspeed trust step failed") as exc:
        model.run(flight)

    assert not exc.value.retryable
    assert isinstance(exc.value.__cause__, TypeError)
    model._resolve_bada_adapter.assert_called_once()
    model._choose_mass_strategy.assert_not_called()
