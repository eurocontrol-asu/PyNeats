"""Tests for the airspeed trust step (audit I1, I9, I14).

No row is removed and no column is added. A row whose true airspeed (TAS) is
not finite, whose CAS is below the BADA stall CAS at MTOW (CAS against CAS) or
above the BADA VMO (400 kt when the BADA model has none), or whose Mach number
is 1 or more, is untrusted; its TAS is
replaced by linear interpolation in time between trusted rows, and before the
first and after the last trusted row by the CAS of that row, converted to TAS at
the row's own altitude. A computed TAS is judged and filled unsmoothed, then
smoothed; only rows whose smoothing window holds an untrusted row take the new
smoothed value.

The adapter is a fake: no BADA data is needed.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest


pytest.importorskip("pyBADA", reason="pyBADA required for performance module imports")

import pyBADA.atmosphere as atm
from pycontrails import Flight
from pycontrails.core.flight import _sg_filter
from pycontrails.physics.jet import acceleration as pc_acceleration

from pyneats.core.neats_default_parameters import DEFAULT_MAX_TRUSTED_CAS
from pyneats.core.neats_default_parameters import DEFAULT_MAX_TRUSTED_MACH
from pyneats.steps.performance.airspeed_trust import apply_airspeed_trust
from pyneats.steps.performance.airspeed_trust import fill_untrusted
from pyneats.steps.performance.airspeed_trust import hold_end_cas
from pyneats.steps.performance.airspeed_trust import max_trusted_cas
from pyneats.steps.performance.airspeed_trust import smooth_airspeed
from pyneats.steps.performance.airspeed_trust import stall_cas
from pyneats.steps.performance.airspeed_trust import untrusted_airspeed
from pyneats.steps.performance.airspeed_trust import within_smoothing_window
from pyneats.steps.performance.protocol import PerformanceStepError


KT = 1852.0 / 3600.0  # m/s per kt
MTOW = 78_000.0  # kg
STALL_CAS = {"TO": 70.0, "LD": 60.0}  # m/s, fake BADA stall CAS at MTOW
WINDOW = 7  # Savitzky-Golay window of the computed TAS (default)
FL310 = 9_448.8  # m


class FakeAdapter:
    """BADA stand-in: MTOW, a stall CAS per configuration and VMO.

    ``vmo_kt`` [kt, CAS] defaults to ``None`` (no VMO in the BADA model), so
    the 400 kt fallback applies.
    """

    bada_code = "FAKE01"

    def __init__(
        self,
        mtow: float | None = MTOW,
        vmo_kt: float | None = None,
    ) -> None:
        self.MTOW = mtow
        self._vmo_kt = vmo_kt
        self.calls: list[tuple[float, str]] = []

    def v_stall_cas(self, mass: float, config: str) -> float | None:
        self.calls.append((mass, config))
        return STALL_CAS[config]

    def vmo_cas(self) -> float | None:
        return None if self._vmo_kt is None else self._vmo_kt * KT


def _cas(tas: float, altitude: float) -> float:
    _theta, delta, sigma = atm.atmosphereProperties(altitude, 0.0)
    return float(atm.tas2Cas(tas, delta, sigma))


def _cas_array(tas: np.ndarray, altitude: np.ndarray) -> np.ndarray:
    """CAS [m/s] of ``tas`` [m/s] at pressure ``altitude`` [m], ISA."""
    _theta, delta, sigma = atm.atmosphereProperties(
        np.asarray(altitude, dtype=float), np.zeros(len(altitude))
    )
    return np.asarray(atm.tas2Cas(np.asarray(tas, dtype=float), delta, sigma))


def _df(
    tas: list[float], altitude: float | list[float] = 0.0, dt: float = 60.0
) -> pd.DataFrame:
    """Preprocessed flight with a provided TAS [m/s] (no smoothing)."""
    n = len(tas)
    tas_arr = np.asarray(tas, dtype=float)
    seg = np.full(n, dt)
    seg[-1] = np.nan
    return pd.DataFrame(
        {
            "time": pd.date_range("2025-07-09 08:00", periods=n, freq=f"{dt}s"),
            "true_airspeed": tas_arr,
            "altitude": np.broadcast_to(np.asarray(altitude, dtype=float), n).copy(),
            "delta_tau": np.zeros(n),
            "segment_duration": seg,
            "acceleration": pc_acceleration(tas_arr, seg),
            "rocd": np.zeros(n),
        }
    )


def _apply(
    df: pd.DataFrame,
    tas_unsmoothed: np.ndarray | None = None,
    config: str = "TO",
    adapter: FakeAdapter | None = None,
    fail: bool = True,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Run the step; return the flight and the mask of untrusted rows."""
    columns = list(df.columns)
    out, replaced = apply_airspeed_trust(
        df,
        adapter or FakeAdapter(),
        tas_unsmoothed,
        stall_config=config,
        smoothing_window=WINDOW,
        fail_when_mostly_untrusted=fail,
    )
    assert list(out.columns) == columns  # no column added (output schema)
    return out, replaced


