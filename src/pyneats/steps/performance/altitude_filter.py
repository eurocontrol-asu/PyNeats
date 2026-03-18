"""Altitude filter helper for the performance fallback mechanism.

Provides a function to filter low-altitude trajectory points from a
:class:`FlightWithWeather` view.  Used by :class:`BADAPerformanceModel`
when the first performance attempt fails — removing ground-level / taxi
points can allow the BADA model to succeed on a second try.
"""

from __future__ import annotations

from pycontrails import Flight
from pycontrails.physics.units import ft_to_m

from pyneats.core.neats_default_parameters import DEFAULT_MAX_ALTITUDE_FILTER_RATIO
from pyneats.core.neats_default_parameters import DEFAULT_MIN_ALTITUDE_FL
from pyneats.steps.performance.protocol import PerformanceStepError
from pyneats.steps.weather.weather_provider import FlightWithWeather


__all__ = ["filter_low_altitude_points"]


def filter_low_altitude_points(
    flight: FlightWithWeather,
    min_altitude_fl: float = DEFAULT_MIN_ALTITUDE_FL,
    max_filter_ratio: float = DEFAULT_MAX_ALTITUDE_FILTER_RATIO,
) -> FlightWithWeather:
    """Filter trajectory points below *min_altitude_fl* and return a new view.

    At this pipeline stage altitude is already in **metres**, so the FL
    threshold is converted: ``FL x 100 x 0.3048``.

    Parameters
    ----------
    flight : FlightWithWeather
        Flight data with weather columns.
    min_altitude_fl : float
        Minimum Flight Level (inclusive).  Default ``DEFAULT_MIN_ALTITUDE_FL``.
    max_filter_ratio : float
        Maximum fraction of points that may be removed.  If exceeded the
        flight is considered un-recoverable.

    Raises
    ------
    PerformanceStepError
        If no low-altitude points exist (nothing to filter) or if more
        than *max_filter_ratio* of points would be removed.
    """
    min_alt_m: float = ft_to_m(min_altitude_fl * 100)  # FL → ft → m
    df = flight.dataframe
    mask = df["altitude"] >= min_alt_m
    n_filtered = int((~mask).sum())

    if n_filtered == 0:
        raise PerformanceStepError(
            "No low-altitude points to filter — altitude fallback inapplicable",
            retryable=False,
        )

    if n_filtered / len(df) > max_filter_ratio:
        raise PerformanceStepError(
            f"Too many points below FL{min_altitude_fl} "
            f"({n_filtered}/{len(df)}, >{max_filter_ratio:.0%} threshold)",
            retryable=False,
        )

    filtered_df = df.loc[mask].reset_index(drop=True)
    filtered = Flight(data=filtered_df, attrs={**flight.attrs}, fuel=flight.fuel)
    return FlightWithWeather.from_flight(filtered)
