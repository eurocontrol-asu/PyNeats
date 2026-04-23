"""PyNEATS geometry integration tests.

This module tests geometry edge cases through PyNEATS's actual API layers,
rather than testing pycontrails functions directly. This validates that:

1. PyNEATS configuration (buffers, params) is applied correctly
2. Geometry bugs in pycontrails propagate through PyNEATS as expected
3. The full call chain (PyNEATS → pycontrails) works correctly

Tests are organized by PyNEATS step:
- WeatherProvider.downselect() - met data downselection
- WeatherProvider.run() - weather intersection
- PyContrailsInterpolator.run() - trajectory resampling

Run with:
    pytest tests/test_geometry_integration.py -v
    pytest -m "geometry and integration"
"""

from __future__ import annotations

import numpy as np
import pytest

from pyneats.steps.interpolation.pycontrails_interpolation import (
    PyContrailsInterpolationParams,
)
from pyneats.steps.interpolation.pycontrails_interpolation import (
    PyContrailsInterpolator,
)
from pyneats.steps.weather.weather_provider import WeatherProvider
from pyneats.steps.weather.weather_provider import WeatherProviderParams

from .geometry_test_utils import compute_antimeridian_span


# ============================================================================
# WeatherProvider Integration Tests
# ============================================================================


@pytest.mark.geometry
@pytest.mark.integration
@pytest.mark.xfail(
    strict=True,
    reason="FM-2: downselect_met() antimeridian over-fetch bug propagates through WeatherProvider",
)
def test_weather_provider_downselect_antimeridian_overfetch(
    tokyo_la_flight, minimal_met
):
    """Integration: WeatherProvider.downselect() with antimeridian flight.

    This tests the FULL PyNEATS call chain:
    WeatherProvider.downselect() → flight.downselect_met() → pycontrails bug

    Expected: FM-2 over-fetch bug propagates through PyNEATS
    Measured: Met data fetched through PyNEATS WeatherProvider API
    """
    # Create WeatherProvider with realistic config
    weather_params = WeatherProviderParams(
        lon_buf=(5.0, 5.0),  # degrees - typical PyNEATS buffer
        lat_buf=(5.0, 5.0),
        time_buf=(np.timedelta64(1, "h"), np.timedelta64(1, "h")),
        level_buf=(5000.0, 5000.0),  # Pa
        method="linear",
        use_indices=False,
        var_map={
            "air_temperature": "air_temperature",
            "eastward_wind": "u_wind",
            "northward_wind": "v_wind",
            "specific_humidity": "specific_humidity",
        },
    )

    provider = WeatherProvider(
        met=minimal_met,
        rad=minimal_met,  # Use same dataset for simplicity
        wind=None,
        params=weather_params,
    )

    # Call downselect through PyNEATS API (not direct pycontrails)
    downselected_met = provider.downselect(tokyo_la_flight, minimal_met)

    # Measure over-fetch
    traj_lons = tokyo_la_flight["longitude"]
    traj_span = compute_antimeridian_span(traj_lons)

    met_lons = downselected_met.data["longitude"].values
    met_span = len(met_lons) * 10  # 10° grid resolution

    # Expected: trajectory span + 2×buffer + tolerance
    lon_buf = weather_params.lon_buf[0]
    expected_max_span = traj_span + 2 * lon_buf + 50  # 50° tolerance

    # Report
    print("\n" + "=" * 70)
    print("Integration Test: PyNEATS WeatherProvider.downselect()")
    print("=" * 70)
    print("  Flight route: Tokyo → Los Angeles (antimeridian crossing)")
    print(f"  Trajectory lon span: {traj_span:.2f}°")
    print(f"  Config lon buffer: {lon_buf}° (each side)")
    print(f"  Expected max met span: {expected_max_span:.2f}°")
    print(f"  Actual met span: {met_span:.2f}° ({len(met_lons)} grid points)")
    print(f"  Over-fetch: {met_span > expected_max_span}")
    print(f"  Over-fetch ratio: {met_span / expected_max_span:.2f}x")
    print("=" * 70)

    # Assert: FM-2 bug should propagate through PyNEATS
    # This test is EXPECTED to FAIL due to the pycontrails bug
    assert met_span < expected_max_span, (
        f"PyNEATS WeatherProvider over-fetched: {met_span:.2f}° vs expected {expected_max_span:.2f}°"
    )


