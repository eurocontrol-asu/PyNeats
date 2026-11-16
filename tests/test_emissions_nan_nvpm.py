"""Constant nvPM fallback of the pycontrails emissions step.

pycontrails >= 0.63 estimates nvPM with SCOPE11 for engines with smoke numbers
but no nvPM data in the ICAO EDB. EDB v32 has no bypass ratio for PW4098
(5PW076) and JT9D (8PW086, 8PW087, 8PW088), so SCOPE11 gives NaN at every
waypoint. PyContrailsEmissionModel then uses the constant nvPM emission indices
of the pycontrails "Constant" route.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest
from pycontrails import Flight

import pyneats.steps.emissions.pycontrails_emissions as pe
from pyneats.steps.emissions import PyContrailsEmissionModel


NAN_NVPM_ENGINES = ("5PW076", "8PW086", "8PW087", "8PW088")
# Engine that pycontrails sends to the "Constant" route itself (no nvPM data,
# incomplete smoke numbers): the reference for the fallback values.
CONSTANT_ROUTE_ENGINE = "1IA001"


@pytest.fixture(autouse=True)
def _no_view_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cruise test flight has no performance columns: skip the view check."""
    monkeypatch.setattr(
        pe.FlightWithEmissions, "from_flight", classmethod(lambda cls, f: f)
    )


def _flight(engine_uid: str) -> Flight:
    n = 5
    data = pd.DataFrame(
        {
            "longitude": np.linspace(0.0, 1.0, n),
            "latitude": np.full(n, 48.0),
            "altitude": np.full(n, 11000.0),
            "time": pd.date_range("2025-07-09T10:00", periods=n, freq="1min"),
            "fuel_flow": np.full(n, 0.6),
            "true_airspeed": np.full(n, 230.0),
            "air_temperature": np.full(n, 218.0),
            "specific_humidity": np.full(n, 1e-5),
        }
    )
    return Flight(
        data, engine_uid=engine_uid, n_engine=4, aircraft_type="B742", flight_id="X"
    )


@pytest.mark.parametrize("engine_uid", NAN_NVPM_ENGINES)
def test_pycontrails_gives_all_nan_nvpm(engine_uid: str) -> None:
    """The case the fallback is for: pycontrails alone gives NaN nvPM."""
    raw = PyContrailsEmissionModel()._impl.eval(_flight(engine_uid))
    assert np.isnan(raw["nvpm_ei_n"]).all()
    assert np.isnan(raw["nvpm_ei_m"]).all()


@pytest.mark.parametrize("engine_uid", NAN_NVPM_ENGINES)
def test_fallback_gives_constant_nvpm(
    engine_uid: str, caplog: pytest.LogCaptureFixture
) -> None:
    model = PyContrailsEmissionModel()
    with caplog.at_level(logging.WARNING):
        out = model.run(_flight(engine_uid))
    ref = model.run(_flight(CONSTANT_ROUTE_ENGINE))
    assert ref.attrs["nvpm_data_source"] == "Constant"

    np.testing.assert_array_equal(out["nvpm_ei_n"], ref["nvpm_ei_n"])
    np.testing.assert_array_equal(out["nvpm_ei_m"], ref["nvpm_ei_m"])
    assert out.attrs["nvpm_data_source"] == (
        "Constant (fallback: ICAO EDB (SCOPE11 with T4/T2) gave NaN nvPM)"
    )
    assert out.attrs["engine_uid_used"] == engine_uid
    # nvPM segment values and totals recomputed from the new emission indices
    assert np.isfinite(out["nvpm_number"][:-1]).all()
    assert out.attrs["total_nvpm_number"] == pytest.approx(
        np.nansum(out["nvpm_number"])
    )
    assert out.attrs["total_nvpm_number"] > 0
    assert out.attrs["total_nvpm_mass"] > 0
    assert any(
        "nvPM emission indices are all NaN" in r.getMessage()
        and engine_uid in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.parametrize("engine_uid", NAN_NVPM_ENGINES)
def test_fallback_keeps_other_emissions(engine_uid: str) -> None:
    model = PyContrailsEmissionModel()
    raw = model._impl.eval(_flight(engine_uid))
    out = model.run(_flight(engine_uid))
    for col in ("nox_ei", "co_ei", "hc_ei", "co2", "h2o", "nox"):
        np.testing.assert_array_equal(out[col], raw[col])
    for key in ("total_co2", "total_h2o", "total_nox", "total_co", "total_hc"):
        assert out.attrs[key] == raw.attrs[key]


@pytest.mark.parametrize("engine_uid", ["2CM015", "3CM026"])
def test_no_fallback_for_finite_nvpm(
    engine_uid: str, caplog: pytest.LogCaptureFixture
) -> None:
    model = PyContrailsEmissionModel()
    raw = model._impl.eval(_flight(engine_uid))
    with caplog.at_level(logging.WARNING):
        out = model.run(_flight(engine_uid))
    np.testing.assert_array_equal(out["nvpm_ei_n"], raw["nvpm_ei_n"])
    assert out.attrs["nvpm_data_source"] == raw.attrs["nvpm_data_source"]
    assert not any("all NaN" in r.getMessage() for r in caplog.records)
