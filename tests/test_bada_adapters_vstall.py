"""BADA stall speed (``v_stall_cas``) of the BADA3 and BADA4 adapters (audit I1).

pyBADA 0.1.12: BADA3 ``VStall(mass, config)``; BADA4
``VStall(mass, HLid, LG, nz=1.0, theta=, delta=)`` with (HLid, LG) from
``getAeroConfig(config)``. The BADA4 adapter used the BADA3 call, which raised
``TypeError``, so BADA4 flights were never speed-checked.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


if TYPE_CHECKING:
    from pyneats.steps.performance.bada_adapters import BADA3Adapter
    from pyneats.steps.performance.bada_adapters import BADA4Adapter


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


# ---------------------------------------------------------------------------
# Helpers — build mock adapters without touching real pyBADA / file system
# ---------------------------------------------------------------------------


def _make_bada4_adapter(vstall_return: float | None = 80.0) -> BADA4Adapter:
    """Build a BADA4Adapter with a mocked Bada4Aircraft."""
    from pyneats.steps.performance.bada_adapters import BADA4Adapter

    mock_aircraft = MagicMock()
    mock_aircraft.flightEnvelope.getAeroConfig.return_value = [3.0, "LGUP"]
    mock_aircraft.flightEnvelope.VStall.return_value = vstall_return
    mock_aircraft.MTOW = 80_000.0
    mock_aircraft.n_eng = 2
    mock_aircraft.span = 35.0
    mock_aircraft.MPL = 20_000.0
    mock_aircraft.OEW = 42_000.0

    with patch(
        "pyneats.steps.performance.bada_adapters.Bada4Aircraft",
        return_value=mock_aircraft,
    ):
        adapter = BADA4Adapter("/fake/path/4.2.1", "A320", rocd_phase_threshold_fpm=0.0)

    return adapter


def _make_bada3_adapter(vstall_return: float | None = 70.0) -> BADA3Adapter:
    """Build a BADA3Adapter with a mocked Bada3Aircraft."""
    from pyneats.steps.performance.bada_adapters import BADA3Adapter

    mock_aircraft = MagicMock()
    mock_aircraft.flightEnvelope.VStall.return_value = vstall_return
    mock_aircraft.MTOW = 70_000.0
    mock_aircraft.numberOfEngines = 2
    mock_aircraft.span = 34.0
    mock_aircraft.OEW = 40_000.0

    with patch(
        "pyneats.steps.performance.bada_adapters.Bada3Aircraft",
        return_value=mock_aircraft,
    ):
        adapter = BADA3Adapter("/fake/path/3.13", "A319", rocd_phase_threshold_fpm=0.0)

    return adapter


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestVStallBada4:
    """BADA4Adapter.v_stall_cas unit tests."""

    def test_vstall_bada4_returns_float(self) -> None:
        adapter = _make_bada4_adapter(vstall_return=80.0)

        result = adapter.v_stall_cas(mass=70_000, config="CR")

        assert isinstance(result, float)
        assert result > 0

    def test_vstall_returns_none_gracefully(self) -> None:
        adapter = _make_bada4_adapter(vstall_return=None)

        result = adapter.v_stall_cas(mass=70_000, config="CR")

        assert result is None

    def test_missing_configuration_returns_none(self) -> None:
        # pyBADA getAeroConfig subscripts None for a configuration missing
        # from the BADA4 file; the adapter returns None before that.
        adapter = _make_bada4_adapter(vstall_return=80.0)
        envelope = adapter._obj.flightEnvelope
        envelope.AC.aeroConfig = {"TO": {"HLid": 3.0, "LG": "LGUP"}}

        assert adapter.v_stall_cas(mass=70_000, config="LD") is None
        envelope.getAeroConfig.assert_not_called()
        envelope.VStall.assert_not_called()

    def test_vstall_bada4_signature(self) -> None:
        adapter = _make_bada4_adapter(vstall_return=80.0)

        adapter.v_stall_cas(mass=70_000, config="TO")

        envelope = adapter._obj.flightEnvelope
        envelope.getAeroConfig.assert_called_once_with(config="TO")
        envelope.VStall.assert_called_once_with(
            mass=70_000, HLid=3.0, LG="LGUP", nz=1.0, theta=1.0, delta=1.0
        )


class TestVStallBada3:
    """BADA3Adapter.v_stall_cas unit tests."""

    def test_vstall_bada3_returns_float(self) -> None:
        adapter = _make_bada3_adapter(vstall_return=70.0)

        result = adapter.v_stall_cas(mass=60_000, config="CR")

        assert isinstance(result, float)
        assert result > 0

    def test_vstall_returns_none_gracefully(self) -> None:
        adapter = _make_bada3_adapter(vstall_return=None)

        result = adapter.v_stall_cas(mass=60_000, config="CR")

        assert result is None

    def test_vstall_bada3_signature(self) -> None:
        adapter = _make_bada3_adapter(vstall_return=70.0)

        adapter.v_stall_cas(mass=60_000, config="LD")

        adapter._obj.flightEnvelope.VStall.assert_called_once_with(
            mass=60_000, config="LD"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestVStallEdgeCases:
    """Edge cases for v_stall_cas across adapters."""

    def test_missing_clmax_data_returns_none(self) -> None:
        """When pyBADA returns None from VStall (missing CLmax data),
        v_stall_cas should return None without raising."""
        adapter = _make_bada4_adapter(vstall_return=None)

        result = adapter.v_stall_cas(mass=70_000, config="CR")

        assert result is None

    def test_heavy_aircraft_higher_vstall(self) -> None:
        """At MTOW, VStall should be higher than at a lighter mass.

        We configure VStall to return different values depending on mass
        to simulate real pyBADA behavior.
        """
        from pyneats.steps.performance.bada_adapters import BADA4Adapter

        mock_aircraft = MagicMock()
        mock_aircraft.flightEnvelope.getAeroConfig.return_value = [0.0, "LGUP"]
        # VStall increases with mass — heavier → higher stall speed
        mock_aircraft.flightEnvelope.VStall.side_effect = lambda mass, **_: (
            90.0 if mass >= 80_000 else 75.0
        )
        mock_aircraft.MTOW = 80_000.0
        mock_aircraft.n_eng = 2
        mock_aircraft.span = 35.0
        mock_aircraft.MPL = 20_000.0
        mock_aircraft.OEW = 42_000.0

        with patch(
            "pyneats.steps.performance.bada_adapters.Bada4Aircraft",
            return_value=mock_aircraft,
        ):
            adapter = BADA4Adapter(
                "/fake/path/4.2.1", "A320", rocd_phase_threshold_fpm=0.0
            )

        mtow = adapter.MTOW
        assert mtow is not None

        v_heavy = adapter.v_stall_cas(mass=mtow, config="CR")
        v_light = adapter.v_stall_cas(mass=50_000, config="CR")

        assert v_heavy is not None
        assert v_light is not None
        assert v_heavy > v_light


# ---------------------------------------------------------------------------
# Real BADA data (skipped without --bada-path / BADA_PATH)
# ---------------------------------------------------------------------------


@pytest.mark.requires_bada
@pytest.mark.parametrize("code", ["A320-214", "B738W26", "B744GE"])
def test_vstall_bada4_real_data(bada_path: Path | None, code: str) -> None:
    from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
    from pyneats.steps.performance.bada_adapters import BADA4Adapter

    if bada_path is None:
        pytest.skip("BADA path not provided")
    root = bada_path / DEFAULT_BADA4_VERSION
    if not (root / code / f"{code}.xml").is_file():
        pytest.skip(f"BADA4 model {code} not found under {root}")
    adapter = BADA4Adapter(str(root), code)
    mtow = adapter.MTOW
    assert mtow is not None

    v_to = adapter.v_stall_cas(mtow, "TO")
    v_ld = adapter.v_stall_cas(mtow, "LD")

    # Same as pyBADA called directly with the configuration's HLid and LG.
    envelope = adapter._obj.flightEnvelope
    hlid, lg = envelope.getAeroConfig(config="TO")
    expected = envelope.VStall(
        mass=mtow, HLid=hlid, LG=lg, nz=1.0, theta=1.0, delta=1.0
    )
    assert v_to == float(expected)
    # Plausible CAS [m/s] for a jet at MTOW; landing below take-off.
    assert v_to is not None and v_ld is not None
    assert math.isfinite(v_to)
    assert 50.0 < v_ld < v_to < 110.0
    assert adapter.v_stall_cas(0.8 * mtow, "TO") < v_to


@pytest.mark.requires_bada
def test_vstall_bada3_real_data(bada_path: Path | None) -> None:
    from pyneats.core.neats_default_parameters import DEFAULT_BADA3_VERSION
    from pyneats.steps.performance.bada_adapters import BADA3Adapter

    if bada_path is None:
        pytest.skip("BADA path not provided")
    root = bada_path / DEFAULT_BADA3_VERSION
    if not (root / "A320__.OPF").is_file():
        pytest.skip(f"BADA3 model A320 not found under {root}")
    adapter = BADA3Adapter(str(root), "A320")
    mtow = adapter.MTOW
    assert mtow is not None

    v_to = adapter.v_stall_cas(mtow, "TO")
    v_ld = adapter.v_stall_cas(mtow, "LD")

    assert v_to is not None and v_ld is not None
    assert 50.0 < v_ld < v_to < 110.0