@pytest.mark.geometry
@pytest.mark.integration
def test_weather_provider_run_antimeridian(tokyo_la_flight, minimal_met):
    """Integration: WeatherProvider.run() with antimeridian flight.

    Tests the full weather intersection pipeline through PyNEATS:
    WeatherProvider.run() → downselect → intersect_met → FlightWithWeather

    Validates:
    - No errors during antimeridian processing
    - All weather variables are interpolated
    - No NaN/invalid values in output
    """
    # Create WeatherProvider
    weather_params = WeatherProviderParams(
        lon_buf=(5.0, 5.0),
        lat_buf=(5.0, 5.0),
        time_buf=(np.timedelta64(1, "h"), np.timedelta64(1, "h")),
        level_buf=(5000.0, 5000.0),
        method="linear",
        use_indices=False,
        var_map={
            "air_temperature": "air_temperature",
            "eastward_wind": "u_wind",
            "northward_wind": "v_wind",
            "specific_humidity": "specific_humidity",
        },
    )

    provider = WeatherProvider(
        met=minimal_met,
        rad=minimal_met,
        wind=None,
        params=weather_params,
    )

    # Run full weather intersection pipeline
    try:
        flight_with_weather = provider.run(tokyo_la_flight)
    except Exception as e:
        pytest.fail(f"WeatherProvider.run() raised exception: {e}")

    # Validate output
    assert flight_with_weather is not None
    assert len(flight_with_weather) == len(tokyo_la_flight)

    # Check that all weather variables were added
    for output_col in weather_params.var_map.values():
        assert output_col in flight_with_weather.data, f"Missing column: {output_col}"

        # Check for invalid values
        values = flight_with_weather[output_col]
        has_nan = np.isnan(values).any()
        has_inf = np.isinf(values).any()

        # Report
        print(f"\n  Weather variable: {output_col}")
        print(f"    Range: [{values.min():.2f}, {values.max():.2f}]")
        print(f"    Has NaN: {has_nan}")
        print(f"    Has inf: {has_inf}")

        # Wind variables are allowed to have NaN (filled with 0)
        if output_col in ["eastward_wind", "northward_wind"]:
            continue  # Skip NaN check for wind

        assert not has_nan, f"{output_col} contains NaN values"
        assert not has_inf, f"{output_col} contains inf values"

    print("\n" + "=" * 70)
    print("Integration Test: PyNEATS WeatherProvider.run() PASSED")
    print("=" * 70)


@pytest.mark.geometry
@pytest.mark.integration
def test_weather_provider_polar_flight(polar_flight, minimal_met):
    """Integration: WeatherProvider with polar flight (85°N).

    Tests that PyNEATS correctly processes high-latitude flights:
    - No coordinate escape beyond ±90°
    - No NaN/inf in interpolated weather
    - Proper handling near pole singularities
    """
    # Create WeatherProvider
    weather_params = WeatherProviderParams(
        lon_buf=(5.0, 5.0),
        lat_buf=(5.0, 5.0),
        time_buf=(np.timedelta64(1, "h"), np.timedelta64(1, "h")),
        level_buf=(5000.0, 5000.0),
        method="linear",
        use_indices=False,
        var_map={
            "air_temperature": "air_temperature",
            "eastward_wind": "u_wind",
            "northward_wind": "v_wind",
            "specific_humidity": "specific_humidity",
        },
    )

    provider = WeatherProvider(
        met=minimal_met,
        rad=minimal_met,
        wind=None,
        params=weather_params,
    )

    # Run weather intersection
    try:
        flight_with_weather = provider.run(polar_flight)
    except Exception as e:
        pytest.fail(f"WeatherProvider.run() raised exception for polar flight: {e}")

    # Validate coordinates didn't escape
    result_lats = flight_with_weather["latitude"]
    lat_escaped = (result_lats > 90) | (result_lats < -90)

    # Validate weather data
    temps = flight_with_weather["air_temperature"]
    has_nan = np.isnan(temps).any()
    has_inf = np.isinf(temps).any()

    # Report
    print("\n" + "=" * 70)
    print("Integration Test: PyNEATS Polar Flight Weather")
    print("=" * 70)
    print(
        f"  Input latitude range: [{polar_flight['latitude'].min():.2f}°, {polar_flight['latitude'].max():.2f}°]"
    )
    print(
        f"  Output latitude range: [{result_lats.min():.2f}°, {result_lats.max():.2f}°]"
    )
    print(f"  Latitude escape: {lat_escaped.sum()} waypoints")
    print(f"  Temperature range: [{temps.min():.2f} K, {temps.max():.2f} K]")
    print(f"  Temperature has NaN: {has_nan}")
    print(f"  Temperature has inf: {has_inf}")
    print("=" * 70)

    # Assert
    assert not lat_escaped.any(), (
        f"Latitudes escaped [-90, 90]: {result_lats[lat_escaped]}"
    )
    assert not has_nan, "Temperature contains NaN values"
    assert not has_inf, "Temperature contains inf values"


# ============================================================================
# PyContrailsInterpolator Integration Tests
# ============================================================================


