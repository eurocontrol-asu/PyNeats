"""REFERENCE_Q_FUEL is the fuel LHV that BADA4 assumes (audit A11/A12).

pyBADA computes BADA4 fuel flow as energy flow / LHV of the aircraft file, so the
rescaling to the actual fuel, BADA fuel flow x REFERENCE_Q_FUEL / q_fuel, needs
REFERENCE_Q_FUEL equal to that LHV. Every BADA4 model reachable through the
PyNEATS mapping tables must declare it; a BADA4 release with another value fails
here. BADA3 declares no LHV and uses the same reference (maintainer decision).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import pyneats
from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
from pyneats.core.neats_default_parameters import REFERENCE_Q_FUEL
from pyneats.steps.performance.bada_adapters import BADA4Adapter
from pyneats.steps.performance.bada_model import BADAPerformanceModelParams


RESOURCES = Path(pyneats.__file__).parent / "resources"


def _mapped_bada4_codes() -> set[str]:
    codes: set[str] = set()
    for table in RESOURCES.glob("*.csv"):
        df = pd.read_csv(table, dtype=str)
        if "BADA4" in df.columns:
            codes |= set(df["BADA4"].dropna().str.strip())
    return codes - {""}


def test_reference_is_the_bada4_lhv_and_the_model_default() -> None:
    assert REFERENCE_Q_FUEL == 43_217_000.0
    assert BADAPerformanceModelParams.reference_q_fuel == REFERENCE_Q_FUEL


def test_every_mapped_bada4_model_declares_the_reference_lhv(
    bada_path: Path | None,
) -> None:
    if bada_path is None:
        pytest.skip("BADA path not provided")
    root = bada_path / DEFAULT_BADA4_VERSION
    # A BADA folder may hold only some models (e.g. the CI data repository):
    # check every mapped model that is present.
    codes = {c for c in _mapped_bada4_codes() if (root / c / f"{c}.xml").is_file()}
    if not codes:
        pytest.skip(f"no mapped BADA4 model found under {root}")
    lhv = {code: float(BADA4Adapter(str(root), code)._obj.LHV) for code in codes}
    different = {code: v for code, v in lhv.items() if v != REFERENCE_Q_FUEL}
    assert not different, f"BADA4 LHV differs from REFERENCE_Q_FUEL: {different}"
