"""OpenAirClim (Method D) emits every flight in one reference year (audit O4).

The inventory year was the year of the first waypoint, while the metric start
year (``t_0``) and the result read back (``AGWP_{H}_2025``) were fixed at 2025
and the base inventory covers 2025 only. Every flight dated 2026 failed. Now
the inventory year, ``t_0``, ``time.range`` and the result key all use
``OpenAirClimParams.reference_year`` (``OPEN_AIRCLIM_REFERENCE_YEAR``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import toml


pytest.importorskip("openairclim", reason="openairclim required for Method D")

from pycontrails import Flight

from pyneats.core.neats_default_parameters import OPEN_AIRCLIM_REFERENCE_YEAR
from pyneats.steps.climate_functions import open_airclim
from pyneats.steps.climate_functions.open_airclim import OpenAirClimModel
from pyneats.steps.climate_functions.open_airclim import OpenAirClimParams
from pyneats.steps.climate_functions.open_airclim import _create_worker_toml


def _flight(start: str) -> Flight:
    """A 30-minute cruise at FL350 with per-segment emissions [kg]."""
    n = 31
    df = pd.DataFrame(
        {
            "longitude": np.linspace(2.0, 6.0, n),
            "latitude": np.linspace(48.0, 50.0, n),
            "altitude": np.full(n, 10668.0),
            "time": pd.date_range(start, periods=n, freq="1min"),
        }
    )
    df["air_pressure"] = 23842.0
    df["fuel_burn"] = 40.0
    df["co2"] = 40.0 * 3.159
    df["h2o"] = 40.0 * 1.23
    df["nox"] = 0.6
    return Flight(df, flight_id="TEST")


def test_default_reference_year() -> None:
    assert OPEN_AIRCLIM_REFERENCE_YEAR == 2025
    assert OpenAirClimParams().reference_year == OPEN_AIRCLIM_REFERENCE_YEAR


def test_worker_toml_uses_reference_year(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inputs").mkdir()
    path = _create_worker_toml(
        OpenAirClimParams().base_toml_path,
        "inputs",
        "outputs",
        "emissions.nc",
        100,
        2031,
    )
    config = toml.load(path)
    assert config["metrics"]["t_0"] == [2031]
    assert config["time"]["range"] == [2031, 2132, 1]


@pytest.mark.parametrize(
    "start", ["2024-12-31T23:40", "2025-07-09T10:00", "2026-03-01T10:00"]
)
def test_inventory_year_is_reference_year(start: str) -> None:
    flight = _flight(start)
    flight["segment_length"] = flight.segment_length()
    ds = OpenAirClimModel()._flight_to_inventory(flight)
    assert ds.attrs["Inventory_Year"] == OPEN_AIRCLIM_REFERENCE_YEAR


def _agwp(start: str, tmp_path: Path) -> dict[str, float]:
    # The flight has only the columns OpenAirClim needs, so skip the output view.
    model = OpenAirClimModel(tmp_base_dir_path=str(tmp_path))
    out = model.run(_flight(start))  # type: ignore[arg-type]
    return {k: v for k, v in out.attrs.items() if k.startswith("AGWP_")}


def test_flight_dated_2026_runs_and_equals_2025(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same flight gives the same result whatever its date."""
    monkeypatch.setattr(
        open_airclim.FlightWithGlobalAGWP, "from_flight", staticmethod(lambda f: f)
    )
    agwp_2025 = _agwp("2025-07-09T10:00", tmp_path)
    agwp_2026 = _agwp("2026-07-09T10:00", tmp_path)
    assert len(agwp_2025) == 12  # 3 horizons x O3, CH4, H2O, CONT
    assert all(np.isfinite(v) for v in agwp_2025.values())
    assert agwp_2026 == agwp_2025
