"""Speed filter — removes trajectory points below VStall threshold.

Provides a function to filter low-speed trajectory points from a
preprocessed DataFrame using the BADA adapter's stall speed.
"""

from __future__ import annotations

import logging

import pandas as pd

from pyneats.steps.performance.protocol import PerformanceStepError


logger = logging.getLogger(__name__)

__all__ = ["filter_low_speed_points"]


def filter_low_speed_points(
    df: pd.DataFrame,
    adapter: object,
    max_filter_ratio: float = 0.8,
) -> pd.DataFrame:
    """Filter trajectory points with TAS below VStall.

    Parameters
    ----------
    df : pd.DataFrame
        Preprocessed DataFrame with ``true_airspeed`` column (m/s).
    adapter : BaseBADAAdapter
        BADA adapter providing ``v_stall_cas()`` and ``MTOW``.
    max_filter_ratio : float
        Maximum fraction of points that may be removed.

    Returns
    -------
    pd.DataFrame
        Filtered DataFrame, or original if filter is skipped.

    Raises
    ------
    PerformanceStepError
        If no slow points exist or too many would be removed.
    """
    mtow = getattr(adapter, "MTOW", None)
    if mtow is None:
        logger.warning("Adapter has no MTOW — skipping speed filter")
        return df

    v_stall = adapter.v_stall_cas(mtow, "TO")  # type: ignore[union-attr]
    if v_stall is None:
        return df

    mask = df["true_airspeed"] >= v_stall
    n_filtered = int((~mask).sum())

    if n_filtered == 0:
        raise PerformanceStepError(
            "No low-speed points to filter — speed fallback inapplicable",
            retryable=False,
        )

    if n_filtered / len(df) > max_filter_ratio:
        raise PerformanceStepError(
            f"Too many points below VStall={v_stall:.1f} m/s "
            f"({n_filtered}/{len(df)}, >{max_filter_ratio:.0%} threshold)",
            retryable=False,
        )

    return df.loc[mask].reset_index(drop=True)