@pytest.mark.geometry
@pytest.mark.integration
def test_interpolator_antimeridian(tokyo_la_flight):
    """Integration: PyContrailsInterpolator with antimeridian flight.

    Tests trajectory resampling through PyNEATS:
    PyContrailsInterpolator.run() → flight.resample_and_fill() → pycontrails

    Validates:
    - No errors during antimeridian resampling
    - Longitudes stay in [-180, 180]
    - No coordinate discontinuities at ±180°
    """
    # Create interpolator with realistic config
    interp_params = PyContrailsInterpolationParams(
        interpolation_time="5min",  # Resample to 5-minute intervals
    )

    interpolator = PyContrailsInterpolator(params=interp_params)

    # Run interpolation through PyNEATS API
    try:
        resampled = interpolator.run(tokyo_la_flight)
    except Exception as e:
        pytest.fail(f"PyContrailsInterpolator.run() raised exception: {e}")

    # Validate output
    assert resampled is not None
    assert len(resampled) >= len(tokyo_la_flight)  # Should have more points

    # Check longitude validity
    result_lons = resampled["longitude"]
    out_of_range = (result_lons > 180) | (result_lons < -180)

    # Check for longitude discontinuities (jumps > 180° indicate wrapping issues)
    lon_diffs = np.abs(np.diff(result_lons))
    discontinuities = lon_diffs > 180

    # Report
    print("\n" + "=" * 70)
    print("Integration Test: PyNEATS PyContrailsInterpolator")
    print("=" * 70)
    print(f"  Input waypoints: {len(tokyo_la_flight)}")
    print(f"  Output waypoints: {len(resampled)}")
    print(f"  Longitude range: [{result_lons.min():.2f}°, {result_lons.max():.2f}°]")
    print(f"  Out of range: {out_of_range.sum()} waypoints")
    print(f"  Discontinuities (>180° jumps): {discontinuities.sum()}")
    print("=" * 70)

    # Assert
    assert not out_of_range.any(), (
        f"Longitudes outside [-180, 180]: {result_lons[out_of_range]}"
    )
    assert discontinuities.sum() <= 1, (
        "Multiple longitude discontinuities detected (expected ≤1 for antimeridian crossing)"
    )


@pytest.mark.geometry
@pytest.mark.integration
def test_interpolator_polar(polar_flight):
    """Integration: PyContrailsInterpolator with polar flight.

    Tests trajectory resampling at high latitudes:
    - No latitude escape beyond ±90°
    - Proper interpolation near meridian convergence
    """
    # Create interpolator
    interp_params = PyContrailsInterpolationParams(
        interpolation_time="5min",
    )

    interpolator = PyContrailsInterpolator(params=interp_params)

    # Run interpolation
    try:
        resampled = interpolator.run(polar_flight)
    except Exception as e:
        pytest.fail(
            f"PyContrailsInterpolator.run() raised exception for polar flight: {e}"
        )

    # Validate coordinates
    result_lats = resampled["latitude"]
    lat_escaped = (result_lats > 90) | (result_lats < -90)

    # Report
    print("\n" + "=" * 70)
    print("Integration Test: PyNEATS Polar Flight Interpolation")
    print("=" * 70)
    print(f"  Input waypoints: {len(polar_flight)}")
    print(f"  Output waypoints: {len(resampled)}")
    print(f"  Latitude range: [{result_lats.min():.2f}°, {result_lats.max():.2f}°]")
    print(f"  Latitude escape: {lat_escaped.sum()} waypoints")
    print("=" * 70)

    # Assert
    assert not lat_escaped.any(), (
        f"Latitudes escaped [-90, 90]: {result_lats[lat_escaped]}"
    )


# ============================================================================
# Configuration Validation Tests
# ============================================================================


@pytest.mark.geometry
@pytest.mark.integration
def test_weather_provider_buffer_types(tokyo_la_flight, minimal_met):
    """Validate that PyNEATS correctly handles buffer type conversions.

    Ensures that config buffers (tuples of floats/Timedeltas) are properly
    passed to pycontrails without type errors.
    """
    # Test with various buffer configurations
    buffer_configs = [
        # (lon_buf, lat_buf, time_buf, level_buf)
        (
            (5.0, 5.0),
            (5.0, 5.0),
            (np.timedelta64(1, "h"), np.timedelta64(1, "h")),
            (5000.0, 5000.0),
        ),
        (
            (10.0, 10.0),
            (3.0, 3.0),
            (np.timedelta64(2, "h"), np.timedelta64(2, "h")),
            (3000.0, 3000.0),
        ),
        (
            (0.0, 5.0),
            (0.0, 5.0),
            (np.timedelta64(30, "m"), np.timedelta64(30, "m")),
            (1000.0, 5000.0),
        ),  # Asymmetric
    ]

    for lon_buf, lat_buf, time_buf, level_buf in buffer_configs:
        weather_params = WeatherProviderParams(
            lon_buf=lon_buf,
            lat_buf=lat_buf,
            time_buf=time_buf,
            level_buf=level_buf,
            method="linear",
            use_indices=False,
            var_map={"air_temperature": "air_temperature"},
        )

        provider = WeatherProvider(
            met=minimal_met,
            rad=minimal_met,
            wind=None,
            params=weather_params,
        )

        # Should not raise type errors
        try:
            downselected = provider.downselect(tokyo_la_flight, minimal_met)
            assert downselected is not None
        except TypeError as e:
            pytest.fail(
                f"Buffer type error with config {lon_buf}, {lat_buf}, {time_buf}, {level_buf}: {e}"
            )

    print("\n✓ All buffer configurations handled correctly")
