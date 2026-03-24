from __future__ import annotations

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
        # VStall increases with mass — heavier → higher stall speed
        mock_aircraft.flightEnvelope.VStall.side_effect = lambda mass, config: (
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
