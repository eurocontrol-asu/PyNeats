"""A WARNING when the AO aircraft_mass overrides a different takeoff_mass (audit A6).

When the aircraft operator (AO) sends ``am`` (column ``aircraft_mass``), the
performance step uses it on every path and never reads ``takeoff_mass``
(attribute ``takeoff_weight``). That used to be logged at DEBUG only, and the
WARNING meant for this case could not be reached. Now one WARNING per flight
names the flight and both masses when they differ by more than
max(1000 kg, 2 % of the first aircraft_mass). A smaller difference stays at
DEBUG. No number changes, and the output attribute ``takeoff_weight`` still
shows the AO value.

The tests below the mocked ones run the real step from ``run`` down with the
BADA adapter mocked; the last test uses real BADA data and skips when the
model file is missing (the CI BADA data is a subset).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from pyneats.steps.performance.bada_model import BADAPerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError
from tests.test_performance_retry_isolation import FUEL_BURN_THRESHOLD
from tests.test_performance_retry_isolation import MTOW
from tests.test_performance_retry_isolation import OEW
from tests.test_performance_retry_isolation import _make_df
from tests.test_performance_retry_isolation import _make_flight


LOGGER_NAME = "tests.takeoff_mass_ignored"
AM0 = 70_000.0  # _make_df: aircraft_mass = 70,000 - 60 x i kg
THRESHOLD = max(1000.0, 0.02 * AM0)  # 1,400 kg
AO_FF = 1.0  # kg/s; plausible for the fuel-burn guardrail


def _bada(mass: float, *_: Any) -> tuple[float, float, str, str]:
    return 1e-5 * mass, 50_000.0, "Cruise", "TOTAL"


def _make_model(
    df: pd.DataFrame, failing_attempts: int = 0
) -> tuple[MagicMock, list[str]]:
    """Real performance step from ``run`` down; adapter and preprocessing mocked.

    The first ``failing_attempts`` attempts fail at their first BADA point
    (retryable), so the BADA3 retry and the altitude fallback run. Returns
    the model and the list of BADA versions of the attempts.
    """
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = logging.getLogger(LOGGER_NAME)
    for name in (
        "run",
        "run_by_bada_version",
        "_run_with_altitude_fallback",
        "_log_takeoff_mass_ignored",
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
        # getattr default: lets this file run against a dev without A6.
        method = getattr(BADAPerformanceModel, name, None)
        if method is not None:
            setattr(model, name, method.__get__(model))

    model.params = MagicMock()
    model.params.fuel_burn_threshold = FUEL_BURN_THRESHOLD
    model.params.reference_q_fuel = 43.13e6
    model.params.bada_type = MagicMock(return_value=(2, "A320", "A320-214", "ENG"))
    model.params.airspeed_stall_config = "TO"
    model.params.true_air_speed_smoothing_window = 7
    model.params.payload_factor = 1.0
    model.params.fuel_reserve_fraction = 0.15
    model.params.max_rel_mass_diff = 0.01
    model.params.max_mass_estimation_iter = 4
    model.params.max_consecutive_failures = 3
    model.params.ff_outlier_threshold = 10.0

    attempts: list[str] = []

    def resolve(
        icao: str, series: Any, engine_id: Any, force_bada3: bool = False
    ) -> tuple[Any, str, int, str]:
        version = "BADA3" if force_bada3 else "BADA4"
        attempts.append(version)
        adapter = MagicMock()
        adapter.MTOW = MTOW
        adapter.OEW = OEW
        adapter.MPL = MTOW - OEW
        adapter.nb_eng = 2
        adapter.span = 34.1
        adapter.bada_code = "A320"
        adapter.v_stall_cas = MagicMock(return_value=60.0)
        adapter.vmo_cas = MagicMock(return_value=180.06)
        if len(attempts) <= failing_attempts:
            adapter.thrust_fuel_segment = MagicMock(side_effect=RuntimeError("BADA"))
        else:
            adapter.thrust_fuel_segment = MagicMock(side_effect=_bada)
        return adapter, version, 2, "ENG"

    model._resolve_bada_adapter = MagicMock(side_effect=resolve)
    model._preprocess = MagicMock(side_effect=lambda _flight: df.copy())
    model._unsmoothed_true_airspeed = MagicMock(return_value=None)
    model._extract_aircraft_attrs = MagicMock(return_value=("A320", None, None, None))
    return model, attempts


def _df(ao: set[str]) -> pd.DataFrame:
    df = _make_df(ao)
    if "ff" in ao:
        df["fuel_flow"] = AO_FF
    return df


def _run(
    ao: set[str],
    failing_attempts: int = 0,
    df: pd.DataFrame | None = None,
    **attrs: Any,
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    model, attempts = _make_model(_df(ao) if df is None else df, failing_attempts)
    flight = _make_flight()
    flight.attrs.update(attrs)
    with patch(
        "pyneats.steps.performance.bada_model.filter_low_altitude_points",
        side_effect=lambda f: f,
    ):
        result = model.run(flight)
    return result.dataframe, dict(result.attrs), attempts


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER_NAME
        and r.levelno == logging.WARNING
        and "takeoff_mass" in r.getMessage()
    ]


@pytest.fixture(autouse=True)
def _capture(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)


# ---------------------------------------------------------------------------
# WARNING when the difference is large
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ao", [{"am"}, {"ff", "am"}, {"ff", "ee", "am"}])
@pytest.mark.parametrize("takeoff_mass", [AM0 - 8_000.0, AM0 + 8_000.0, 1_000_000.0])
def test_large_difference_warns_once(
    caplog: pytest.LogCaptureFixture, ao: set[str], takeoff_mass: float
) -> None:
    _run(ao, takeoff_weight=takeoff_mass)
    msgs = _warnings(caplog)
    assert len(msgs) == 1
    msg = msgs[0]
    assert "TEST1" in msg
    assert f"takeoff_mass {takeoff_mass:.0f} kg" in msg
    assert f"first aircraft_mass {AM0:.0f} kg" in msg
    assert "is not used because aircraft_mass is given" in msg
    assert "takeoff_weight still shows the AO value" in msg


def test_warning_text_ff_ee_am_early_exit(caplog: pytest.LogCaptureFixture) -> None:
    _run({"ff", "ee", "am"}, takeoff_weight=59_837.0)
    assert _warnings(caplog) == [
        "Flight TEST1: takeoff_mass 59837 kg is not used because aircraft_mass"
        " is given (first aircraft_mass 70000 kg, difference -10163 kg)."
        " The output attribute takeoff_weight still shows the AO value"
        " 59837 kg"
    ]


def test_first_finite_aircraft_mass_is_compared(
    caplog: pytest.LogCaptureFixture,
) -> None:
    df = _df({"ff", "ee", "am"})
    df.loc[0, "aircraft_mass"] = np.nan
    _run({"ff", "ee", "am"}, df=df, takeoff_weight=80_000.0)
    assert len(_warnings(caplog)) == 1
    assert "first aircraft_mass 69940 kg" in _warnings(caplog)[0]


# ---------------------------------------------------------------------------
# No WARNING
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "takeoff_mass",
    [AM0, AM0 - THRESHOLD, AM0 + THRESHOLD, AM0 - 1_000.0, AM0 + 300.0],
)
def test_within_threshold_debug_only(
    caplog: pytest.LogCaptureFixture, takeoff_mass: float
) -> None:
    _run({"am"}, takeoff_weight=takeoff_mass)
    assert _warnings(caplog) == []
    assert any(
        r.levelno == logging.DEBUG and "'takeoff_weight' attribute" in r.getMessage()
        for r in caplog.records
        if r.name == LOGGER_NAME
    )


def test_threshold_is_1000_kg_for_a_light_aircraft(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """2 % of 20,000 kg is 400 kg: the 1,000 kg floor applies."""
    df = _df({"am"})
    df["aircraft_mass"] = 20_000.0
    _run({"am"}, df=df, takeoff_weight=20_900.0)
    assert _warnings(caplog) == []
    _run({"am"}, df=df, takeoff_weight=21_100.0)
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize("ao", [{"am"}, {"ff", "ee", "am"}])
def test_no_takeoff_mass_no_warning(
    caplog: pytest.LogCaptureFixture, ao: set[str]
) -> None:
    _run(ao)
    _run(ao, takeoff_weight=None)
    assert _warnings(caplog) == []


@pytest.mark.parametrize("ao", [{"am"}, {"ff", "ee", "am"}])
@pytest.mark.parametrize("takeoff_mass", [np.nan, float("inf"), pd.NA])
def test_non_finite_takeoff_mass_no_warning(
    caplog: pytest.LogCaptureFixture, ao: set[str], takeoff_mass: Any
) -> None:
    _run(ao, takeoff_weight=takeoff_mass)
    assert _warnings(caplog) == []


def test_takeoff_mass_used_without_aircraft_mass_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without am, takeoff_mass is the initial mass: nothing is ignored."""
    df, _, _ = _run(set(), takeoff_weight=60_000.0)
    assert df["aircraft_mass"].iloc[0] == 60_000.0
    assert _warnings(caplog) == []


