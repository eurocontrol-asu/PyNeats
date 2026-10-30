"""The AO takeoff_mass is range-checked against the BADA model (audit A6).

The aircraft operator (AO) ``takeoff_mass`` (flight attribute
``takeoff_weight``, kg) used to be taken as it came: 10,000 kg on an A330 or
999,999 kg on a B737-800 gave a result without a word. Now a finite
takeoff_mass below OEW or above 1.05 x MTOW of the BADA model of the first
attempt fails the flight, without a BADA3 retry or an altitude fallback. The
check runs before the early exit (AO fuel flow, engine efficiency and
aircraft mass), so it applies whether or not ``aircraft_mass`` is given. The
5 % margin keeps the golden UAE62Y B77W (takeoff_mass 2.0 % above the BADA4
MTOW 351,535 kg) valid. A missing, NaN, infinite or non-numeric takeoff_mass
is not checked.

The mocked tests run the real step from ``run`` down with the BADA adapter
mocked (OEW 45,000 kg, MTOW 80,000 kg). The real-BADA tests skip when the
model file is missing (the CI BADA data is a subset); the FleetRunner test
also needs weather data.
"""

from __future__ import annotations

import copy
import json
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
from tests.test_performance_retry_isolation import MTOW
from tests.test_performance_retry_isolation import OEW
from tests.test_performance_retry_isolation import _make_flight
from tests.test_takeoff_mass_ignored_warning import _df
from tests.test_takeoff_mass_ignored_warning import _make_model


UPPER = 1.05 * MTOW  # 84,000 kg
AO_CASES = [set(), {"am"}, {"ff"}, {"ff", "am"}, {"ff", "ee"}, {"ff", "ee", "am"}]
AO_IDS = ["none", "am", "ff", "ff+am", "ff+ee", "ff+ee+am"]


def _run(
    ao: set[str], failing_attempts: int = 0, **attrs: Any
) -> tuple[pd.DataFrame | None, list[str], PerformanceStepError | None, int]:
    """Run the mocked step; returns (df or None, attempts, error, fallback calls)."""
    model, attempts = _make_model(_df(ao), failing_attempts)
    flight = _make_flight()
    flight.attrs.update(attrs)
    with patch(
        "pyneats.steps.performance.bada_model.filter_low_altitude_points",
        side_effect=lambda f: f,
    ) as fallback:
        try:
            result = model.run(flight)
        except PerformanceStepError as e:
            return None, attempts, e, fallback.call_count
    return result.dataframe, attempts, None, fallback.call_count


# ---------------------------------------------------------------------------
# Out of range: the flight fails, without retry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ao", AO_CASES, ids=AO_IDS)
@pytest.mark.parametrize("takeoff_mass", [10_000.0, OEW - 1.0])
def test_below_oew_fails(ao: set[str], takeoff_mass: float) -> None:
    _, attempts, error, fallback_calls = _run(ao, takeoff_weight=takeoff_mass)
    assert error is not None
    assert not error.retryable
    assert attempts == ["BADA4"]
    assert fallback_calls == 0
    assert f"takeoff_mass {takeoff_mass:.0f} kg is below the OEW 45000 kg" in str(error)


@pytest.mark.parametrize("ao", AO_CASES, ids=AO_IDS)
@pytest.mark.parametrize("takeoff_mass", [UPPER + 1.0, 999_999.0])
def test_above_105_mtow_fails(ao: set[str], takeoff_mass: float) -> None:
    _, attempts, error, fallback_calls = _run(ao, takeoff_weight=takeoff_mass)
    assert error is not None
    assert not error.retryable
    assert attempts == ["BADA4"]
    assert fallback_calls == 0
    assert "above 1.05 x MTOW = 84000 kg (MTOW 80000 kg)" in str(error)


def test_error_text_below_oew() -> None:
    _, _, error, _ = _run({"ff", "ee", "am"}, takeoff_weight=10_000.0)
    assert str(error) == (
        "Flight TEST1: takeoff_mass 10000 kg is below the OEW 45000 kg of BADA"
        " model BADA4 A320. takeoff_mass must be the mass at take-off in kg"
    )


