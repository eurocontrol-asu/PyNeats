"""Tests for the Method D climate function (OpenAirClimModel, openairclim 0.20).

Runs openairclim end to end on a synthetic flight. Needs only the repository
data and the base inventory bundled in ``pyneats/resources``: no BADA, no
weather data, so the tests run in the CI matrix.

The configuration settings checked here were decided by Ramon + Philippe on
2026-10-28 (decisions A.1-A.5 in docs/internal/pyneats_units_audit.md).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import inspect
import os
import re
import textwrap
from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import toml
import xarray as xr
from pycontrails import Flight


pytest.importorskip("openairclim", reason="openairclim required for Method D")

from pyneats.steps.climate_functions.open_airclim import OAC_AIRCRAFT_ID
from pyneats.steps.climate_functions.open_airclim import OpenAirClimModel
from pyneats.steps.climate_functions.open_airclim import OpenAirClimParams
from pyneats.steps.climate_functions.open_airclim import _create_worker_toml
from pyneats.steps.climate_functions.protocol import OpenAirClimStepError
from pyneats.steps.climate_functions.views import FlightWithGlobalAGWP


OPENAIRCLIM_VERSION = "0.20.0"

# (AGWP_100_CH4 / AGWP_20_CH4) with CH4 including PMO, for the perturbation
# approach (resp_CH4_pert.nc) with a one-year pulse in 2025 and the SSP2-4.5
# background. It does not depend on the flight (the CH4 ODE is linear in the
# forcing): 1.2596 with openairclim 0.19.1 and 1.2602 with 0.20.0 for a
# production flight. The tagging approach gives about 1.44.
CH4_AGWP_100_OVER_20_REF = 1.2596

# Per-segment emissions of the synthetic flight [kg]; ~1 t fuel in total.
_FUEL_PER_SEGMENT_KG = 200.0
_EI_NOX = 0.012  # kg NOx (as NO2) / kg fuel
_EI_CO2 = 3.16
_EI_H2O = 1.23

SPECIES = ("O3", "CH4", "H2O", "CONT")
HORIZONS = (20, 50, 100)

_RESOURCES = files("pyneats.resources")
_BASE_TOML = Path(str(_RESOURCES.joinpath("openairclim.toml")))
_REPOSITORY = Path(str(_RESOURCES.joinpath("repository")))
_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _make_flight(
    scale: float = 1.0, n: int = 6, start: str = "2025-06-15T10:00:00"
) -> Flight:
    """Synthetic cruise flight (dated 2025 by default) with the columns Method D reads.

    Emission columns are scaled by ``scale``; everything else is fixed.
    Dummy weather/performance columns satisfy ``FlightWithGlobalAGWP``'s
    view requirements (openairclim does not use them).
    """
    t0 = pd.Timestamp(start, tz="UTC")
    data = {
        "longitude": np.linspace(2.0, 6.0, n),
        "latitude": np.linspace(44.0, 47.0, n),
        "altitude": np.full(n, 10500.0),
        "time": pd.date_range(t0, periods=n, freq="10min"),
        "air_pressure": np.full(n, 25000.0),  # Pa -> 250 hPa
        "fuel_burn": np.full(n, _FUEL_PER_SEGMENT_KG * scale),
        "nox": np.full(n, _FUEL_PER_SEGMENT_KG * _EI_NOX * scale),
        "co2": np.full(n, _FUEL_PER_SEGMENT_KG * _EI_CO2 * scale),
        "h2o": np.full(n, _FUEL_PER_SEGMENT_KG * _EI_H2O * scale),
        # view requirements (not used by openairclim)
        "nox_ei": np.full(n, _EI_NOX),
        "nvpm_ei_m": np.full(n, 1e-5),
        "true_airspeed": np.full(n, 230.0),
        "fuel_flow": np.full(n, 0.5),
        "engine_efficiency": np.full(n, 0.3),
        "aircraft_mass": np.full(n, 60000.0),
        "u_wind": np.zeros(n),
        "v_wind": np.zeros(n),
        "air_temperature": np.full(n, 220.0),
        "specific_humidity": np.full(n, 1e-5),
    }
    attrs = {
        "flight_id": f"SYN{scale:g}",
        "aircraft_type": "A320",
        "departure_airport": "LFPG",
        "arrival_airport": "LFML",
        "aobt": t0.isoformat(),
        "model_type": "synthetic",  # view requirement (FlightWithPerformance)
    }
    return Flight(data=data, attrs=attrs)


def _run(
    tmp_path, scale: float = 1.0, start: str = "2025-06-15T10:00:00", **overrides
) -> dict[str, float]:
    model = OpenAirClimModel(tmp_base_dir_path=str(tmp_path), **overrides)
    out = model.run(_make_flight(scale, start=start))
    assert isinstance(out, FlightWithGlobalAGWP)
    return {
        f"AGWP_{h}_{sp}": out.attrs[f"AGWP_{h}_{sp}"]
        for h in HORIZONS
        for sp in SPECIES
    }


# ---------------------------------------------------------------------------
# Version pin and upstream behaviour we rely on
# ---------------------------------------------------------------------------


def test_openairclim_version_is_pinned():
    """pyproject pins openairclim 0.20.0 and that version is installed."""
    deps = toml.loads(_PYPROJECT.read_text())["project"]["dependencies"]
    pins = [d for d in deps if re.match(r"openairclim\b", d)]
    assert pins == [f"openairclim=={OPENAIRCLIM_VERSION}"]
    assert importlib.metadata.version("openairclim") == OPENAIRCLIM_VERSION


def test_openairclim_ch4_solver_call_is_unchanged():
    """openairclim integrates the CH4 ODE with scipy's default tolerances.

    PyNEATS keeps openairclim's solver settings (no tolerance wrapper,
    decision Ramon + Philippe 2026-10-28). The accepted bias of AGWP_CH4 is
    about -0.3 % against tight tolerances. If a new openairclim release
    changes this call (tolerances, method, success check), this test fails so
    the decision can be re-checked.
    """
    from openairclim.core import calc_ch4

    src = textwrap.dedent(inspect.getsource(calc_ch4.calc_ch4_concentration))
    calls = [
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "solve_ivp"
    ]
    assert len(calls) == 1
    kwargs = {kw.arg: kw.value for kw in calls[0].keywords}
    assert set(kwargs) == {"method", "t_eval", "dense_output", "max_step", "args"}
    assert "rtol" not in kwargs and "atol" not in kwargs
    assert ast.literal_eval(kwargs["method"]) == "Radau"
    assert "success" not in src  # openairclim does not check solution.success
    assert calc_ch4.solve_ivp.__module__.startswith("scipy.")


# ---------------------------------------------------------------------------
# Configuration (decisions A.1-A.5)
# ---------------------------------------------------------------------------


def test_bundled_toml_leaves_attribution_to_library_default():
    """A.5: the shipped TOML does not set any ``attr`` key."""
    raw = toml.loads(_BASE_TOML.read_text())
    for spec in ("CO2", "CH4"):
        assert "attr" not in raw["responses"][spec].get("rf", {}), spec


def test_worker_toml_validates_against_openairclim_schema(tmp_path):
    """The TOML PyNEATS writes passes openairclim's validation and resolves
    to the decided settings."""
    from openairclim.core.config_model import validate_config

    os.makedirs(tmp_path / "inputs")
    path = _create_worker_toml(
        str(_BASE_TOML),
        str(tmp_path / "inputs"),
        str(tmp_path / "outputs"),
        "emissions.nc",
        100,
        2025,
        "ELK_aviation_2025_res5deg_flat.nc",
    )
    cfg = validate_config(toml.load(path))
    resp = cfg["responses"]
    # A.1 perturbation approach for O3 and CH4
    assert resp["O3"]["rf"]["approach"] == "perturbation"
    assert resp["CH4"]["tau"]["approach"] == "perturbation"
    assert resp["O3"]["rf"]["file"] == "resp_RF_O3_pert.nc"
    assert resp["CH4"]["tau"]["file"] == "resp_CH4_pert.nc"
    # A.2 NOx is NO2-equivalent
    assert cfg["species"]["nox"] == "NO2"
    # A.4 base inventory, no SWV
    assert cfg["inventories"]["rel_to_base"] is True
    assert cfg["inventories"]["base"]["files"] == ["ELK_aviation_2025_res5deg_flat.nc"]
    assert "SWV" not in cfg["species"]["out"]
    # A.5 attribution is the openairclim default, "proportional"
    assert resp["CH4"]["rf"]["attr"] == "proportional"
    assert resp["CO2"]["rf"]["attr"] == "proportional"
    # other settings openairclim 0.20 requires
    assert resp["H2O"]["rf"]["file"] == "resp_RF_H2O.nc"
    assert cfg["time"]["range"] == [2025, 2126, 1]
    for key in ("G_250", "b", "PMrel"):
        assert key in cfg["aircraft"]["DEFAULT"]


def test_default_params_use_bundled_base_inventory():
    """A.4: the default model runs relative to the bundled ELK 2025 base."""
    path = OpenAirClimParams().base_inventory_path
    assert path is not None
    assert os.path.basename(path) == "ELK_aviation_2025_res5deg_flat.nc"
    assert os.path.exists(path)


def test_bundled_repository_files_match_provenance():
    """Every file the TOML references exists, and every bundled .nc file has
    the MD5 recorded in PROVENANCE.txt (openairclim repository data 0.2.0)."""
    raw = toml.loads(_BASE_TOML.read_text())
    referenced = [raw["background"][s]["file"] for s in ("CO2", "CH4", "N2O")]
    resp = raw["responses"]
    referenced += [
        resp["H2O"]["rf"]["file"],
        resp["O3"]["rf"]["file"],
        resp["CH4"]["tau"]["file"],
        resp["cont"]["resp"]["file"],
    ]
    for name in referenced:
        assert (_REPOSITORY / name).is_file(), name

    recorded = dict(
        reversed(line.split())
        for line in (_REPOSITORY / "PROVENANCE.txt").read_text().splitlines()
        if re.fullmatch(r"[0-9a-f]{32}  \S+\.nc", line)
    )
    bundled = sorted(p.name for p in _REPOSITORY.glob("*.nc"))
    assert sorted(recorded) == bundled
    for name in bundled:
        md5 = hashlib.md5((_REPOSITORY / name).read_bytes()).hexdigest()
        assert md5 == recorded[name], name


# ---------------------------------------------------------------------------
# Numerics
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def agwp_by_scale(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("oac")
    return {s: _run(tmp, s) for s in (0.01, 1.0, 100.0)}


def test_agwp_signs_and_finiteness(agwp_by_scale):
    r = agwp_by_scale[1.0]
    for key, val in r.items():
        assert np.isfinite(val), key
    for h in HORIZONS:
        assert r[f"AGWP_{h}_O3"] > 0
        assert r[f"AGWP_{h}_H2O"] > 0
        assert r[f"AGWP_{h}_CH4"] < 0  # CH4 + PMO
        assert r[f"AGWP_{h}_CONT"] > 0


@pytest.mark.parametrize("species", ["O3", "CH4", "H2O"])
def test_agwp_scales_linearly_with_inventory(agwp_by_scale, species):
    """AGWP / scale is the same for x0.01, x1 and x100 inventories.

    With openairclim 0.13 the per-flight CH4 solution was dominated by
    integration noise (CH4_100/CH4_20 in -44..12 across production flights).
    """
    ref = {h: agwp_by_scale[1.0][f"AGWP_{h}_{species}"] for h in HORIZONS}
    for scale, res in agwp_by_scale.items():
        for h in HORIZONS:
            assert res[f"AGWP_{h}_{species}"] / scale == pytest.approx(
                ref[h], rel=1e-4
            ), (species, h, scale)


def test_ch4_agwp_horizon_ratio_matches_reference(agwp_by_scale):
    for scale, res in agwp_by_scale.items():
        ratio = res["AGWP_100_CH4"] / res["AGWP_20_CH4"]
        assert ratio == pytest.approx(CH4_AGWP_100_OVER_20_REF, rel=1e-2), scale


def test_contrail_agwp_is_per_flight_not_base_fleet(agwp_by_scale):
    """With rel_to_base, openairclim's own metrics file reports the base
    fleet plus the flight ("TOTAL", ~5e-2 W m-2 yr); PyNEATS must report the
    flight's share (~1e-9 W m-2 yr for a ~1 t fuel flight)."""
    r = agwp_by_scale[1.0]
    assert r["AGWP_20_CONT"] < 1e-6
    assert r["AGWP_20_CONT"] == pytest.approx(r["AGWP_100_CONT"])  # one-year pulse


