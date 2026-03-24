"""Speed filter — removes trajectory points below VStall threshold.

Provides a function to filter low-speed trajectory points from a
:class:`FlightWithWeather` view using the BADA adapter's stall speed.
"""

from __future__ import annotations

import logging

from pycontrails import Flight

from pyneats.steps.performance.protocol import PerformanceStepError
from pyneats.steps.weather.weather_provider import FlightWithWeather


logger = logging.getLogger(__name__)

__all__ = ["filter_low_speed_points"]


def filter_low_speed_points(
    flight: FlightWithWeather,
    adapter: object,
    max_filter_ratio: float = 0.8,
) -> FlightWithWeather:
    """Filter trajectory points with TAS below VStall.

    Parameters
    ----------
    flight : FlightWithWeather
        Flight data with weather columns.
    adapter : BaseBADAAdapter
        BADA adapter providing ``v_stall_cas()`` and ``MTOW``.
    max_filter_ratio : float
        Maximum fraction of points that may be removed.

    Returns
    -------
    FlightWithWeather
        Filtered flight, or original if filter is skipped.

    Raises
    ------
    PerformanceStepError
        If no slow points exist or too many would be removed.
    """
    mtow = getattr(adapter, "MTOW", None)
    if mtow is None:
        logger.warning("Adapter has no MTOW — skipping speed filter")
        return flight

    v_stall = adapter.v_stall_cas(mtow, "TO")  # type: ignore[union-attr]
    if v_stall is None:
        return flight

    df = flight.dataframe
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

    filtered_df = df.loc[mask].reset_index(drop=True)
    filtered = Flight(data=filtered_df, attrs={**flight.attrs}, fuel=flight.fuel)
    return FlightWithWeather.from_flight(filtered)