def test_error_text_above_mtow() -> None:
    _, _, error, _ = _run(set(), takeoff_weight=999_999.0)
    assert str(error) == (
        "Flight TEST1: takeoff_mass 999999 kg is above 1.05 x MTOW = 84000 kg"
        " (MTOW 80000 kg) of BADA model BADA4 A320. takeoff_mass must be the"
        " mass at take-off in kg"
    )


def test_numeric_string_is_checked() -> None:
    """The mass strategy converts the attribute with float(); so does the check."""
    _, _, error, _ = _run(set(), takeoff_weight="999999")
    assert error is not None
    assert not error.retryable


def test_no_retry_even_when_bada3_would_be_tried() -> None:
    """A retryable first-attempt failure goes to BADA3; a range failure does not."""
    _, attempts, error, _ = _run({"am"}, failing_attempts=1, takeoff_weight=70_000.0)
    assert error is None
    assert attempts == ["BADA4", "BADA3"]
    _, attempts, error, fallback_calls = _run(
        {"am"}, failing_attempts=1, takeoff_weight=999_999.0
    )
    assert error is not None
    assert attempts == ["BADA4"]
    assert fallback_calls == 0


def test_list_engine_uid_copy_names_the_ao_flight() -> None:
    _, _, error, _ = _run(
        {"am"},
        takeoff_weight=999_999.0,
        flight_id="EJU1920__eng1",
        _multi_engine_original_fid="EJU1920",
    )
    assert error is not None
    assert str(error).startswith("Flight EJU1920: takeoff_mass 999999 kg is above")


def _first_model_does_not_load(model: Any, attempts: list[str]) -> None:
    """Make the first BADA model of every non-forced attempt fail to load."""
    resolve = model._resolve_bada_adapter.side_effect

    def failing_resolve(
        icao: str, series: Any, engine_id: Any, force_bada3: bool = False
    ) -> tuple[Any, str, int, str]:
        if not force_bada3:
            attempts.append("BADA4 not loaded")
            raise ValueError("BADA4 model file not found")
        return resolve(icao, series, engine_id, force_bada3)

    model._resolve_bada_adapter.side_effect = failing_resolve


@pytest.mark.parametrize("ao", AO_CASES, ids=AO_IDS)
@pytest.mark.parametrize("takeoff_mass", [10_000.0, 999_999.0])
def test_checked_by_bada3_when_first_model_does_not_load(
    ao: set[str], takeoff_mass: float
) -> None:
    """The check runs with the first BADA model that loads (review of A6 PR 2)."""
    model, attempts = _make_model(_df(ao))
    _first_model_does_not_load(model, attempts)
    flight = _make_flight()
    flight.attrs["takeoff_weight"] = takeoff_mass
    with (
        patch(
            "pyneats.steps.performance.bada_model.filter_low_altitude_points",
            side_effect=lambda f: f,
        ) as fallback,
        pytest.raises(PerformanceStepError) as info,
    ):
        model.run(flight)
    assert not info.value.retryable
    assert attempts == ["BADA4 not loaded", "BADA3"]
    assert fallback.call_count == 0
    assert "of BADA model BADA3 A320." in str(info.value)


@pytest.mark.parametrize("ao", AO_CASES, ids=AO_IDS)
def test_in_range_passes_when_first_model_does_not_load(ao: set[str]) -> None:
    model, attempts = _make_model(_df(ao))
    _first_model_does_not_load(model, attempts)
    flight = _make_flight()
    flight.attrs["takeoff_weight"] = 70_000.0
    out = model.run(flight)
    assert attempts == ["BADA4 not loaded", "BADA3"]
    assert out.dataframe is not None


