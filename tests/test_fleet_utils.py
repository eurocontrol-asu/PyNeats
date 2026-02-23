"""Unit tests for fleet_utils: flights_to_fleet / fleet_to_flights roundtrip."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pycontrails import Fleet
from pycontrails import Flight

from pyneats.core.fleet_utils import fleet_to_flights
from pyneats.core.fleet_utils import flights_to_fleet
from pyneats.core.neats_fuel import NEATSFuel


def _make_flight(
    flight_id: str,
    departure: str,
    arrival: str,
    aobt: str,
    n_points: int = 5,
    extra_columns: dict | None = None,
) -> Flight:
    """Create a minimal Flight with required 4D columns and fuel attrs."""
    t0 = pd.Timestamp(aobt, tz="UTC")
    data = {
        "longitude": np.linspace(0, 10, n_points),
        "latitude": np.linspace(40, 50, n_points),
        "altitude": np.linspace(10000, 11000, n_points),
        "time": pd.date_range(t0, periods=n_points, freq="60s"),
    }
    if extra_columns:
        for col, val in extra_columns.items():
            data[col] = np.full(n_points, val)

    attrs = {
        "flight_id": flight_id,
        "departure_airport": departure,
        "arrival_airport": arrival,
        "aobt": aobt,
    }
    flight = Flight(data=data, attrs=attrs)
    flight.fuel = NEATSFuel(q_fuel=43.2e6, hydrogen_content=13.8)
    return flight


def test_roundtrip_preserves_flight_id():
    """Single flight: flight_id is restored after roundtrip."""
    flight = _make_flight("ABC123", "EGLL", "KJFK", "2024-01-01T12:00:00")
    fleet = flights_to_fleet([flight])
    result, errors = fleet_to_flights(fleet)

    assert len(result) == 1
    assert result[0].attrs["flight_id"] == "ABC123"
    assert "_original_flight_id" not in result[0].attrs
    assert errors == []


def test_duplicate_flight_id_gets_unique_composite():
    """Two flights with same flight_id but different routes don't clash."""
    f1 = _make_flight("DUP001", "EGLL", "KJFK", "2024-01-01T12:00:00")
    f2 = _make_flight("DUP001", "LFPG", "LEMD", "2024-01-01T14:00:00")

    # Should not raise — composite keys are unique
    fleet = flights_to_fleet([f1, f2])
    result, errors = fleet_to_flights(fleet)

    assert len(result) == 2
    assert all(f.attrs["flight_id"] == "DUP001" for f in result)
    assert errors == []


def test_original_columns_preserved():
    """Extra NaN-padded columns are removed after roundtrip."""
    f1 = _make_flight(
        "A1", "EGLL", "KJFK", "2024-01-01T12:00:00", extra_columns={"sac": 1.0}
    )
    f2 = _make_flight("B2", "LFPG", "LEMD", "2024-01-01T14:00:00")

    fleet = flights_to_fleet([f1, f2])
    result, errors = fleet_to_flights(fleet)

    # f1 originally had "sac", f2 did not
    r1 = next(f for f in result if f.attrs["flight_id"] == "A1")
    r2 = next(f for f in result if f.attrs["flight_id"] == "B2")

    assert "sac" in r1.data
    assert "sac" not in r2.data
    assert errors == []


def test_fuel_roundtrip():
    """Fuel object is reconstructed and ei_h2o survives via attrs."""
    flight = _make_flight("FUEL1", "EGLL", "KJFK", "2024-01-01T12:00:00")
    # Store fuel params in attrs so from_attrs can reconstruct them
    flight.attrs["q_fuel"] = flight.fuel.q_fuel
    flight.attrs["hydrogen_content"] = 13.8
    expected_q = flight.fuel.q_fuel
    expected_ei = flight.fuel.ei_h2o

    fleet = flights_to_fleet([flight])
    result, errors = fleet_to_flights(fleet)

    assert result[0].fuel is not None
    assert result[0].fuel.q_fuel == pytest.approx(expected_q, rel=1e-6)
    assert result[0].fuel.ei_h2o == pytest.approx(expected_ei, rel=1e-6)
    assert errors == []


def test_dropped_flight_creates_error_record():
    """Dropped flight is detected and returned as an error record."""
    f1 = _make_flight("KEEP", "EGLL", "KJFK", "2024-01-01T12:00:00")
    f2 = _make_flight("DROP", "LFPG", "LEMD", "2024-01-01T14:00:00")
    fleet = flights_to_fleet([f1, f2])

    # Find the composite key for f2 to drop it
    df = fleet.dataframe
    composite_ids = df["flight_id"].unique()
    composite_id_to_drop = next(cid for cid in composite_ids if "DROP" in cid)

    # Simulate a vectorized step dropping f2 by removing its rows
    mask = df["flight_id"] != composite_id_to_drop
    filtered_fleet = Fleet(
        data=df[mask].reset_index(drop=True),
        attrs=fleet.attrs,
        fl_attrs={k: v for k, v in fleet.fl_attrs.items() if k != composite_id_to_drop},
    )

    result, errors = fleet_to_flights(filtered_fleet, step_name="test_step")
    assert len(result) == 1
    assert result[0].attrs["flight_id"] == "KEEP"
    assert len(errors) == 1
    assert errors[0]["flight_information"]["flight_id"] == "DROP"
    assert errors[0]["flight_information"]["departure_airport"] == "LFPG"
    assert errors[0]["flight_information"]["arrival_airport"] == "LEMD"
    assert "test_step" in errors[0]["error"]


def test_manifest_stored_in_fleet_attrs():
    """Flight manifest is stored in Fleet attrs during flights_to_fleet."""
    f1 = _make_flight("FLT1", "EGLL", "KJFK", "2024-01-01T12:00:00")
    fleet = flights_to_fleet([f1])

    assert "_flight_manifest" in fleet.attrs
    manifest = fleet.attrs["_flight_manifest"]
    assert len(manifest) == 1
    # The manifest value should contain the original flight_id
    info = next(iter(manifest.values()))
    assert info["flight_id"] == "FLT1"
