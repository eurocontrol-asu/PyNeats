"""Maximum operating speed ``vmo_cas`` of the BADA3 and BADA4 adapters.

The airspeed trust step flags a row whose CAS is above the BADA maximum
operating speed VMO (no margin; 400 kt when the BADA model has none). pyBADA
0.1.12 stores VMO in kt (CAS) on the aircraft object, for BADA4 (XML
``KLM/vmo``) and BADA3 (OPF "Flight envelope" block); the adapters return it in
m/s, and ``None`` when it is missing.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


if TYPE_CHECKING:
    from pyneats.steps.performance.bada_adapters import BADA3Adapter
    from pyneats.steps.performance.bada_adapters import BADA4Adapter


KT = 0.514444  # m/s per kt (pyBADA kt2ms, pycontrails knots_to_m_per_s)


def _can_import_bada_adapters() -> bool:
    try:
        import pyneats.steps.performance.bada_adapters  # noqa: F401
    except (ImportError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _can_import_bada_adapters(),
    reason="pyBADA or pycontrails not installed",
)


def _make_bada4_adapter(vmo: object) -> BADA4Adapter:
    """BADA4Adapter on a mocked Bada4Aircraft with ``VMO`` [kt]."""
    from pyneats.steps.performance.bada_adapters import BADA4Adapter

    mock_aircraft = MagicMock()
    mock_aircraft.VMO = vmo
    with patch(
        "pyneats.steps.performance.bada_adapters.Bada4Aircraft",
        return_value=mock_aircraft,
    ):
        return BADA4Adapter("/fake/path/4.2.1", "A320", rocd_phase_threshold_fpm=0.0)


def _make_bada3_adapter(vmo: object) -> BADA3Adapter:
    """BADA3Adapter on a mocked Bada3Aircraft with ``VMO`` [kt]."""
    from pyneats.steps.performance.bada_adapters import BADA3Adapter

    mock_aircraft = MagicMock()
    mock_aircraft.VMO = vmo
    with patch(
        "pyneats.steps.performance.bada_adapters.Bada3Aircraft",
        return_value=mock_aircraft,
    ):
        return BADA3Adapter("/fake/path/3.16", "A320", rocd_phase_threshold_fpm=0.0)


Maker = Callable[[object], "BADA3Adapter | BADA4Adapter"]
MAKERS: list[Maker] = [_make_bada4_adapter, _make_bada3_adapter]


# ---------------------------------------------------------------------------
# Unit tests (mocked pyBADA aircraft)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("make", MAKERS)
def test_vmo_is_converted_from_kt_to_m_per_s(make: Maker) -> None:
    assert make(350.0).vmo_cas() == pytest.approx(350.0 * KT)


@pytest.mark.parametrize("make", MAKERS)
@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), 0.0, -1.0, "n/a"])
def test_missing_or_invalid_vmo_gives_none(make: Maker, bad: object) -> None:
    assert make(bad).vmo_cas() is None


@pytest.mark.parametrize("make", MAKERS)
def test_trust_step_uses_the_adapter_vmo(make: Maker) -> None:
    from pyneats.steps.performance.airspeed_trust import max_trusted_cas

    assert max_trusted_cas(make(340.0)) == pytest.approx(340.0 * KT)


# ---------------------------------------------------------------------------
# Real BADA data (skipped without --bada-path / BADA_PATH)
# ---------------------------------------------------------------------------

# (BADA4 code, VMO [kt, CAS]) in BADA 4.2.1
BADA4_TYPES = [
    ("A320-214", 350.0),
    ("B738W26", 340.0),
    ("B744GE", 365.0),
    ("B788GE67", 350.0),
]
# (BADA3 code, VMO [kt, CAS]) in BADA 3.16
BADA3_TYPES = [
    ("A320", 350.0),
    ("AT76", 250.0),  # turboprop
]


def _check_plausible(vmo: float | None) -> None:
    """VMO [m/s, CAS] of a transport aircraft: 240 to 380 kt."""
    assert vmo is not None and math.isfinite(vmo)
    assert 240.0 * KT < vmo < 380.0 * KT


@pytest.mark.requires_bada
@pytest.mark.parametrize(("code", "vmo_kt"), BADA4_TYPES)
def test_bada4_real_data(bada_path: Path | None, code: str, vmo_kt: float) -> None:
    from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
    from pyneats.steps.performance.bada_adapters import BADA4Adapter

    if bada_path is None:
        pytest.skip("BADA path not provided")
    root = bada_path / DEFAULT_BADA4_VERSION
    if not (root / code / f"{code}.xml").is_file():
        pytest.skip(f"BADA4 model {code} not found under {root}")
    adapter = BADA4Adapter(str(root), code)

    _check_plausible(adapter.vmo_cas())
    assert adapter.vmo_cas() == pytest.approx(vmo_kt * KT)
    # Same unit as pyBADA: its clean, gear-up maximum CAS [m/s] is VMO.
    envelope = adapter._obj.flightEnvelope
    assert adapter.vmo_cas() == pytest.approx(envelope.maxCAS(HLid=0, LG="LGUP"))


@pytest.mark.requires_bada
@pytest.mark.parametrize(("code", "vmo_kt"), BADA3_TYPES)
def test_bada3_real_data(bada_path: Path | None, code: str, vmo_kt: float) -> None:
    from pyneats.core.neats_default_parameters import DEFAULT_BADA3_VERSION
    from pyneats.steps.performance.bada_adapters import BADA3Adapter

    if bada_path is None:
        pytest.skip("BADA path not provided")
    root = bada_path / DEFAULT_BADA3_VERSION
    if not (root / f"{code.ljust(6, '_')}.OPF").is_file():
        pytest.skip(f"BADA3 model {code} not found under {root}")
    adapter = BADA3Adapter(str(root), code)

    _check_plausible(adapter.vmo_cas())
    assert adapter.vmo_cas() == pytest.approx(vmo_kt * KT)
    # Same unit as pyBADA: its maximum speed [m/s, CAS] at sea level is VMO.
    assert adapter.vmo_cas() == pytest.approx(
        adapter._obj.flightEnvelope.VMax(h=0.0, deltaTemp=0.0)
    )