# ---------------------------------------------------------------------------
# Retries: one WARNING per flight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failing_attempts", "expected_attempts"),
    [
        (1, ["BADA4", "BADA3"]),
        (2, ["BADA4", "BADA3", "BADA4"]),
        (3, ["BADA4", "BADA3", "BADA4", "BADA3"]),
    ],
)
def test_warned_once_across_retries(
    caplog: pytest.LogCaptureFixture,
    failing_attempts: int,
    expected_attempts: list[str],
) -> None:
    _, _, attempts = _run(
        {"am"}, failing_attempts=failing_attempts, takeoff_weight=1_000_000.0
    )
    assert attempts == expected_attempts
    assert len(_warnings(caplog)) == 1


def test_warned_once_when_every_attempt_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(PerformanceStepError):
        _run({"am"}, failing_attempts=4, takeoff_weight=1_000_000.0)
    assert len(_warnings(caplog)) == 1


# ---------------------------------------------------------------------------
# A list engine_uid: one WARNING per flight, not per engine copy
# ---------------------------------------------------------------------------


def _engine_copy_attrs(n_engines: int) -> list[dict[str, Any]]:
    """Attrs of the engine copies made by FleetRunner for a list engine_uid."""
    from pyneats.runners.fleet import FleetRunner

    source = pd.DataFrame({"aircraft_mass": [AM0]})
    source.attrs = {
        "flight_id": "EJU1920",
        "arrival_airport": "LFML",
        "departure_airport": "LFPG",
        "aobt": "2023-01-01 10:00:00",
        "engine_uid": [f"ENG{i}" for i in range(n_engines)],
        "takeoff_weight": 1_000_000.0,
    }
    runner = MagicMock()
    runner.source_fleet = [source]
    runner.error_records = []
    FleetRunner._expand_multi_engine_sources(runner)
    return [dict(d.attrs) for d in runner.source_fleet]


