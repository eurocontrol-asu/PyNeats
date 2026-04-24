"""Geometry failure mode tests for pycontrails delegation in PyNEATS.

This module tests 7 known geometry failure modes in pycontrails that may
affect PyNEATS trajectory processing:

- FM-1: spatial_bounding_box() antimeridian bug
- FM-2: GeoVectorDataset.downselect_met() antimeridian over-fetch
- FM-3: MetDataset.downselect(bbox) antimeridian handling (should work)
- FM-4: advect_longitude() antimeridian wrapping
- FM-5: advect_longitude_and_latitude_near_poles() polar handling
- FM-6: Polar latitude escape beyond ±90°
- FM-7: GeoVectorDataset longitude validation

Each test:
1. Creates synthetic test data (no external dependencies)
2. Calls pycontrails functions directly (no mocking)
3. Measures actual outputs
4. Reports numeric values (not just PASS/FAIL)
5. Asserts quantitative pass criteria

Run with:
    pytest tests/test_geometry_failure_modes.py -v
    pytest tests/test_geometry_failure_modes.py::test_fm1_antimeridian_bbox -v -s
    pytest -m geometry
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# Version-aware imports with graceful fallback
try:
    from pycontrails.core.geo import spatial_bounding_box
except (ImportError, AttributeError):
    spatial_bounding_box = None

try:
    from pycontrails.physics.geo import advect_longitude
except (ImportError, AttributeError):
    advect_longitude = None

try:
    from pycontrails.physics.geo import advect_longitude_and_latitude_near_poles
except (ImportError, AttributeError):
    advect_longitude_and_latitude_near_poles = None

# Standard pycontrails imports (always available)
from pycontrails import Flight

# Import test utilities
from .geometry_test_utils import compute_antimeridian_span


# ============================================================================
# FM-1: spatial_bounding_box() antimeridian bug
# ============================================================================


@pytest.mark.geometry
@pytest.mark.xfail(
    strict=True, reason="FM-1: spatial_bounding_box() antimeridian bug in pycontrails"
)
@pytest.mark.skipif(
    spatial_bounding_box is None,
    reason="spatial_bounding_box not available in this pycontrails version",
)
def test_fm1_antimeridian_bbox(tokyo_la_flight):
    """FM-1: spatial_bounding_box() antimeridian crossing bug.

    Expected: Bbox with west > east (e.g., west=165, east=-155)
    Bug behavior: Returns west < east with ~342° span

    Pass criteria:
        - Correctly detects antimeridian crossing (west > east)
        - Longitude span < 180°
        - Span error < 10° from true span
    """
    lons = tokyo_la_flight["longitude"].values
    lats = tokyo_la_flight["latitude"].values

    # Execute
    bbox = spatial_bounding_box(lons, lats)
    west, south, east, north = bbox

    # Measure
    crosses_antimeridian = west > east
    if crosses_antimeridian:
        lon_span = (east - west) % 360
    else:
        lon_span = east - west

    true_span = compute_antimeridian_span(lons)

    # Report
    print("\n" + "=" * 70)
    print("FM-1 Results: spatial_bounding_box() antimeridian")
    print("=" * 70)
    print(
        f"  Bbox: west={west:.2f}°, south={south:.2f}°, east={east:.2f}°, north={north:.2f}°"
    )
    print(f"  Crosses antimeridian: {crosses_antimeridian}")
    print(f"  Computed lon span: {lon_span:.2f}°")
    print(f"  True lon span: {true_span:.2f}°")
    print(f"  Input lon range: [{lons.min():.2f}°, {lons.max():.2f}°]")
    print(f"  Span error: {abs(lon_span - true_span):.2f}°")
    print("=" * 70)

    # Assert
    assert crosses_antimeridian, (
        "Bbox should indicate antimeridian crossing (west > east)"
    )
    assert lon_span < 180, f"Longitude span {lon_span:.2f}° should be < 180°"
    assert abs(lon_span - true_span) < 10, (
        f"Span error: {abs(lon_span - true_span):.2f}°"
    )


# ============================================================================
# FM-2: GeoVectorDataset.downselect_met() antimeridian over-fetch
# ============================================================================


@pytest.mark.geometry
@pytest.mark.xfail(
    strict=True,
    reason="FM-2: downselect_met() antimeridian over-fetch bug in pycontrails",
)
def test_fm2_downselect_met_overfetch(tokyo_la_flight, minimal_met):
    """FM-2: downselect_met() over-fetches met data for antimeridian flights.

    Expected: Met slice ~118° wide (trajectory span + 2xbuffer)
    Bug behavior: Met slice ~360° wide (entire global longitude range)

    Pass criteria: met_width < trajectory_width + 2xbuffer + 50° tolerance
    """
    lon_buffer = 5.0  # degrees
    lat_buffer = 5.0

    # Execute
    met_slice = tokyo_la_flight.downselect_met(
        minimal_met,
        longitude_buffer=(lon_buffer, lon_buffer),
        latitude_buffer=(lat_buffer, lat_buffer),
        time_buffer=(np.timedelta64(1, "h"), np.timedelta64(1, "h")),
    )

    # Measure
    traj_lons = tokyo_la_flight["longitude"]  # Already a numpy array
    traj_span = compute_antimeridian_span(traj_lons)

    met_lons = met_slice.data[
        "longitude"
    ].values  # This is xarray, so .values is correct
    met_span = len(met_lons) * 10  # 10° grid resolution

    expected_max_span = traj_span + 2 * lon_buffer + 50  # 50° tolerance

    # Report
    print("\n" + "=" * 70)
    print("FM-2 Results: downselect_met() antimeridian over-fetch")
    print("=" * 70)
    print(f"  Trajectory lon span: {traj_span:.2f}°")
    print(f"  Met slice lon points: {len(met_lons)} (span ~{met_span:.2f}°)")
    print(f"  Expected max span: {expected_max_span:.2f}°")
    print(f"  Over-fetch: {met_span > expected_max_span}")
    print(f"  Over-fetch ratio: {met_span / expected_max_span:.2f}x")
    print("=" * 70)

    # Assert
    assert met_span < expected_max_span, (
        f"Met slice {met_span:.2f}° exceeds expected {expected_max_span:.2f}°"
    )


# ============================================================================
# FM-3: MetDataset.downselect(bbox) antimeridian handling (should PASS)
# ============================================================================


@pytest.mark.geometry
def test_fm3_metdataset_downselect_bbox(minimal_met):
    """FM-3: MetDataset.downselect(bbox) correctly handles antimeridian.

    Expected: PASS - This function correctly handles antimeridian
    Bug behavior: Should work correctly in pycontrails 0.60.2

    Pass criteria: Selected lons match both sides of antimeridian bbox
    """
    # Antimeridian-crossing bbox (Tokyo→LA envelope)
    bbox = (165.0, 30.0, -155.0, 45.0)  # west > east

    # Execute
    selected = minimal_met.downselect(bbox=bbox)

    # Measure
    selected_lons = selected.data["longitude"].values
    west_lons = selected_lons[selected_lons >= 165]
    east_lons = selected_lons[selected_lons <= -155]

    # Report
    print("\n" + "=" * 70)
    print("FM-3 Results: MetDataset.downselect(bbox) antimeridian (should PASS)")
    print("=" * 70)
    print(f"  Bbox: {bbox} (west > east)")
    print(f"  Selected lons: {sorted(selected_lons)}")
    print(f"  West side (≥165°): {west_lons}")
    print(f"  East side (≤-155°): {east_lons}")
    print(f"  Total selected: {len(selected_lons)} points")
    print("=" * 70)

    # Assert
    assert len(west_lons) > 0, "Should select western longitudes (≥165°)"
    assert len(east_lons) > 0, "Should select eastern longitudes (≤-155°)"


# ============================================================================
# FM-4: advect_longitude() antimeridian wrapping
# ============================================================================


@pytest.mark.geometry
@pytest.mark.skipif(
    advect_longitude is None,
    reason="advect_longitude not available in this pycontrails version",
)
def test_fm4_advect_longitude_wrap():
    """FM-4: advect_longitude() antimeridian wrapping.

    Expected: Advected lons wrapped to [-180, 180]
    Bug behavior: May produce lon > 180 or lon < -180

    Pass criteria: All advected lons in [-180, 180]
    """
    # Particles near antimeridian, strong eastward wind
    initial_lons = np.array([170.0, 175.0, 179.0, -179.0, -175.0])
    lats = np.array([40.0, 40.0, 40.0, 40.0, 40.0])
    u_wind = np.array([50.0, 50.0, 50.0, 50.0, 50.0])  # m/s eastward
    dt = np.timedelta64(3600, "s")  # 1 hour

    # Execute
    advected_lons = advect_longitude(initial_lons, lats, u_wind, dt)

    # Measure
    out_of_range = (advected_lons > 180) | (advected_lons < -180)

    # Report
    print("\n" + "=" * 70)
    print("FM-4 Results: advect_longitude() antimeridian wrapping")
    print("=" * 70)
    print(f"  Initial lons: {initial_lons}")
    print(f"  Advected lons: {advected_lons}")
    print(f"  Range: [{advected_lons.min():.2f}°, {advected_lons.max():.2f}°]")
    print(f"  Out of range: {out_of_range.sum()} / {len(advected_lons)}")
    if out_of_range.any():
        print(f"  Out-of-range values: {advected_lons[out_of_range]}")
    print("=" * 70)

    # Assert
    assert not out_of_range.any(), (
        f"Advected lons outside [-180, 180]: {advected_lons[out_of_range]}"
    )


# ============================================================================
# FM-5: advect_longitude_and_latitude_near_poles() polar handling
# ============================================================================


@pytest.mark.geometry
@pytest.mark.skipif(
    advect_longitude_and_latitude_near_poles is None,
    reason="advect_longitude_and_latitude_near_poles not available in this pycontrails version",
)
def test_fm5_polar_advection():
    """FM-5: Polar advection numerical stability.

    Expected: Stable lat/lon near poles, lats in [-90, 90]
    Bug behavior: May produce NaN, inf, or lat > 90°

    Pass criteria: No NaN/inf, all lats in [-90, 90]
    """
    # High-latitude coordinates
    lons = np.array([0.0, 30.0, 60.0, 90.0])
    lats = np.array([82.0, 85.0, 88.0, 89.0])

    # Simulate wind at poles
    u_wind = np.array([20.0, 20.0, 20.0, 20.0])  # m/s eastward
    v_wind = np.array([10.0, 10.0, 10.0, 10.0])  # m/s northward
    dt = np.timedelta64(3600, "s")  # 1 hour

    # Execute
    try:
        advected_lons, advected_lats = advect_longitude_and_latitude_near_poles(
            lons, lats, u_wind, v_wind, dt
        )
    except Exception as e:
        pytest.fail(f"Polar advection raised exception: {e}")

    # Measure
    has_nan = np.isnan(advected_lats).any() or np.isnan(advected_lons).any()
    has_inf = np.isinf(advected_lats).any() or np.isinf(advected_lons).any()
    lat_escaped = (advected_lats > 90) | (advected_lats < -90)

    # Report
    print("\n" + "=" * 70)
    print("FM-5 Results: Polar advection stability")
    print("=" * 70)
    print(f"  Initial lats: {lats}")
    print(f"  Advected lats: {advected_lats}")
    print(f"  Initial lons: {lons}")
    print(f"  Advected lons: {advected_lons}")
    print(f"  Has NaN: {has_nan}")
    print(f"  Has inf: {has_inf}")
    print(f"  Lat escape count: {lat_escaped.sum()}")
    if lat_escaped.any():
        print(f"  Escaped values: {advected_lats[lat_escaped]}")
    print("=" * 70)

    # Assert
    assert not has_nan, "Advected coordinates contain NaN"
    assert not has_inf, "Advected coordinates contain inf"
    assert not lat_escaped.any(), (
        f"Latitudes escaped [-90, 90]: {advected_lats[lat_escaped]}"
    )


# ============================================================================
# FM-6: Polar latitude escape beyond ±90°
# ============================================================================


@pytest.mark.geometry
def test_fm6_polar_lat_escape(polar_flight, minimal_met):
    """FM-6: Latitude escape beyond ±90° in polar operations.

    Expected: Lats clamped to 90° OR warning/end-of-life flag
    Bug behavior: Lat silently escapes > 90° with no indication

    Pass criteria: All lats in [-90, 90] after intersect_met
    """
    # Extract MetDataArray from MetDataset
    # intersect_met expects a MetDataArray (xr.DataArray with met metadata)
    from pycontrails.core.met import MetDataArray

    temp_mda = MetDataArray(minimal_met.data["air_temperature"])

    # Execute
    try:
        polar_flight.intersect_met(temp_mda, method="linear")
    except Exception as e:
        pytest.fail(f"intersect_met raised exception: {e}")

    # Measure
    result_lats = polar_flight["latitude"]  # Already a numpy array
    escaped = (result_lats > 90) | (result_lats < -90)

    # Report
    print("\n" + "=" * 70)
    print("FM-6 Results: Polar latitude escape")
    print("=" * 70)
    print(f"  Latitude range: [{result_lats.min():.2f}°, {result_lats.max():.2f}°]")
    print(f"  All latitudes: {result_lats}")
    print(f"  Escaped count: {escaped.sum()}")
    if escaped.any():
        print(f"  Escaped values: {result_lats[escaped]}")
    print("=" * 70)

    # Assert
    assert not escaped.any(), f"Latitudes escaped [-90, 90]: {result_lats[escaped]}"


# ============================================================================
# FM-7: GeoVectorDataset longitude validation
# ============================================================================


@pytest.mark.geometry
def test_fm7_longitude_validation():
    """FM-7: GeoVectorDataset longitude validation.

    Expected: Rejects lon outside [-180, 180] OR auto-normalizes
    Bug behavior: Unknown - depends on implementation

    Pass criteria: Either ValueError raised OR lons normalized to [-180, 180]
    """
    # Invalid longitude data
    invalid_data = {
        "longitude": np.array([181.0, 185.0, 270.0, -185.0]),
        "latitude": np.array([0.0, 10.0, 20.0, 30.0]),
        "altitude": np.array([35000.0] * 4),
        "time": pd.date_range("2023-06-15 10:00:00", periods=4, freq="5min"),
    }

    # Try to create Flight
    error_raised = False
    normalized = False
    result_lons = None

    try:
        flight = Flight(data=invalid_data)
        result_lons = flight["longitude"].values
        normalized = np.all((result_lons >= -180) & (result_lons <= 180))
    except ValueError as e:
        error_raised = True
        error_msg = str(e)

    # Report
    print("\n" + "=" * 70)
    print("FM-7 Results: GeoVectorDataset longitude validation")
    print("=" * 70)
    print(f"  Input lons: {invalid_data['longitude']}")

    if error_raised:
        print(f"  ValueError raised (GOOD): {error_msg}")
        print("  Validation works correctly")
    else:
        print("  No error raised")
        print(f"  Result lons: {result_lons}")
        print(f"  Normalized: {normalized}")

        if normalized:
            print("  Auto-normalization works correctly")
        else:
            print(
                "  WARNING: Invalid lons accepted without validation or normalization"
            )

    print("=" * 70)

    # Assert: Either error raised OR normalization occurred
    if not error_raised:
        assert normalized, (
            "Should either raise ValueError OR normalize longitudes to [-180, 180]"
        )
