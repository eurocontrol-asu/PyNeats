"""Tests for the maximum payload (MPL) used in the initial mass estimate (audit I4).

``BADA3Adapter.MPL`` returns the OPF maximum payload, as ``BADA4Adapter.MPL``
returns the BADA4 one. ``_estimate_initial_mass_iterative`` uses
ZFW = OEW + payload_factor x MPL, and MTOW - OEW only when the adapter gives
no MPL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pandas as pd
import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

from pyneats.core.neats_default_parameters import DEFAULT_BADA3_VERSION
from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
from pyneats.steps.performance.bada_adapters import BADA3Adapter
from pyneats.steps.performance.bada_adapters import BADA4Adapter
from pyneats.steps.performance.bada_model import BADAPerformanceModel


# A20N masses in BADA 3.16 (A20N__.OPF) and BADA 4.2.1 (A320-271N), kg.
MTOW = 79_000.0
OEW = 46_000.0
MPL = 18_300.0

N_POINTS = 50
SEGMENT_S = 60.0
FUEL_FLOW = 1.0  # kg/s, constant in the mocked performance pass
TRIP_FUEL = FUEL_FLOW * SEGMENT_S * N_POINTS  # 3,000 kg
RESERVE = 0.15


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def _make_bada3_adapter(mpl: float | None) -> BADA3Adapter:
    mock_aircraft = MagicMock()
    mock_aircraft.MTOW = MTOW
    mock_aircraft.OEW = OEW
    mock_aircraft.MPL = mpl
    with patch(
        "pyneats.steps.performance.bada_adapters.Bada3Aircraft",
        return_value=mock_aircraft,
    ):
        return BADA3Adapter("/fake/path/3.16", "A20N", rocd_phase_threshold_fpm=0.0)


class TestBada3AdapterMPL:
    def test_returns_opf_max_payload(self) -> None:
        assert _make_bada3_adapter(MPL).MPL == MPL

    def test_returns_none_when_pybada_has_none(self) -> None:
        assert _make_bada3_adapter(None).MPL is None

    def test_returns_none_when_attribute_missing(self) -> None:
        mock_aircraft = MagicMock(spec=["MTOW", "OEW"])
        mock_aircraft.MTOW = MTOW
        mock_aircraft.OEW = OEW
        with patch(
            "pyneats.steps.performance.bada_adapters.Bada3Aircraft",
            return_value=mock_aircraft,
        ):
            adapter = BADA3Adapter(
                "/fake/path/3.16", "A20N", rocd_phase_threshold_fpm=0.0
            )
        assert adapter.MPL is None


# ---------------------------------------------------------------------------
# Initial mass estimate
# ---------------------------------------------------------------------------


def _run_mass_estimate(
    mpl: float | None, payload_factor: float | None = None
) -> list[float | None]:
    """Run the real estimate with a constant-fuel-flow performance pass.

    Returns the ``initial_mass`` of every performance pass, in order.
    """
    model = MagicMock(spec=BADAPerformanceModel)
    model.logger = MagicMock()
    model.params = MagicMock()
    model.params.payload_factor = 1.0
    model.params.fuel_reserve_fraction = RESERVE
    model.params.max_rel_mass_diff = 0.01
    model.params.max_mass_estimation_iter = 4

    passes: list[float | None] = []

    def single_pass(
        adapter: Any, df: pd.DataFrame, initial_mass: float | None, **_: Any
    ) -> dict[str, list[float]]:
        passes.append(initial_mass)
        return {"fuel_flow": [FUEL_FLOW] * len(df)}

    model._single_pass_performance = MagicMock(side_effect=single_pass)

    adapter = MagicMock()
    adapter.MTOW = MTOW
    adapter.OEW = OEW
    adapter.MPL = mpl

    flight = MagicMock()
    flight.attrs = {} if payload_factor is None else {"payload_factor": payload_factor}
    df = pd.DataFrame({"segment_duration": [SEGMENT_S] * N_POINTS})

    BADAPerformanceModel._estimate_initial_mass_iterative(
        model, adapter, df, flight, "A20N", 43.13e6, 43.13e6
    )
    return passes


class TestInitialMassUsesMPL:
    def test_uses_mpl(self) -> None:
        passes = _run_mass_estimate(MPL)
        assert passes[0] is None  # first pass: constant-mass guess
        assert passes[1] == pytest.approx(OEW + MPL + TRIP_FUEL * (1 + RESERVE))
        assert passes[1] < MTOW

    def test_falls_back_to_mtow_minus_oew(self) -> None:
        # ZFW = OEW + (MTOW - OEW) = MTOW, so the cap applies.
        passes = _run_mass_estimate(None)
        assert passes[1] == MTOW

    def test_payload_factor_scales_mpl(self) -> None:
        passes = _run_mass_estimate(MPL, payload_factor=0.5)
        assert passes[1] == pytest.approx(OEW + 0.5 * MPL + TRIP_FUEL * (1 + RESERVE))

    def test_capped_at_mtow(self) -> None:
        # Payload at MPL plus fuel above MTOW is capped.
        passes = _run_mass_estimate(MTOW - OEW - 100.0)
        assert passes[1] == MTOW


# ---------------------------------------------------------------------------
# Real BADA files (skipped without --bada-path / BADA_PATH)
# ---------------------------------------------------------------------------


def test_bada3_mpl_matches_opf_and_bada4(bada_path: Path | None) -> None:
    """A20N: BADA 3.16 OPF and BADA 4.2.1 A320-271N give the same MPL."""
    if bada_path is None:
        pytest.skip("BADA data not available (use --bada-path or BADA_PATH)")
    bada3_dir = bada_path / DEFAULT_BADA3_VERSION
    bada4_dir = bada_path / DEFAULT_BADA4_VERSION
    if not (bada3_dir / "A20N__.OPF").exists():
        pytest.skip(f"A20N__.OPF not found in {bada3_dir}")

    bada3 = BADA3Adapter(str(bada3_dir), "A20N")
    assert bada3.MPL == MPL
    assert bada3.MTOW == MTOW
    assert bada3.OEW == OEW

    if not (bada4_dir / "A320-271N").exists():
        pytest.skip(f"A320-271N not found in {bada4_dir}")
    assert BADA4Adapter(str(bada4_dir), "A320-271N").MPL == bada3.MPL