@pytest.mark.parametrize("n_engines", [2, 3])
@pytest.mark.parametrize("ao", [{"am"}, {"ff", "ee", "am"}])
def test_list_engine_uid_warns_once_per_flight(
    caplog: pytest.LogCaptureFixture, n_engines: int, ao: set[str]
) -> None:
    copies = _engine_copy_attrs(n_engines)
    assert [a["flight_id"] for a in copies] == [
        f"EJU1920__eng{i}" for i in range(n_engines)
    ]
    for attrs in copies:
        _run(ao, **attrs)
    msgs = _warnings(caplog)
    assert len(msgs) == 1
    assert msgs[0].startswith("Flight EJU1920: takeoff_mass 1000000 kg is not used")
    # The other copies log the same message at DEBUG.
    debug = [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER_NAME
        and r.levelno == logging.DEBUG
        and r.getMessage().startswith("Flight EJU1920: takeoff_mass")
    ]
    assert len(debug) == n_engines - 1


def test_engine_copy_key_matches_fleet_runner() -> None:
    from pyneats.runners import fleet
    from pyneats.steps.performance import bada_model

    assert bada_model._MULTI_ENGINE_ORIG_FID_KEY == fleet._MULTI_ENGINE_ORIG_FID_KEY


# ---------------------------------------------------------------------------
# Numbers unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ao", [{"am"}, {"ff", "am"}, {"ff", "ee", "am"}])
@pytest.mark.parametrize("takeoff_mass", [AM0 + 500.0, AM0 - 8_000.0, 1_000_000.0])
def test_results_identical_with_and_without_takeoff_mass(
    ao: set[str], takeoff_mass: float
) -> None:
    ref_df, ref_attrs, _ = _run(ao)
    df, attrs, _ = _run(ao, takeoff_weight=takeoff_mass)
    pd.testing.assert_frame_equal(df, ref_df)
    # The output attribute still shows the AO value.
    assert attrs.pop("takeoff_weight") == takeoff_mass
    assert attrs == ref_attrs