# ---------------------------------------------------------------------------
# Trust mask
# ---------------------------------------------------------------------------


class TestUntrustedAirspeed:
    def test_cas_not_tas_is_compared_with_the_stall_cas(self) -> None:
        # At FL361 a TAS of 120 m/s is a CAS of about 64 m/s: below the
        # 70 m/s stall CAS although the TAS is above it.
        altitude = 11_000.0
        assert _cas(120.0, altitude) < STALL_CAS["TO"] < 120.0
        mask = untrusted_airspeed(
            np.array([120.0, 200.0]),
            np.full(2, altitude),
            np.zeros(2),
            STALL_CAS["TO"],
            max_cas=DEFAULT_MAX_TRUSTED_CAS,
        )
        assert mask.tolist() == [True, False]

    def test_sea_level_threshold(self) -> None:
        # At ISA sea level CAS = TAS.
        mask = untrusted_airspeed(
            np.array([69.9, 70.1]),
            np.zeros(2),
            np.zeros(2),
            STALL_CAS["TO"],
            max_cas=DEFAULT_MAX_TRUSTED_CAS,
        )
        assert mask.tolist() == [True, False]

    def test_not_finite_is_untrusted(self) -> None:
        mask = untrusted_airspeed(
            np.array([np.nan, np.inf, 150.0]),
            np.zeros(3),
            np.zeros(3),
            70.0,
            max_cas=DEFAULT_MAX_TRUSTED_CAS,
        )
        assert mask.tolist() == [True, True, False]

    def test_too_fast_is_untrusted(self) -> None:
        # CAS above 400 kt near the ground; Mach >= 1 at FL361 (CAS < 400 kt).
        cas_limit = DEFAULT_MAX_TRUSTED_CAS
        low = untrusted_airspeed(
            np.array([cas_limit - 1.0, cas_limit + 1.0]),
            np.zeros(2),
            np.zeros(2),
            70.0,
            max_cas=DEFAULT_MAX_TRUSTED_CAS,
        )
        assert low.tolist() == [False, True]
        theta, _delta, _sigma = atm.atmosphereProperties(11_000.0, 0.0)
        mach_1 = float(atm.mach2Tas(1.0, theta))
        high = untrusted_airspeed(
            np.array([0.98 * mach_1, mach_1 + 0.1, 10.0 * mach_1]),
            np.full(3, 11_000.0),
            np.zeros(3),
            70.0,
            max_cas=DEFAULT_MAX_TRUSTED_CAS,
        )
        assert high.tolist() == [False, True, True]
        assert _cas(mach_1 + 0.1, 11_000.0) < cas_limit

    def test_no_stall_speed_keeps_the_other_rules(self) -> None:
        mask = untrusted_airspeed(
            np.array([5.0, np.nan, 300.0]),
            np.zeros(3),
            np.zeros(3),
            None,
            max_cas=DEFAULT_MAX_TRUSTED_CAS,
        )
        assert mask.tolist() == [False, True, True]

    def test_stall_cas_uses_mtow_and_config(self) -> None:
        adapter = FakeAdapter()
        assert stall_cas(adapter, "LD") == STALL_CAS["LD"]
        assert adapter.calls == [(MTOW, "LD")]
        assert stall_cas(FakeAdapter(mtow=None), "TO") is None

    def test_missing_stall_speed_warning_names_the_bada_model(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        df = _df([150.0, 5.0, 160.0, 170.0])
        with caplog.at_level(logging.WARNING):
            _, replaced = _apply(df, adapter=FakeAdapter(mtow=None))
        stall = [r.getMessage() for r in caplog.records if "stall" in r.getMessage()]
        assert len(stall) == 1 and "FAKE01" in stall[0]
        assert not replaced.any()  # no stall test


class TestMaxTrustedCas:
    """CAS limit = BADA VMO (no margin), 400 kt without; Mach limit stays 1."""

    def test_vmo_without_margin(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            max_cas = max_trusted_cas(FakeAdapter(vmo_kt=350.0))
        assert max_cas == pytest.approx(350.0 * KT)
        assert caplog.text == ""

    def test_vmo_above_400_kt_is_used_as_is(self) -> None:
        assert max_trusted_cas(FakeAdapter(vmo_kt=420.0)) == pytest.approx(420.0 * KT)

    def test_missing_vmo_falls_back_to_400_kt_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            max_cas = max_trusted_cas(FakeAdapter())
        assert max_cas == DEFAULT_MAX_TRUSTED_CAS
        assert max_cas == pytest.approx(400.0 * KT)
        assert "No BADA VMO for FAKE01" in caplog.text

    def test_cas_above_vmo_is_untrusted(self) -> None:
        # Sea level, CAS = TAS: 360 kt is above an A320 VMO (350 kt) but
        # below the 400 kt fallback; 349.9 kt is trusted (no margin).
        tas = list(np.array([349.9, 360.0, 300.0, 300.0]) * KT)
        _, a320 = _apply(_df(tas), adapter=FakeAdapter(vmo_kt=350.0))
        _, fallback = _apply(_df(tas))
        assert a320.tolist() == [False, True, False, False]
        assert not fallback.any()

    def test_mach_limit_stays_1_not_mmo(self) -> None:
        # FL390 with an A320 (VMO 350 kt, MMO 0.82): Mach 0.92 and 0.99 are
        # trusted (CAS below VMO), Mach 1.0 is not.
        altitude = 11_887.2
        theta, _delta, _sigma = atm.atmosphereProperties(altitude, 0.0)
        tas = [float(atm.mach2Tas(m, theta)) for m in (0.80, 0.92, 0.99, 1.0, 0.80)]
        assert _cas(tas[3], altitude) < 350.0 * KT  # not the CAS limit
        mask = untrusted_airspeed(
            np.array(tas),
            np.full(5, altitude),
            np.zeros(5),
            STALL_CAS["TO"],
            max_cas=max_trusted_cas(FakeAdapter(vmo_kt=350.0)),
        )
        assert DEFAULT_MAX_TRUSTED_MACH == 1.0
        assert mask.tolist() == [False, False, False, True, False]

    def test_take_off_catch_up_minute_is_not_an_anchor(self) -> None:
        # ETD75F-like: two slow minutes on the runway, then a 370 kt "catch-up"
        # minute after a frozen position, then the climb. With the 400 kt
        # limit the catch-up minute is the first trusted row and the runway
        # minutes take its 370 kt CAS; with VMO (350 kt) they take the CAS of
        # the first real climb minute.
        altitude = [0.0, 0.0, 150.0, 450.0, 900.0, 1_500.0, 2_100.0]
        tas = np.array([30.0, 30.0, 370.0, 180.0, 190.0, 200.0, 210.0]) * KT
        df = _df(list(tas), altitude=altitude)

        out_400, mask_400 = _apply(df.copy())
        out_vmo, mask_vmo = _apply(df.copy(), adapter=FakeAdapter(vmo_kt=350.0))

        assert mask_400.tolist() == [True, True, False, False, False, False, False]
        assert mask_vmo.tolist() == [True, True, True, False, False, False, False]
        cas_400 = _cas_array(out_400["true_airspeed"].to_numpy(), np.array(altitude))
        cas_vmo = _cas_array(out_vmo["true_airspeed"].to_numpy(), np.array(altitude))
        np.testing.assert_allclose(cas_400[:2], cas_400[2], rtol=1e-9)
        assert cas_400[2] / KT > 360.0
        np.testing.assert_allclose(cas_vmo[:3], cas_vmo[3], rtol=1e-9)
        assert cas_vmo[:3].max() / KT < 180.0


# ---------------------------------------------------------------------------
# Fill and smoothing
# ---------------------------------------------------------------------------


class TestFillUntrusted:
    def test_interior_gap_is_linear_in_time(self) -> None:
        values = np.array([100.0, 1.0, 1.0, 200.0])
        time_s = np.array([0.0, 10.0, 70.0, 100.0])  # uneven steps
        untrusted = np.array([False, True, True, False])
        out = fill_untrusted(values, untrusted, time_s)
        np.testing.assert_allclose(out, [100.0, 110.0, 170.0, 200.0])

    def test_ends_take_the_nearest_trusted_value(self) -> None:
        values = np.array([np.nan, 5.0, 100.0, 120.0, 3.0, np.nan])
        untrusted = np.array([True, True, False, False, True, True])
        out = fill_untrusted(values, untrusted, np.arange(6.0))
        np.testing.assert_array_equal(out, [100.0, 100.0, 100.0, 120.0, 120.0, 120.0])

    def test_no_trusted_value_raises(self) -> None:
        with pytest.raises(ValueError, match="No trusted"):
            fill_untrusted(np.ones(3), np.ones(3, dtype=bool), np.arange(3.0))


class TestHoldEndCas:
    def test_descent_after_a_cruise_anchor_keeps_the_cas(self) -> None:
        altitude = np.array([11_000.0, 11_000.0, 8_000.0, 4_000.0, 500.0])
        tas = np.array([230.0, 235.0, 235.0, 235.0, 235.0])
        untrusted = np.array([False, False, True, True, True])

        out = hold_end_cas(tas, untrusted, altitude, np.zeros(5))

        cas = _cas_array(out, altitude)
        np.testing.assert_allclose(cas[2:], _cas(235.0, 11_000.0), rtol=1e-9)
        assert (np.diff(out[1:]) < 0.0).all()
        np.testing.assert_array_equal(out[:2], tas[:2])

    def test_delta_tau_of_each_row_is_used(self) -> None:
        # ISA+20 K at the end row: same CAS, higher TAS than at ISA.
        altitude = np.full(3, 3_000.0)
        untrusted = np.array([False, True, True])
        tas = np.array([150.0, 0.0, 0.0])
        out = hold_end_cas(tas, untrusted, altitude, np.array([0.0, 0.0, 20.0]))
        assert out[1] == pytest.approx(150.0, rel=1e-9)
        assert out[2] > out[1]

    def test_row_without_altitude_takes_the_anchor_tas(self) -> None:
        altitude = np.array([np.nan, 3_000.0, 3_000.0])
        out = hold_end_cas(
            np.array([0.0, 150.0, 160.0]),
            np.array([True, False, False]),
            altitude,
            np.zeros(3),
        )
        np.testing.assert_array_equal(out, [150.0, 150.0, 160.0])

    def test_no_trusted_value_raises(self) -> None:
        with pytest.raises(ValueError, match="No trusted"):
            hold_end_cas(np.ones(2), np.ones(2, dtype=bool), np.zeros(2), np.zeros(2))


class TestSmoothAirspeed:
    @pytest.mark.parametrize("n", [1, 2, 3, 6, 7, 8, 50])
    def test_same_as_pycontrails_ground_speed_smoothing(self, n: int) -> None:
        rng = np.random.default_rng(n)
        tas = 200.0 + 20.0 * rng.standard_normal(n)
        np.testing.assert_array_equal(
            smooth_airspeed(tas, WINDOW), _sg_filter(tas.copy(), WINDOW, 1)
        )

    @pytest.mark.parametrize("n", [1, 2, 3, 6, 7, 8, 9, 30])
    @pytest.mark.parametrize("seed", range(5))
    def test_smoothed_value_outside_the_window_mask_ignores_the_flags(
        self, n: int, seed: int
    ) -> None:
        # Changing the flagged values changes rows of the mask only. (An edge
        # row of the mask can keep its value: a linear edge fit can give a
        # flagged row a zero weight.)
        rng = np.random.default_rng(100 * n + seed)
        tas = 200.0 + 20.0 * rng.standard_normal(n)
        flags = rng.random(n) < 0.15
        changed = tas.copy()
        changed[flags] += 50.0 + 10.0 * rng.random(int(flags.sum()))

        moved = smooth_airspeed(changed, WINDOW) != smooth_airspeed(tas, WINDOW)

        mask = within_smoothing_window(flags, WINDOW)
        assert not (moved & ~mask).any()  # rows outside the mask: bit-identical
        assert moved[flags].all() and mask[flags].all()

    def test_window_mask_of_an_interior_flag(self) -> None:
        flags = np.zeros(20, dtype=bool)
        flags[10] = True
        assert np.flatnonzero(within_smoothing_window(flags, WINDOW)).tolist() == list(
            range(7, 14)
        )
        flags[:] = False
        flags[1] = True  # inside the first window: the whole first half-window
        assert np.flatnonzero(within_smoothing_window(flags, WINDOW)).tolist() == list(
            range(0, 5)
        )


# ---------------------------------------------------------------------------
# apply_airspeed_trust, provided TAS (no smoothing)
# ---------------------------------------------------------------------------


class TestProvidedTas:
    def test_clean_flight_unchanged(self) -> None:
        df = _df([150.0, 155.0, 160.0, 158.0, 150.0])
        before = df.copy()

        out, replaced = _apply(df)

        pd.testing.assert_frame_equal(out, before)
        assert not replaced.any()

    def test_interior_gap(self) -> None:
        df = _df([150.0, 160.0, 20.0, 30.0, 190.0, 200.0])

        out, replaced = _apply(df)

        np.testing.assert_allclose(
            out["true_airspeed"], [150.0, 160.0, 170.0, 180.0, 190.0, 200.0]
        )
        assert replaced.tolist() == [0, 0, 1, 1, 0, 0]
        # acceleration [m/s^2] from the TAS used; no row removed.
        np.testing.assert_allclose(
            out["acceleration"], [10 / 60, 10 / 60, 10 / 60, 10 / 60, 10 / 60, 0.0]
        )
        assert len(out) == 6
        assert np.isnan(out["segment_duration"].iloc[-1])

    def test_start_and_end_runs(self) -> None:
        # Same altitude everywhere: the held CAS gives back the anchor TAS.
        df = _df([10.0, 20.0, 150.0, 160.0, 170.0, 30.0, 5.0])

        out, _ = _apply(df)

        np.testing.assert_allclose(
            out["true_airspeed"],
            [150.0, 150.0, 150.0, 160.0, 170.0, 170.0, 170.0],
            rtol=1e-9,
        )

    def test_end_run_in_a_descent_holds_the_cas(self) -> None:
        # THY6RA-like: the last trusted row is in cruise (FL370, 455 kt TAS),
        # the descent to FL28 after it is untrusted. The end run keeps the
        # CAS of the cruise row, so its TAS falls with the altitude, instead
        # of keeping 455 kt TAS (a CAS of more than 400 kt near the ground).
        altitude = np.array([11_277.6, 11_277.6, 9_000.0, 6_000.0, 3_000.0, 853.4])
        tas = [455.0 * KT, 455.0 * KT, 20.0, 20.0, 20.0, np.nan]
        df = _df(tas, altitude=list(altitude))

        out, replaced = _apply(df)

        assert replaced.tolist() == [0, 0, 1, 1, 1, 1]
        new_tas = out["true_airspeed"].to_numpy()
        cas = _cas_array(new_tas, altitude)
        np.testing.assert_allclose(cas[2:], cas[1], rtol=1e-9)
        assert (np.diff(new_tas[1:]) < 0.0).all()  # TAS falls with the altitude
        assert cas.max() < DEFAULT_MAX_TRUSTED_CAS
        assert _cas(455.0 * KT, 853.4) > DEFAULT_MAX_TRUSTED_CAS  # TAS hold
        np.testing.assert_allclose(
            out["acceleration"].to_numpy()[:-1], np.diff(new_tas) / 60.0
        )

    def test_start_run_in_a_climb_holds_the_cas(self) -> None:
        # Slow take-off minutes below the first trusted row (FL100): they
        # take its CAS, so a lower TAS than the anchor's.
        altitude = np.array([0.0, 300.0, 1_500.0, 3_048.0, 3_500.0, 4_000.0])
        tas = [30.0, 40.0, 50.0, 140.0, 150.0, 160.0]
        df = _df(tas, altitude=list(altitude))

        out, replaced = _apply(df)

        assert replaced.tolist() == [1, 1, 1, 0, 0, 0]
        new_tas = out["true_airspeed"].to_numpy()
        cas = _cas_array(new_tas, altitude)
        np.testing.assert_allclose(cas[:3], cas[3], rtol=1e-9)
        assert (np.diff(new_tas[:4]) > 0.0).all()
        np.testing.assert_array_equal(new_tas[3:], tas[3:])

    def test_nan_last_point(self) -> None:
        df = _df([150.0, 160.0, 170.0, np.nan])

        out, replaced = _apply(df)

        np.testing.assert_allclose(
            out["true_airspeed"], [150.0, 160.0, 170.0, 170.0], rtol=1e-9
        )
        assert replaced.tolist() == [0, 0, 0, 1]

    def test_fast_point(self) -> None:
        # A duplicate raw timestamp can give a 10,000 kt segment.
        df = _df([150.0, 10_000.0 * KT, 170.0, 180.0])

        out, _ = _apply(df)

        np.testing.assert_allclose(out["true_airspeed"], [150.0, 160.0, 170.0, 180.0])

    def test_landing_config_threshold(self) -> None:
        # 65 m/s at sea level: below the TO stall CAS (70), above the LD one (60).
        tas = [150.0, 65.0, 150.0, 150.0]
        assert _apply(_df(tas), config="TO")[1].sum() == 1
        assert _apply(_df(tas), config="LD")[1].sum() == 0

    def test_more_than_80_percent_of_time_untrusted_fails(self) -> None:
        tas = [150.0] + [10.0] * 8 + [150.0]  # 8 of 9 segments of 60 s untrusted
        with pytest.raises(PerformanceStepError, match="89%") as exc:
            _apply(_df(tas))
        assert not exc.value.retryable

    def test_80_percent_of_time_untrusted_passes(self) -> None:
        tas = [150.0] + [10.0] * 4 + [150.0]  # 4 of 5 segments untrusted
        _, replaced = _apply(_df(tas))
        assert replaced.sum() == 4

    def test_no_failure_when_not_asked_replaces_the_tas(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Path where the BADA fuel flow is not used (AO fuel flow, efficiency
        # and mass): more than 80 % untrusted keeps the flight, TAS replaced.
        tas = [150.0] + [10.0] * 8 + [150.0]
        with caplog.at_level(logging.WARNING):
            out, replaced = _apply(_df(tas), fail=False)
        assert "89%" in caplog.text
        assert replaced.sum() == 8
        np.testing.assert_allclose(out["true_airspeed"], 150.0, rtol=1e-9)

    def test_no_failure_when_not_asked_and_no_trusted_row(self) -> None:
        # Nothing to interpolate from: the TAS is kept as is.
        df = _df([10.0, 20.0, np.nan])
        before = df.copy()
        out, replaced = _apply(df, fail=False)
        assert replaced.all()
        pd.testing.assert_frame_equal(out, before)

    def test_time_share_uses_segment_durations(self) -> None:
        # 1 untrusted row of 4, but its segment is 85 % of the flight time.
        df = _df([150.0, 10.0, 150.0, 150.0])
        df["segment_duration"] = [10.0, 170.0, 20.0, np.nan]
        with pytest.raises(PerformanceStepError, match="85%"):
            _apply(df)

    def test_no_trusted_row_fails(self) -> None:
        with pytest.raises(PerformanceStepError) as exc:
            _apply(_df([np.nan, np.nan]))
        assert not exc.value.retryable


# ---------------------------------------------------------------------------
# apply_airspeed_trust, computed TAS (unsmoothed trust, then smoothing)
# ---------------------------------------------------------------------------


def _flight(speeds_kt: list[float], altitude: float = FL310) -> Flight:
    """Flight east along the equator, 1 min per segment, at given ground speeds."""
    n = len(speeds_kt) + 1
    step_deg = np.degrees(np.asarray(speeds_kt) * KT * 60.0 / 6_371_229.0)
    lon = np.concatenate([[0.0], np.cumsum(step_deg)])
    return Flight(
        longitude=lon,
        latitude=np.zeros(n),
        altitude=np.full(n, altitude),
        time=pd.date_range("2025-07-09 07:40", periods=n, freq="1min"),
    )


def _computed_df(flight: Flight, u: float = 0.0, v: float = 0.0) -> tuple:
    """As BADAPerformanceModel._preprocess: smoothed TAS, plus unsmoothed TAS."""
    n = len(flight)
    u_wind = np.full(n, u)
    v_wind = np.full(n, v)
    tas = flight.segment_true_airspeed(u_wind=u_wind, v_wind=v_wind, smooth=True)
    raw = flight.segment_true_airspeed(u_wind=u_wind, v_wind=v_wind, smooth=False)
    seg = pd.to_numeric(pd.Series(flight.segment_duration())).to_numpy(float)
    df = pd.DataFrame(
        {
            "time": flight["time"],
            "true_airspeed": tas,
            "altitude": flight.altitude,
            "delta_tau": np.zeros(n),
            "segment_duration": seg,
            "acceleration": pc_acceleration(tas, seg),
        }
    )
    return df, raw


class TestComputedTas:
    def test_clean_flight_keeps_its_smoothed_tas(self) -> None:
        # Accelerating climb-out speeds with a cross wind; every segment is
        # trusted, only the last row (no forward segment) has no TAS.
        speeds = [250.0 + 5.0 * i for i in range(30)]
        df, raw = _computed_df(_flight(speeds, altitude=3_000.0), u=12.0, v=-7.0)
        before = df.copy()

        out, replaced = _apply(df, raw)

        np.testing.assert_array_equal(
            out["true_airspeed"].to_numpy()[:-1],
            before["true_airspeed"].to_numpy()[:-1],
        )
        assert out["true_airspeed"].iloc[-1] == out["true_airspeed"].iloc[-2]
        np.testing.assert_array_equal(out["acceleration"], before["acceleration"])
        assert replaced.tolist() == [False] * 30 + [True]

    def test_cruise_gap_filled_from_unsmoothed_neighbours(self) -> None:
        # STW1125 at FL310: about 500 kt, then a 15-min raw gap at 57.5 kt,
        # then 457 kt. The smoothed TAS next to the gap is pulled down by the
        # slow minutes; the fill uses the unsmoothed speeds either side.
        speeds = [500.0] * 20 + [57.5] * 15 + [457.0] * 25
        df, raw = _computed_df(_flight(speeds))
        smoothed_anchor_kt = df["true_airspeed"].iloc[19] / KT
        assert smoothed_anchor_kt < 400.0  # smoothing leaks the slow minutes
        observed = df["true_airspeed"].to_numpy().copy()

        out, replaced = _apply(df, raw)

        assert np.flatnonzero(replaced).tolist() == list(range(20, 35)) + [60]
        gap_kt = out["true_airspeed"].to_numpy()[20:35] / KT
        assert gap_kt.min() > 457.0 - 1.0
        assert gap_kt.max() < 500.0 + 1.0
        # Trusted cruise rows next to the gap are no longer pulled down.
        assert out["true_airspeed"].iloc[19] / KT > 480.0
        assert out["true_airspeed"].iloc[35] / KT > 450.0
        # Only rows within half a window (3 points) of the gap are re-smoothed;
        # the others keep the TAS from the smoothed ground speed bit for bit.
        tas = out["true_airspeed"].to_numpy()
        far = np.r_[0:17, 38:60]
        np.testing.assert_array_equal(tas[far], observed[far])
        assert (tas[17:20] != observed[17:20]).all()
        assert (tas[35:38] != observed[35:38]).all()
        assert not replaced[np.r_[17:20, 35:38]].any()

    def test_end_runs_take_the_unsmoothed_value_of_the_nearest_trusted_row(
        self,
    ) -> None:
        # Three slow minutes on the runway, then a steady acceleration; four
        # slow minutes at the end. The Savitzky-Golay edge fit would
        # extrapolate the acceleration back over the first rows (below the
        # stall CAS); the end rule holds the first trusted row's unsmoothed
        # CAS instead (its TAS at this constant altitude).
        speeds = [40.0] * 3 + [150.0 + 10.0 * i for i in range(20)] + [40.0] * 4
        df, raw = _computed_df(_flight(speeds, altitude=0.0))

        out, replaced = _apply(df, raw)

        tas = out["true_airspeed"].to_numpy()
        assert np.flatnonzero(replaced).tolist() == [0, 1, 2, 23, 24, 25, 26, 27]
        np.testing.assert_allclose(tas[:3], raw[3], rtol=1e-9)
        np.testing.assert_allclose(tas[23:], raw[22], rtol=1e-9)
        assert tas.min() >= STALL_CAS["TO"]  # CAS = TAS at ISA sea level
        # Without the end rule the edge fit gives a lower first value.
        edge_fit = smooth_airspeed(
            np.r_[np.full(3, raw[3]), raw[3:23], np.full(4, raw[22])], WINDOW
        )
        assert edge_fit[0] < tas[0]

    def test_end_run_in_a_descent_holds_the_cas_after_smoothing(self) -> None:
        # THY6RA: cruise at FL370 (455 kt), then a descent to FL28 whose raw
        # speeds are untrusted (here slow). The end run keeps the CAS of the
        # last trusted cruise row, also after the re-smoothing; the last row
        # (no forward segment) takes the TAS of the row before it.
        n_cruise, n_descent = 15, 10
        altitude = np.r_[
            np.full(n_cruise + 1, 11_277.6), np.linspace(10_000.0, 853.4, n_descent)
        ]
        speeds = [455.0] * n_cruise + [40.0] * n_descent
        flight = _flight(speeds)
        flight.update(altitude=altitude)
        df, raw = _computed_df(flight)

        out, replaced = _apply(df, raw)

        last = n_cruise - 1  # last trusted row (FL370)
        assert np.flatnonzero(replaced).tolist() == list(range(n_cruise, len(df)))
        tas = out["true_airspeed"].to_numpy()
        cas = _cas_array(tas, altitude)
        np.testing.assert_allclose(cas[last + 1 : -1], _cas(raw[last], altitude[last]))
        assert (np.diff(tas[last + 1 : -1]) < 0.0).all()  # TAS falls with altitude
        assert tas[-1] == tas[-2]
        assert cas.max() < DEFAULT_MAX_TRUSTED_CAS

    def test_unsmoothed_trust_ignores_smoothing_artefacts(self) -> None:
        # One raw minute at 60 kt in a 250 kt descent: SG spreads it over its
        # neighbours, but only that minute is untrusted on the raw speed.
        speeds = [250.0] * 10 + [60.0] + [250.0] * 10
        df, raw = _computed_df(_flight(speeds, altitude=1_000.0))

        out, replaced = _apply(df, raw)

        assert np.flatnonzero(replaced).tolist() == [10, 21]
        np.testing.assert_allclose(out["true_airspeed"], 250.0 * KT, rtol=1e-9)
