# conftest.py
from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Any, Mapping
import pandas as pd
import pytest
from _pytest.python import Metafunc
try:
    import yaml  # optional
except Exception:
    yaml = None

# ----------------------------------------------------------------------
# CLI options
# ----------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:

    g = parser.getgroup("pyneats")

    g.addoption("--traj-csv", action="store", default=None,
                help="Path to Flights_YYYYMMDD.csv (semicolon-separated, comma-decimal).")
    g.addoption("--model-type", action="store", default="CTFM",
                help="MODEL_TYPE to select (e.g., CTFM or FTFM). Default: CTFM.")

    g.addoption("--flight-id", action="append", default=None,
                help="AIRCRAFT_ID(s) to include (repeatable).")
    g.addoption("--adep", action="store", default=None, help="Filter by ADEP.")
    g.addoption("--ades", action="store", default=None, help="Filter by ADES.")
    g.addoption("--reg",  action="store", default=None, help="Filter by REGISTRATION.")
    g.addoption("--all-flights", action="store_true", default=False,
                help="Test all flights after filters.")
    g.addoption("--max-flights", type=int, default=None,
                help="Optional cap on number of flights tested.")

    g.addoption("--zarr-path", action="store", default=None,
                help="Base folder containing met_cache/icon_met.zarr, icon_rad.zarr, icon_wind.zarr (optional).")

    g.addoption("--asof", action="store", default=None,
                help='Weather window start, e.g. "2025-07-09 00:00:00".')
    g.addoption("--window-h", type=int, default=36,
                help="Forecast window in hours (default 36).")
    
    g.addoption("--expect", action="store", default=None,
                help="Path to JSON/YAML file with expected sums for metrics.")
    g.addoption("--rtol", type=float, default=0.03,
                help="Relative tolerance for numeric regression (default 3%).")
    g.addoption("--atol", type=float, default=0.0,
                help="Absolute tolerance for numeric regression (default 0).")

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _resolve_zarr_base(pytestconfig: pytest.Config) -> Path:
    zpath = pytestconfig.getoption("--zarr-path") or os.getenv("PYNEATS_ZARR_PATH")
    if not zpath:
        raise pytest.UsageError("Provide --zarr-path or set PYNEATS_ZARR_PATH.")
    p = Path(zpath)
    if not p.exists():
        raise FileNotFoundError(p)
    return p

def _read_csv(csv_path: Path, model_type: str) -> pd.DataFrame:

    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(
        csv_path,
        sep=";",
        decimal=",",
        dayfirst=True,
        #parse_dates=["TIME_OVER"],  # adjust if needed
        dtype={
            "AIRCRAFT_ID": "string",
            "ADEP": "string",
            "ADES": "string",
            "REGISTRATION": "string",
            "MODEL_TYPE": "string",
        },
    )
    df = df[df["MODEL_TYPE"].str.upper() == model_type.upper()].copy()
    for col in ["AIRCRAFT_ID", "ADEP", "ADES", "REGISTRATION"]:
        df[col] = df[col].astype("string").str.strip()
    return df

def _select_flights(
    df: pd.DataFrame,
    wanted_ids: list[str] | None,
    adep: Optional[str],
    ades: Optional[str],
    reg: Optional[str],
    all_flights: bool,
    max_flights: Optional[int],
) -> list[Mapping[str, Any]]:
    
    sel = pd.Series(True, index=df.index)
    if wanted_ids:
        sel &= df["AIRCRAFT_ID"].isin([str(x) for x in wanted_ids])
    if adep:
        sel &= df["ADEP"] == str(adep).strip()
    if ades:
        sel &= df["ADES"] == str(ades).strip()
    if reg:
        sel &= df["REGISTRATION"] == str(reg).strip()

    df_sel = df.loc[sel].copy()
    if df_sel.empty:
        return []

    keys = ["AIRCRAFT_ID", "ADEP", "ADES", "REGISTRATION"]
    groups = df_sel.groupby(keys, dropna=False, sort=False)

    # Build the list in a typed-friendly way
    cases: list[Mapping[str, Any]] = []
    for (fid, a, d, r), gdf in groups:
        cases.append({
            "flight_id": str(fid),
            "adep": str(a),
            "ades": str(d),
            "reg": str(r),
            "df": gdf.copy(),
        })

    # Apply sampling limits
    if not all_flights:
        limit = max_flights if max_flights is not None else 1
        cases = cases[:limit]
    elif max_flights is not None:
        cases = cases[:max_flights]

    return cases