@pytest.mark.requires_bada
def test_real_bada_results_identical_and_warned(
    bada_path: Path | None, caplog: pytest.LogCaptureFixture
) -> None:
    """Real step and BADA4 A320-214 data: same output, one WARNING."""
    from pycontrails import Flight

    from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
    from pyneats.steps.performance.bada_model import BADAPerformanceModelParams

    if bada_path is None:
        pytest.skip("BADA path not provided")
    root = bada_path / DEFAULT_BADA4_VERSION
    if not (root / "A320-214" / "A320-214.xml").is_file():
        pytest.skip(f"BADA4 model A320-214 not found under {root}")

    n = 30
    data = pd.DataFrame(
        {
            "time": pd.date_range("2023-01-01 10:00", periods=n, freq="1min"),
            "latitude": np.linspace(45.0, 46.0, n),
            "longitude": np.linspace(2.0, 4.0, n),
            "altitude": np.full(n, 10_000.0),
            "true_airspeed": np.full(n, 230.0),
            "air_temperature": np.full(n, 220.0),
            "specific_humidity": np.full(n, 1e-4),
            "u_wind": np.zeros(n),
            "v_wind": np.zeros(n),
            "aircraft_mass": AM0 - 40.0 * np.arange(n),
        }
    )
    attrs = {
        "aircraft_type": "A320",
        "flight_id": "REAL1",
        "departure_airport": "LFPG",
        "arrival_airport": "LFML",
        "model_type": "test",
        "aobt": "2023-01-01 10:00:00",
    }
    model = BADAPerformanceModel(
        params=BADAPerformanceModelParams(
            bada4_root_path=str(bada_path), bada3_root_path=str(bada_path)
        )
    )
    caplog.set_level(logging.DEBUG, logger=model.logger.name)

    ref = model(Flight(data=data.copy(), attrs=dict(attrs)))
    out = model(Flight(data=data.copy(), attrs={**attrs, "takeoff_weight": 1e6}))

    assert out.attrs["bada_version"] == "BADA4"
    pd.testing.assert_frame_equal(out.dataframe, ref.dataframe)
    assert out.attrs["takeoff_weight"] == 1e6
    msgs = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "takeoff_mass" in r.getMessage()
    ]
    assert len(msgs) == 1
    assert msgs[0].startswith("Flight REAL1: takeoff_mass 1000000 kg is not used")