@pytest.mark.parametrize(
    ("first_error", "checked"),
    [("load", True), ("other", False)],
    ids=["model_not_loaded", "later_failure"],
)
def test_altitude_fallback_bada3_checks_only_after_load_failure(
    first_error: str, checked: bool
) -> None:
    """In the altitude fallback, the forced BADA3 attempt runs the check only
    when the non-forced attempt did not load its model."""
    from pyneats.steps.performance.bada_model import _BADAModelLoadError

    model, _ = _make_model(_df(set()))
    error = (
        _BADAModelLoadError("not loaded")
        if first_error == "load"
        else PerformanceStepError("BADA NaN")
    )
    expected = object()
    model.run_by_bada_version = MagicMock(side_effect=[error, expected])
    with patch(
        "pyneats.steps.performance.bada_model.filter_low_altitude_points",
        side_effect=lambda f: f,
    ):
        result = model._run_with_altitude_fallback(
            _make_flight(), "A320", None, None, None, PerformanceStepError("first")
        )
    assert result is expected
    second = model.run_by_bada_version.call_args_list[1]
    assert second.kwargs["force_bada3"] is True
    assert second.kwargs["check_takeoff_mass"] is checked


def test_error_text_never_shows_a_value_equal_to_its_bound() -> None:
    from pyneats.steps.performance.bada_model import _takeoff_mass_range_error

    assert _takeoff_mass_range_error(44_999.6, OEW, MTOW) == (
        "takeoff_mass 44999.6 kg is below the OEW 45000.0 kg"
    )
    assert _takeoff_mass_range_error(84_000.4, OEW, MTOW) == (
        "takeoff_mass 84000.4 kg is above 1.05 x MTOW = 84000.0 kg (MTOW 80000 kg)"
    )


# ---------------------------------------------------------------------------
# In range or not checked: unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ao", AO_CASES, ids=AO_IDS)
@pytest.mark.parametrize(
    "takeoff_mass",
    [OEW, 70_000.0, MTOW, 1.02 * MTOW, UPPER],
    ids=["OEW", "70t", "MTOW", "MTOW+2%", "MTOW+5%"],
)
def test_in_range_passes(ao: set[str], takeoff_mass: float) -> None:
    df, attempts, error, _ = _run(ao, takeoff_weight=takeoff_mass)
    assert error is None
    assert df is not None
    assert attempts == ["BADA4"]
    if "am" not in ao:
        # Without aircraft_mass, takeoff_mass is the initial mass.
        assert df["aircraft_mass"].iloc[0] == takeoff_mass


@pytest.mark.parametrize("ao", [{"am"}, {"ff", "am"}, {"ff", "ee", "am"}])
@pytest.mark.parametrize(
    "takeoff_mass",
    [None, np.nan, float("inf"), float("-inf"), pd.NA, "not a number"],
)
def test_missing_or_non_finite_not_checked(ao: set[str], takeoff_mass: Any) -> None:
    """With aircraft_mass, these values give the same result as no takeoff_mass."""
    ref, _, ref_error, _ = _run(ao)
    df, attempts, error, _ = _run(ao, takeoff_weight=takeoff_mass)
    assert ref_error is None
    assert error is None
    assert attempts == ["BADA4"]
    pd.testing.assert_frame_equal(df, ref)


@pytest.mark.parametrize(
    "takeoff_mass", [None, np.nan, float("inf"), pd.NA, "not a number"]
)
def test_range_error_helper_ignores_missing(takeoff_mass: Any) -> None:
    from pyneats.steps.performance.bada_model import _takeoff_mass_range_error

    assert _takeoff_mass_range_error(takeoff_mass, OEW, MTOW) is None


def test_range_error_helper_without_oew_or_mtow() -> None:
    from pyneats.steps.performance.bada_model import _takeoff_mass_range_error

    assert _takeoff_mass_range_error(1.0, None, MTOW) is None
    assert _takeoff_mass_range_error(1e9, OEW, None) is None


def test_no_aircraft_mass_without_takeoff_mass_unchanged() -> None:
    df, attempts, error, _ = _run(set())
    assert error is None
    assert df is not None
    assert attempts == ["BADA4"]


# ---------------------------------------------------------------------------
# Real BADA data (skips when the model file is missing)
# ---------------------------------------------------------------------------


