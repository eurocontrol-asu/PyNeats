"""Shared fixtures and utilities for geometry failure mode tests.

This module provides test fixtures and helper functions for testing pycontrails
geometry edge cases that affect PyNEATS trajectory processing:
- Antimeridian crossing (±180° longitude)
- Polar regions (>80° latitude)
- Coordinate wrapping and validation

All fixtures use synthetic data with no external dependencies (no ERA5, no BADA).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pycontrails import Flight
from pycontrails.core.met import MetDataset


# ============================================================================
# Trajectory Fixtures
# ============================================================================


@pytest.fixture
def tokyo_la_flight() -> Flight:
    """Tokyo→LA trajectory crossing antimeridian.

    Waypoints span from 139.77°E (Tokyo NRT) to 118.41°W (Los Angeles LAX),
    crossing the antimeridian at ~175°E → ~175°W.

    Expected true longitude span: ~108° (not 342°)

    Returns:
        Flight object with 5 waypoints crossing the antimeridian
    """
    waypoints = [
        {"lon": 139.77, "lat": 35.68, "alt": 35000},  # Tokyo (NRT)
        {"lon": 165.0, "lat": 40.0, "alt": 37000},  # Western Pacific
        {"lon": -175.0, "lat": 42.0, "alt": 38000},  # Crosses antimeridian
        {"lon": -155.0, "lat": 38.0, "alt": 36000},  # Hawaii region
        {"lon": -118.41, "lat": 33.94, "alt": 35000},  # Los Angeles (LAX)
    ]
    return make_test_flight(waypoints, flight_id="TOKYO_LA")


@pytest.fixture
def polar_flight() -> Flight:
    """High-latitude polar route reaching 85°N.

    Tests polar geometry handling and meridian convergence near North Pole.

    Returns:
        Flight object with 5 waypoints reaching 85°N latitude
    """
    waypoints = [
        {"lon": 10.0, "lat": 60.0, "alt": 35000},  # Oslo region
        {"lon": 0.0, "lat": 75.0, "alt": 37000},  # Svalbard region
        {"lon": -30.0, "lat": 85.0, "alt": 38000},  # Near North Pole
        {"lon": -90.0, "lat": 82.0, "alt": 37000},  # Canadian Arctic
        {"lon": -120.0, "lat": 70.0, "alt": 35000},  # Alaska region
    ]
    return make_test_flight(waypoints, flight_id="POLAR")


@pytest.fixture
def edge_case_flight() -> Flight:
    """Edge case coordinates (antimeridian boundary, near poles).

    Returns:
        Flight object with 4 edge case waypoints
    """
    waypoints = [
        {"lon": 179.9, "lat": 0.0, "alt": 35000},  # Just west of antimeridian
        {"lon": -179.9, "lat": 0.0, "alt": 35000},  # Just east of antimeridian
        {"lon": 0.0, "lat": 89.5, "alt": 35000},  # Near North Pole
        {"lon": 0.0, "lat": -89.5, "alt": 35000},  # Near South Pole
    ]
    return make_test_flight(waypoints, flight_id="EDGE_CASE")


@pytest.fixture
def minimal_met() -> MetDataset:
    """Minimal global MetDataset for downselect testing.

    Grid: 10° resolution, global coverage
    Variables: air_temperature, eastward_wind, northward_wind
    No external dependencies (no ERA5 credentials needed)

    Returns:
        MetDataset with synthetic global grid
    """
    return make_minimal_metdataset()


# ============================================================================
# Helper Functions
# ============================================================================


def make_test_flight(waypoints: list[dict], flight_id: str = "TEST") -> Flight:
    """Create minimal Flight from waypoint list.

    Follows pattern from test_fleet_utils.py::_make_flight().

    Args:
        waypoints: List of dicts with keys 'lon', 'lat', 'alt'
        flight_id: Flight identifier

    Returns:
        Flight object with required 4D columns and minimal attrs
    """
    n_points = len(waypoints)

    # Build data dict with required 4D coordinates
    data = {
        "longitude": np.array([w["lon"] for w in waypoints]),
        "latitude": np.array([w["lat"] for w in waypoints]),
        "altitude": np.array([w["alt"] for w in waypoints]) * 0.3048,  # ft → m
        "time": pd.date_range(
            "2023-06-15 10:00:00", periods=n_points, freq="5min"
        ).values,  # Convert to numpy datetime64 array
    }

    # Minimal attrs (including model_type required by Flight4D validation)
    attrs = {
        "flight_id": flight_id,
        "aircraft_type": "A320",
        "departure_airport": "TEST",
        "arrival_airport": "TEST",
        "aobt": "2023-06-15 10:00:00",
        "model_type": "BADA4",  # Required by Flight4D validation
    }

    return Flight(data=data, attrs=attrs)


def make_minimal_metdataset(time_slice: str = "2023-06-15T09:00:00") -> MetDataset:
    """Create minimal MetDataset using xarray.

    Mimics ECMWF ERA5 structure without requiring credentials.

    Args:
        time_slice: ISO timestamp for met data

    Returns:
        MetDataset with 10° global grid and basic met variables
    """
    # Global grid with 10° resolution
    lons = np.arange(-180, 181, 10)  # 37 points
    lats = np.arange(-90, 91, 10)  # 19 points
    levels = [300, 250, 200]  # 3 pressure levels (hPa)
    times = pd.date_range(
        time_slice, periods=3, freq="1h"
    ).values  # Convert to numpy datetime64

    coords = {
        "longitude": lons,
        "latitude": lats,
        "level": levels,
        "time": times,
    }

    # Minimal required variables for downselect/intersect
    data_vars = {
        "air_temperature": (
            ["time", "level", "latitude", "longitude"],
            np.full((3, 3, 19, 37), 250.0),  # 250 K
        ),
        "eastward_wind": (
            ["time", "level", "latitude", "longitude"],
            np.full((3, 3, 19, 37), 10.0),  # 10 m/s
        ),
        "northward_wind": (
            ["time", "level", "latitude", "longitude"],
            np.full((3, 3, 19, 37), 5.0),  # 5 m/s
        ),
        "specific_humidity": (
            ["time", "level", "latitude", "longitude"],
            np.full((3, 3, 19, 37), 0.001),  # 0.001 kg/kg
        ),
    }

    ds = xr.Dataset(data_vars, coords=coords)
    return MetDataset(ds)


def compute_antimeridian_span(longitudes: np.ndarray) -> float:
    """Compute true longitude span accounting for antimeridian crossing.

    Uses gap detection algorithm: if the largest gap between sorted consecutive
    longitudes is > 180°, then the trajectory crosses the antimeridian.

    Args:
        longitudes: Array of longitude values in [-180, 180]

    Returns:
        Longitude span in degrees (always ≤ 360°)

    Examples:
        >>> compute_antimeridian_span(np.array([165, 175, -175, -165]))
        70.0  # Not 340.0

        >>> compute_antimeridian_span(np.array([10, 20, 30, 40]))
        30.0
    """
    if len(longitudes) == 0:
        return 0.0

    lons_sorted = np.sort(longitudes)

    if len(lons_sorted) == 1:
        return 0.0

    # Compute gaps between consecutive sorted points
    gaps = np.diff(lons_sorted)
    max_gap = gaps.max()

    # If max gap > 180°, the trajectory crosses the antimeridian
    # The true span is the complement of the max gap
    if max_gap > 180:
        return 360.0 - max_gap
    else:
        # Normal case: span is max - min
        return lons_sorted[-1] - lons_sorted[0]


def create_polar_met_data() -> xr.DataArray:
    """Create synthetic met DataArray at polar latitudes.

    Useful for testing polar region interpolation.

    Returns:
        xr.DataArray with air_temperature at high latitudes
    """
    lons = np.arange(-180, 180, 10)  # 36 points
    lats = np.array([75.0, 80.0, 85.0, 89.0])  # 4 polar latitudes
    levels = [250]  # Single pressure level
    times = pd.date_range("2023-06-15T10:00:00", periods=1)

    coords = {
        "longitude": lons,
        "latitude": lats,
        "level": levels,
        "time": times,
    }

    # Cold polar temperatures
    data = np.full((1, 1, 4, 36), 220.0)  # 220 K

    return xr.DataArray(
        data,
        coords=coords,
        dims=["time", "level", "latitude", "longitude"],
        name="air_temperature",
    )