def test_harvest_matches_openairclim_agwp_without_base(tmp_path, monkeypatch):
    """Without a base inventory "TOTAL" is the flight alone, so the AGWP
    integrated by ``_harvest_agwp`` equals openairclim's own metrics file."""
    import pyneats.steps.climate_functions.open_airclim as oac_mod

    captured: dict[str, dict] = {}
    original = oac_mod._harvest_agwp

    def _spy(results_nc, t_0, horizons, ac=OAC_AIRCRAFT_ID):
        out = original(results_nc, t_0, horizons, ac)
        metrics = xr.load_dataset(results_nc.replace(".nc", "_metrics.nc"))
        captured["ours"] = out
        captured["oac"] = {
            h: dict(
                zip(
                    metrics[f"AGWP_{h}_{t_0}"]["species"].values.astype(str),
                    metrics[f"AGWP_{h}_{t_0}"].values.astype(float),
                )
            )
            for h in horizons
        }
        return out

    monkeypatch.setattr(oac_mod, "_harvest_agwp", _spy)
    _run(tmp_path, 1.0, base_inventory_path=None)
    for h in HORIZONS:
        for sp in ("CO2", "O3", "CH4", "PMO", "H2O", "cont"):
            assert captured["ours"][h][sp] == pytest.approx(
                captured["oac"][h][sp], rel=1e-5
            ), (h, sp)


# ---------------------------------------------------------------------------
# Base inventory and reference year (audit O4) on openairclim 0.20
# ---------------------------------------------------------------------------


def test_missing_base_inventory_raises(tmp_path):
    """A configured base inventory that does not exist is an error naming the
    path, not a silent run without the base (which changes contrails)."""
    missing = tmp_path / "no_such_base_inventory.nc"
    model = OpenAirClimModel(
        tmp_base_dir_path=str(tmp_path), base_inventory_path=str(missing)
    )
    with pytest.raises(OpenAirClimStepError, match=re.escape(str(missing))):
        model.run(_make_flight())


def test_flight_dated_2026_runs_and_equals_2025(tmp_path):
    """With the decided 0.20 setup (base inventory ELK 2025, perturbation,
    NO2) a flight dated 2026 runs and gives the same values as the same
    flight dated 2025: both are emitted in the reference year."""
    agwp_2025 = _run(tmp_path, 1.0, start="2025-07-09T10:00:00")
    agwp_2026 = _run(tmp_path, 1.0, start="2026-07-09T10:00:00")
    assert all(np.isfinite(v) for v in agwp_2025.values())
    assert agwp_2026 == agwp_2025