def _real_model(bada_path: Path | None, code: str) -> BADAPerformanceModel:
    from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
    from pyneats.steps.performance.bada_model import BADAPerformanceModelParams

    if bada_path is None:
        pytest.skip("BADA path not provided")
    root = bada_path / DEFAULT_BADA4_VERSION
    if not (root / code / f"{code}.xml").is_file():
        pytest.skip(f"BADA4 model {code} not found under {root}")
    return BADAPerformanceModel(
        params=BADAPerformanceModelParams(
            bada4_root_path=str(bada_path), bada3_root_path=str(bada_path)
        )
    )


def _real_flight(takeoff_mass: float, with_am: bool) -> Any:
    from pycontrails import Flight

    n = 30
    data = pd.DataFrame(
        {
            "time": pd.date_range("2023-01-01 10:00", periods=n, freq="1min"),
            "latitude": np.linspace(45.0, 46.0, n),
            "longitude": np.linspace(2.0, 4.0, n),
            "altitude": np.full(n, 10_500.0),
            "true_airspeed": np.full(n, 250.0),
            "air_temperature": np.full(n, 220.0),
            "specific_humidity": np.full(n, 1e-4),
            "u_wind": np.zeros(n),
            "v_wind": np.zeros(n),
        }
    )
    if with_am:
        data["aircraft_mass"] = 300_000.0 - 100.0 * np.arange(n)
    attrs = {
        "aircraft_type": "B77W",
        "flight_id": "UAE62Y",
        "departure_airport": "OMDB",
        "arrival_airport": "EGLL",
        "model_type": "test",
        "aobt": "2023-01-01 10:00:00",
        "takeoff_weight": takeoff_mass,
    }
    return Flight(data=data, attrs=attrs)


# BADA4 B773ERGE115B: OEW 167,829 kg, MTOW 351,535 kg; 1.05 x MTOW = 369,111.75 kg.
@pytest.mark.requires_bada
@pytest.mark.parametrize("with_am", [False, True], ids=["no_am", "am"])
@pytest.mark.parametrize(
    "takeoff_mass",
    [167_829.0, 358_565.7, 369_111.75],
    ids=["OEW", "golden_UAE62Y_+2%", "edge_+5%"],
)
def test_real_b77w_in_range_passes(
    bada_path: Path | None, with_am: bool, takeoff_mass: float
) -> None:
    model = _real_model(bada_path, "B773ERGE115B")
    out = model(_real_flight(takeoff_mass, with_am))
    assert out.attrs["bada_version"] == "BADA4"
    assert out.attrs["takeoff_weight"] == takeoff_mass


@pytest.mark.requires_bada
@pytest.mark.parametrize("with_am", [False, True], ids=["no_am", "am"])
@pytest.mark.parametrize(
    ("takeoff_mass", "expected"),
    [
        (
            167_828.0,
            "Flight UAE62Y: takeoff_mass 167828 kg is below the OEW 167829 kg"
            " of BADA model BADA4 B773ERGE115B. takeoff_mass must be the mass"
            " at take-off in kg",
        ),
        (
            369_500.0,
            "Flight UAE62Y: takeoff_mass 369500 kg is above 1.05 x MTOW ="
            " 369112 kg (MTOW 351535 kg) of BADA model BADA4 B773ERGE115B."
            " takeoff_mass must be the mass at take-off in kg",
        ),
    ],
    ids=["below_OEW", "above_+5%"],
)
def test_real_b77w_out_of_range_fails(
    bada_path: Path | None,
    caplog: pytest.LogCaptureFixture,
    with_am: bool,
    takeoff_mass: float,
    expected: str,
) -> None:
    model = _real_model(bada_path, "B773ERGE115B")
    caplog.set_level(logging.INFO, logger=model.logger.name)
    with pytest.raises(PerformanceStepError) as info:
        model(_real_flight(takeoff_mass, with_am))
    assert str(info.value) == expected
    assert not info.value.retryable
    # No BADA3 retry, no altitude fallback.
    messages = [r.getMessage() for r in caplog.records]
    assert not any("BADA3 enforced" in m for m in messages)
    assert not any("altitude fallback" in m for m in messages)


