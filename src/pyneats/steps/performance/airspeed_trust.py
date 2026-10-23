"""Airspeed trust — replaces untrusted true airspeeds before the BADA calculation.

No row is removed and no column is added. A row whose true airspeed (TAS) is
not plausible keeps its place in the flight, and its TAS is replaced by linear
interpolation in time between the nearest trusted rows. Before the first and
after the last trusted row, the row takes the calibrated airspeed (CAS) of that
trusted row, converted to TAS at its own altitude. ``segment_duration`` and
``rocd`` are therefore unchanged, and ``acceleration`` is recomputed from the
TAS used.

A row is untrusted when its TAS is not finite, when its calibrated airspeed
(CAS) is below the BADA stall CAS at MTOW (CAS against CAS) or above the
aircraft's maximum operating speed VMO, or when its Mach number is at least
``DEFAULT_MAX_TRUSTED_MACH`` (1). VMO comes from the BADA model of the
attempt; a model without one uses ``DEFAULT_MAX_TRUSTED_CAS`` (400 kt) instead
(see ``max_trusted_cas``). The Mach limit is not the BADA MMO (see
``neats_default_parameters``).

When PyNEATS computes the TAS from the ground speed and the winds, trust is
decided, and the gaps are filled, on the unsmoothed 1-min TAS. The filled series
is smoothed with the Savitzky-Golay filter pycontrails applies to the ground
speed, and only the rows whose smoothing window holds an untrusted row take the
result; every other row keeps the TAS from the smoothed ground speed bit for
bit. A flight without an untrusted row keeps its smoothed TAS unchanged.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd
import pyBADA.atmosphere as atm
from numpy.typing import NDArray
from pycontrails.physics.jet import acceleration as pc_acceleration
from scipy.signal import savgol_filter

from pyneats.core.neats_default_parameters import DEFAULT_MAX_TRUSTED_CAS
from pyneats.core.neats_default_parameters import DEFAULT_MAX_TRUSTED_MACH
from pyneats.core.neats_default_parameters import (
    DEFAULT_MAX_UNTRUSTED_AIRSPEED_FRACTION,
)
from pyneats.core.neats_default_parameters import (
    DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER,
)
from pyneats.steps.performance.bada_adapters import BaseBADAAdapter
from pyneats.steps.performance.protocol import PerformanceStepError


logger = logging.getLogger(__name__)

__all__ = [
    "apply_airspeed_trust",
    "fill_untrusted",
    "hold_end_cas",
    "max_trusted_cas",
    "smooth_airspeed",
    "stall_cas",
    "untrusted_airspeed",
    "within_smoothing_window",
]


def stall_cas(adapter: BaseBADAAdapter, config: Literal["TO", "LD"]) -> float | None:
    """Return the BADA stall CAS [m/s] at MTOW [kg] in ``config``, or ``None``.

    ``None`` when the adapter gives no MTOW or no stall speed.
    """
    mtow = adapter.MTOW
    if mtow is None:
        return None
    return adapter.v_stall_cas(mtow, config)


def max_trusted_cas(adapter: BaseBADAAdapter) -> float:
    """Return the CAS [m/s] above which a TAS is untrusted.

    The BADA maximum operating speed VMO (``adapter.vmo_cas()``, CAS), with
    no margin. When the BADA model has no VMO, ``DEFAULT_MAX_TRUSTED_CAS``
    (400 kt) is used and a warning names the BADA model.
    """
    vmo = adapter.vmo_cas()
    if vmo is not None:
        return vmo
    logger.warning(
        "No BADA VMO for %s: too fast above CAS %.0f kt",
        adapter.bada_code,
        DEFAULT_MAX_TRUSTED_CAS * 3600.0 / 1852.0,
    )
    return DEFAULT_MAX_TRUSTED_CAS


def untrusted_airspeed(
    tas: NDArray[np.floating],
    altitude: NDArray[np.floating],
    delta_tau: NDArray[np.floating],
    v_stall_cas: float | None,
    *,
    max_cas: float,
    max_mach: float = DEFAULT_MAX_TRUSTED_MACH,
) -> NDArray[np.bool_]:
    """Return True where the TAS is untrusted.

    CAS [m/s] and Mach number are computed with pyBADA at the pressure
    ``altitude`` [m] and ``delta_tau`` [K], as the BADA adapters compute them.
    A row is untrusted when its ``tas`` [m/s] is not finite, its CAS is below
    ``v_stall_cas`` [m/s, CAS] or above ``max_cas`` [m/s, CAS], or its Mach
    number is ``max_mach`` or more. ``max_cas`` has no default: the step
    passes the VMO of the BADA model (``max_trusted_cas``), so no caller gets
    the 400 kt fallback by omission. ``v_stall_cas`` = ``None`` skips the
    stall test.
    """
    tas = np.asarray(tas, dtype=float)
    altitude = np.asarray(altitude, dtype=float)
    delta_tau = np.asarray(delta_tau, dtype=float)

    theta, delta, sigma = atm.atmosphereProperties(altitude, delta_tau)
    with np.errstate(invalid="ignore"):
        cas = np.asarray(atm.tas2Cas(tas, delta, sigma), dtype=float)
        mach = np.asarray(atm.tas2Mach(tas, theta), dtype=float)
        trusted = (
            np.isfinite(tas)
            & np.isfinite(cas)
            & np.isfinite(mach)
            & (cas <= max_cas)
            & (mach < max_mach)
        )
        if v_stall_cas is not None:
            trusted &= cas >= v_stall_cas
    return ~trusted


def fill_untrusted(
    values: NDArray[np.floating],
    untrusted: NDArray[np.bool_],
    time_s: NDArray[np.floating],
) -> NDArray[np.floating]:
    """Replace untrusted values by linear interpolation in time.

    ``time_s`` [s] must increase. Between two trusted rows the value is
    interpolated linearly in time; before the first and after the last trusted
    row the nearest trusted value is used. Trusted values are returned as is.
    """
    out = np.array(values, dtype=float, copy=True)
    trusted = ~untrusted
    if not trusted.any():
        raise ValueError("No trusted value to interpolate from")
    out[untrusted] = np.interp(time_s[untrusted], time_s[trusted], out[trusted])
    return out


def hold_end_cas(
    tas: NDArray[np.floating],
    untrusted: NDArray[np.bool_],
    altitude: NDArray[np.floating],
    delta_tau: NDArray[np.floating],
) -> NDArray[np.floating]:
    """Give the end runs the CAS of the nearest trusted row.

    Rows before the first and after the last trusted row take the CAS [m/s]
    of that trusted row, converted back to TAS [m/s] with their own pressure
    ``altitude`` [m] and ``delta_tau`` [K] (pyBADA ``atmosphereProperties``,
    ``tas2Cas`` and ``cas2Tas``, as in ``untrusted_airspeed``). A descent
    after a cruise anchor therefore keeps a constant CAS, and its TAS falls
    with the altitude. A row whose conversion is not finite (e.g. no
    altitude) takes the TAS of the trusted row. Other rows are returned as is.
    """
    out = np.array(tas, dtype=float, copy=True)
    trusted_idx = np.flatnonzero(~np.asarray(untrusted, dtype=bool))
    if trusted_idx.size == 0:
        raise ValueError("No trusted value to hold")
    first, last = int(trusted_idx[0]), int(trusted_idx[-1])
    if first == 0 and last == out.size - 1:
        return out

    _theta, delta, sigma = atm.atmosphereProperties(
        np.asarray(altitude, dtype=float), np.asarray(delta_tau, dtype=float)
    )
    delta = np.asarray(delta, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    for anchor, rows in ((first, slice(0, first)), (last, slice(last + 1, None))):
        n_rows = out[rows].size
        if n_rows == 0:
            continue
        with np.errstate(invalid="ignore"):
            cas = float(atm.tas2Cas(out[anchor], delta[anchor], sigma[anchor]))
            held = np.asarray(
                atm.cas2Tas(np.full(n_rows, cas), delta[rows], sigma[rows]),
                dtype=float,
            )
        out[rows] = np.where(np.isfinite(held), held, out[anchor])
    return out


def _sg_window(size: int, window_length: int) -> int:
    """Savitzky-Golay window [number of points] pycontrails uses for ``size`` points.

    Cut to ``size`` and made odd, as in pycontrails ``_sg_filter``.
    """
    window = min(window_length, size)
    if window % 2 == 0:
        window -= 1
    return window


def smooth_airspeed(
    tas: NDArray[np.floating],
    window_length: int,
    polyorder: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER,
) -> NDArray[np.floating]:
    """Savitzky-Golay smoothing, as pycontrails smooths the ground speed.

    Same rules as pycontrails ``_sg_filter``: the window [number of points] is
    cut to the series length and made odd; a series too short for the
    polynomial order gets its mean. ``tas`` [m/s] must not contain NaN.
    """
    tas = np.asarray(tas, dtype=float)
    window = _sg_window(tas.size, window_length)
    if window <= polyorder:
        return np.full_like(tas, np.nanmean(tas))
    return np.asarray(savgol_filter(tas, window, polyorder), dtype=float)


def within_smoothing_window(
    flags: NDArray[np.bool_],
    window_length: int,
    polyorder: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER,
) -> NDArray[np.bool_]:
    """Return True where the ``smooth_airspeed`` window of a row holds a flagged row.

    An interior row is smoothed over the ``window_length`` rows centred on it
    [number of points, cut and made odd as in ``smooth_airspeed``]; the first
    and last half-windows take a polynomial fitted to the first and last
    ``window_length`` rows (scipy ``savgol_filter``, ``mode="interp"``); a
    series too short for ``polyorder`` gets its mean (one window: the whole
    series). The smoothed value of a row outside the mask does not depend on
    the flagged rows.
    """
    flags = np.asarray(flags, dtype=bool)
    n = flags.size
    window = _sg_window(n, window_length)
    if window <= polyorder:
        return np.full(n, flags.any())
    half = window // 2
    near = np.convolve(flags.astype(int), np.ones(window, dtype=int), mode="same")
    out = near > 0
    out[:half] = flags[:window].any()
    out[n - half :] = flags[n - window :].any()
    return out


def apply_airspeed_trust(
    df: pd.DataFrame,
    adapter: BaseBADAAdapter,
    tas_unsmoothed: NDArray[np.floating] | None,
    *,
    stall_config: Literal["TO", "LD"],
    smoothing_window: int,
    max_untrusted_fraction: float = DEFAULT_MAX_UNTRUSTED_AIRSPEED_FRACTION,
    fail_when_mostly_untrusted: bool = True,
) -> tuple[pd.DataFrame, NDArray[np.bool_]]:
    """Replace untrusted true airspeeds in ``df``; no row is removed.

    Parameters
    ----------
    df : pd.DataFrame
        Preprocessed flight: ``time``, ``true_airspeed`` [m/s], ``altitude``
        [m, pressure altitude], ``delta_tau`` [K] and ``segment_duration``
        [s, forward, NaN at the last row]. Modified in place and returned.
    adapter : BaseBADAAdapter
        BADA adapter giving ``MTOW`` [kg], ``v_stall_cas()`` [m/s, CAS] and
        ``vmo_cas()`` [m/s, CAS]; see ``max_trusted_cas``.
    tas_unsmoothed : ndarray or None
        TAS [m/s] from the unsmoothed ground speed and the same winds, when
        PyNEATS computed ``true_airspeed`` (Savitzky-Golay smoothed ground
        speed). ``None`` when the TAS is provided (used as is, not smoothed).
    stall_config : {"TO", "LD"}
        BADA configuration of the stall speed at MTOW ("TO" or "LD").
    smoothing_window : int
        Savitzky-Golay window [number of points] of the computed TAS.
    max_untrusted_fraction : float
        Maximum fraction (dimensionless, [0, 1]) of the flight time (sum of
        ``segment_duration``) with an untrusted TAS.
    fail_when_mostly_untrusted : bool
        True: raise when more than ``max_untrusted_fraction`` of the flight
        time is untrusted, or when no row is trusted. False (the BADA fuel
        flow is not used): log a warning instead; the TAS is still replaced,
        except when no row is trusted, where it is kept as is.

    Returns
    -------
    tuple of (pd.DataFrame, ndarray of bool)
        ``df`` with, when a row is untrusted, the new ``true_airspeed`` [m/s]
        and ``acceleration`` [m/s^2] (forward difference of the TAS used); no
        column is added. The mask is True on the untrusted rows.

    Notes
    -----
    Trust is decided on ``tas_unsmoothed`` when given, else on
    ``true_airspeed``. Untrusted values between two trusted rows are replaced
    as in ``fill_untrusted``; untrusted values before the first and after the
    last trusted row take the CAS of that trusted row (``hold_end_cas``).
    A provided TAS keeps its trusted values. A computed TAS is filled on
    ``tas_unsmoothed``, the rows before the last are smoothed with
    ``smooth_airspeed``, and the rows whose smoothing window holds an
    untrusted row (``within_smoothing_window``) take the result. Those rows
    include trusted rows next to an untrusted one (up to half a window away,
    or anywhere in the first or last window of the flight): they are not in
    the mask, but their TAS can change, by more than 100 kt next to a slow
    stretch (the smoothed TAS before the step is pulled towards the slow
    minutes, the new one is not). All other rows keep their TAS bit for bit.

    Finally, rows before the first and after the last trusted row take the
    held-CAS value again, so the smoothing does not extrapolate a climb or
    descent across them.

    Known limits. The anchor row of an end run (first or last trusted row)
    can be re-smoothed, while the end run holds its unsmoothed CAS: the CAS
    can step at the boundary (a median of 22 kt at flight starts on the NM
    sample of 2025-07-09, up to about 100 kt) and ``acceleration`` has a
    one-row spike there. A trusted row is only as good as the limits: a
    "catch-up" minute after a frozen position, faster than the real speed
    but not above VMO (for example 250 kt to VMO near the ground), is
    trusted, and an end run copies its CAS. The interpolation is done in TAS
    while the altitude changes, and the last row copies the TAS of the row
    before it, so a few rows can end slightly above VMO after the step (26
    rows on 10 flights of the NM sample of 2025-07-09, at most 14 kt).

    The last row of a computed TAS has no forward segment (NaN TAS by the
    pycontrails convention), so it is always untrusted and takes the TAS of
    the row before it. Its ``segment_duration`` is NaN, so it adds no flight
    time.

    Raises
    ------
    PerformanceStepError
        Non-retryable, when ``fail_when_mostly_untrusted`` is True and no row
        is trusted or more than ``max_untrusted_fraction`` of the flight time
        is untrusted.
    """
    tas_observed = df["true_airspeed"].to_numpy(dtype=float, copy=True)
    basis = (
        tas_observed if tas_unsmoothed is None else np.asarray(tas_unsmoothed, float)
    )
    if basis.shape != tas_observed.shape:
        raise ValueError(
            f"Unsmoothed TAS has {basis.size} values for {tas_observed.size} rows"
        )

    v_stall = stall_cas(adapter, stall_config)
    if v_stall is None:
        logger.warning(
            "No BADA stall speed for %s (%s at MTOW): only non-finite and "
            "too-fast airspeeds are untrusted",
            adapter.bada_code,
            stall_config,
        )
    altitude = df["altitude"].to_numpy(dtype=float)
    delta_tau = df["delta_tau"].to_numpy(dtype=float)
    untrusted = untrusted_airspeed(
        basis, altitude, delta_tau, v_stall, max_cas=max_trusted_cas(adapter)
    )
    if not untrusted.any():
        return df, untrusted

    # Untrusted share of the flight time [s]; the last row (NaN duration)
    # adds no time.
    dt = df["segment_duration"].to_numpy(dtype=float)
    dt_known = np.nan_to_num(dt, nan=0.0)
    total = dt_known.sum()
    fraction = dt_known[untrusted].sum() / total if total > 0 else untrusted.mean()
    if untrusted.all() or fraction > max_untrusted_fraction:
        message = (
            f"Untrusted true airspeed on {fraction:.0%} of the flight time "
            f"({int(untrusted.sum())}/{untrusted.size} points; not finite, CAS "
            f"below the {stall_config} stall CAS at MTOW, above VMO or Mach >= 1; "
            f"> {max_untrusted_fraction:.0%} threshold)"
        )
        if fail_when_mostly_untrusted:
            raise PerformanceStepError(message, retryable=False)
        if untrusted.all():
            logger.warning("%s; no trusted row, true airspeed kept", message)
            return df, untrusted
        logger.warning("%s; true airspeed replaced, flight kept", message)

    time_s = (df["time"] - df["time"].iloc[0]).dt.total_seconds().to_numpy(float)
    filled = fill_untrusted(basis, untrusted, time_s)
    filled = hold_end_cas(filled, untrusted, altitude, delta_tau)

    if tas_unsmoothed is None:
        tas = filled
    else:
        # The last row (no forward segment) is not smoothed, as in pycontrails.
        tas = tas_observed.copy()
        resmooth = within_smoothing_window(untrusted[:-1], smoothing_window)
        if resmooth.any():
            smoothed = smooth_airspeed(filled[:-1], smoothing_window)
            tas[:-1][resmooth] = smoothed[resmooth]

    # End rule, again after the smoothing (its edge fit extrapolates a climb
    # or descent across the end runs): before the first and after the last
    # trusted row, the CAS of that trusted row, as filled.
    trusted_idx = np.flatnonzero(~untrusted)
    first, last = trusted_idx[0], trusted_idx[-1]
    tas[:first] = filled[:first]
    tas[last + 1 :] = filled[last + 1 :]
    if tas_unsmoothed is not None:
        # Last row: no forward segment (NaN TAS), takes the TAS of the row
        # before it.
        tas[-1] = tas[-2]

    logger.debug(
        "Replaced %d untrusted true airspeeds (%.1f%% of the flight time)",
        int(untrusted.sum()),
        100.0 * fraction,
    )
    df["true_airspeed"] = tas
    df["acceleration"] = pc_acceleration(tas, dt)
    return df, untrusted