def _load_expectations(path: Optional[str]) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.suffix.lower() in (".yml", ".yaml"):
        if yaml is None:
            raise RuntimeError("PyYAML not installed but a .yaml file was provided to --expect")
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return json.loads(p.read_text(encoding="utf-8"))

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture(scope="session")
def test_inputs(pytestconfig: pytest.Config) -> Mapping[str, Any]:

    csv_path = pytestconfig.getoption("--traj-csv") or os.getenv("PYNEATS_TRAJ_CSV")
    if not csv_path:
        raise pytest.UsageError("Provide --traj-csv or set PYNEATS_TRAJ_CSV.")
    csv_path = Path(csv_path)
    model_type = pytestconfig.getoption("--model-type") or "CTFM"

    df_model = _read_csv(csv_path, model_type)

    flights = _select_flights(
        df_model,
        pytestconfig.getoption("--flight-id") or [],
        pytestconfig.getoption("--adep"),
        pytestconfig.getoption("--ades"),
        pytestconfig.getoption("--reg"),
        pytestconfig.getoption("--all-flights"),
        pytestconfig.getoption("--max-flights"),
    )
    if not flights:
        raise pytest.UsageError(f"No {model_type} flights matched filters.")

    asof_str = pytestconfig.getoption("--asof") or "2025-07-09 00:00:00"
    asof = datetime.strptime(asof_str, "%Y-%m-%d %H:%M:%S")
    window_h = int(pytestconfig.getoption("--window-h"))
    t0 = asof.strftime("%Y-%m-%d %H:%M:%S")
    t1 = (asof + timedelta(hours=window_h)).strftime("%Y-%m-%d %H:%M:%S")

    zarr_base = _resolve_zarr_base(pytestconfig)
    met_store  = zarr_base / "met_cache" / "icon_met.zarr"
    rad_store  = zarr_base / "met_cache" / "icon_rad.zarr"
    wind_store = zarr_base / "met_cache" / "icon_wind.zarr"  # may not exist

    read_chunks_env = os.getenv("PYNEATS_READ_CHUNKS_JSON")
    read_chunks = json.loads(read_chunks_env) if read_chunks_env else {
        "time": 1, "level": 10, "latitude": 256, "longitude": 256
    }

    expectations = _load_expectations(pytestconfig.getoption("--expect"))
    rtol = float(pytestconfig.getoption("--rtol"))
    atol = float(pytestconfig.getoption("--atol"))


    output : Mapping[str, Any] = {
        "csv_path": csv_path,
        "model_type": model_type,
        "cases": flights,
        "zarr_paths": {
            "met_store": str(met_store),
            "rad_store": str(rad_store),
            "wind_store": str(wind_store) if wind_store.exists() else None,
        },
        "t0": t0,
        "t1": t1,
        "read_chunks": read_chunks,
        "expectations": expectations,
        "rtol": rtol,
        "atol": atol,
    }

    return output

# ----------------------------------------------------------------------
# Dynamic parametrization
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# Dynamic parametrization (robust: no fixture calls here)
# ----------------------------------------------------------------------
def pytest_generate_tests(metafunc: Metafunc) -> None:
    if "flight_case" not in metafunc.fixturenames:
        return

    # Pull options directly
    csv_path_opt = metafunc.config.getoption("--traj-csv") or os.getenv("PYNEATS_TRAJ_CSV")
    if not csv_path_opt:
        raise pytest.UsageError("Provide --traj-csv or set PYNEATS_TRAJ_CSV.")
    csv_path = Path(csv_path_opt)

    model_type = metafunc.config.getoption("--model-type") or "CTFM"

    df_model = _read_csv(csv_path, model_type)

    cases = _select_flights(
        df_model,
        metafunc.config.getoption("--flight-id") or [],
        metafunc.config.getoption("--adep"),
        metafunc.config.getoption("--ades"),
        metafunc.config.getoption("--reg"),
        bool(metafunc.config.getoption("--all-flights")),
        metafunc.config.getoption("--max-flights"),
    )
    if not cases:
        raise pytest.UsageError(f"No {model_type} flights matched filters.")

    ids = [f'{c["flight_id"]}-{c["adep"]}-{c["ades"]}-{c["reg"]}' for c in cases]
    metafunc.parametrize("flight_case", cases, ids=ids)