@pytest.mark.requires_bada
@pytest.mark.parametrize("with_am", [False, True], ids=["no_am", "am"])
@pytest.mark.parametrize("takeoff_mass", [100_000.0, 999_999.0])
def test_real_checked_by_bada3_when_bada4_file_missing(
    bada_path: Path | None, tmp_path: Path, with_am: bool, takeoff_mass: float
) -> None:
    """A BADA root without the BADA4 B77W file: the BADA3 retry runs the check."""
    from pyneats.core.neats_default_parameters import DEFAULT_BADA3_VERSION
    from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
    from pyneats.steps.performance.bada_model import BADAPerformanceModelParams

    if bada_path is None:
        pytest.skip("BADA path not provided")
    bada3 = bada_path / DEFAULT_BADA3_VERSION
    if not (bada3 / "B77W__.OPF").is_file():
        pytest.skip(f"BADA3 model B77W__ not found under {bada3}")
    (tmp_path / DEFAULT_BADA4_VERSION).mkdir()
    (tmp_path / DEFAULT_BADA3_VERSION).symlink_to(bada3, target_is_directory=True)
    model = BADAPerformanceModel(
        params=BADAPerformanceModelParams(
            bada4_root_path=str(tmp_path), bada3_root_path=str(tmp_path)
        )
    )
    with pytest.raises(PerformanceStepError) as info:
        model(_real_flight(takeoff_mass, with_am))
    assert not info.value.retryable
    assert "of BADA model BADA3 B77W." in str(info.value)


# ---------------------------------------------------------------------------
# FleetRunner: the bad flight fails alone (needs BADA and weather)
# ---------------------------------------------------------------------------


GOLDEN_DIR = Path(__file__).parent / "data" / "golden"
GOLDEN_INPUT = GOLDEN_DIR / "fleet_5_flights_takeoff_mass_input.json"


@pytest.mark.integration
@pytest.mark.requires_weather
@pytest.mark.requires_bada
@pytest.mark.slow
def test_fleet_takeoff_mass_out_of_range_fails_alone(
    weather: Any, weather_path: Path | None, bada_path: Path | None, tmp_path: Path
) -> None:
    """The five golden takeoff_mass flights succeed; a copy of UAE62Y (B77W)
    with takeoff_mass 999,999 kg gives one error record."""
    from pyneats.runners.fleet import FleetRunnerParams
    from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
    from pyneats.steps.weather.weather_store import ZarrPaths

    if weather is None or weather_path is None:
        pytest.skip("Weather data not available")
    _real_model(bada_path, "B773ERGE115B")
    _real_model(bada_path, "A320-214")  # EAF2143 in the golden input

    with GOLDEN_INPUT.open(encoding="utf-8") as fh:
        flights: list[dict[str, Any]] = json.load(fh)
    (source,) = [
        f
        for f in flights
        if f["flight_information"]["flight_identification"] == "UAE62Y"
    ]
    bad = copy.deepcopy(source)
    bad["flight_information"]["flight_identification"] = "BADTOM"
    bad["flight_information"]["aircraft_properties"]["takeoff_mass"] = 999_999.0
    path = tmp_path / "input.json"
    path.write_text(json.dumps([*flights, bad]), encoding="utf-8")

    wind = weather_path / "icon_wind.zarr"
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(path),
        zarr_paths=ZarrPaths(
            weather_path / "icon_met.zarr",
            weather_path / "icon_rad.zarr",
            wind if wind.is_dir() else None,
        ),
        bada_path=str(bada_path),
        params={},
    )
    runner = FleetRunnerLargeEmitter(cfg)
    runner.eval()

    assert runner.fleet_with_climate_impact is not None
    assert sorted(f.attrs["flight_id"] for f in runner.fleet_with_climate_impact) == (
        sorted(f["flight_information"]["flight_identification"] for f in flights)
    )
    (record,) = runner.error_records
    assert record["flight_information"]["flight_id"] == "BADTOM"
    assert record["error"].startswith("Failed at performance")
    assert (
        "Flight BADTOM: takeoff_mass 999999 kg is above 1.05 x MTOW = 369112 kg"
        " (MTOW 351535 kg) of BADA model BADA4 B773ERGE115B" in record["error"]
    )
