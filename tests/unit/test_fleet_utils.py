"""Unit tests for Fleet conversion utilities."""

from typing import List

import numpy as np
import pandas as pd
import pytest
from pycontrails import Flight

from pyneats.core.fleet_utils import fleet_to_flights, flights_to_fleet
from pyneats.core.views import FlightView
from pyneats.steps.parsing.neats_parser import NEATSFuel


class TestFlightsToFleet:
    """Test flights_to_fleet function."""

    def test_single_flight_conversion(self) -> None:
        """Test converting single flight to Fleet."""
        df = pd.DataFrame({"latitude": [51.0, 52.0], "longitude": [0.0, 1.0], "altitude": [10000, 11000]})
        fuel = NEATSFuel(q_fuel=43.0, ei_h2o=1.24)
        flight = Flight(df, fuel=fuel)
        flight.attrs["flight_id"] = "TEST123"

        fleet = flights_to_fleet([flight])

        assert "q_fuel" in fleet.data
        assert "ei_h2o" in fleet.data
        assert "columns" in fleet.attrs
        assert len(fleet) == 2  # 2 waypoints

    def test_multiple_flights_conversion(self) -> None:
        """Test converting multiple flights to Fleet."""
        df1 = pd.DataFrame({"latitude": [51.0, 52.0], "longitude": [0.0, 1.0], "altitude": [10000, 11000]})
        df2 = pd.DataFrame({"latitude": [53.0], "longitude": [2.0], "altitude": [12000]})

        fuel1 = NEATSFuel(q_fuel=43.0, ei_h2o=1.24)
        fuel2 = NEATSFuel(q_fuel=43.0, ei_h2o=1.24)

        flight1 = Flight(df1, fuel=fuel1)
        flight2 = Flight(df2, fuel=fuel2)

        fleet = flights_to_fleet([flight1, flight2])

        assert len(fleet) == 3  # 2 + 1 waypoints
        assert "q_fuel" in fleet.data
        assert "ei_h2o" in fleet.data

    def test_fuel_object_converted_to_columns(self) -> None:
        """Test that fuel objects are converted to q_fuel and ei_h2o columns."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "altitude": [10000]})
        fuel = NEATSFuel(q_fuel=43.5, ei_h2o=1.25)
        flight = Flight(df, fuel=fuel)

        fleet = flights_to_fleet([flight])

        assert fleet["q_fuel"][0] == 43.5
        assert fleet["ei_h2o"][0] == 1.25

    def test_columns_tracked_in_attrs(self) -> None:
        """Test that original column sets are tracked in attrs."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "altitude": [10000]})
        fuel = NEATSFuel(q_fuel=43.0, ei_h2o=1.24)
        flight = Flight(df, fuel=fuel)

        fleet = flights_to_fleet([flight])

        assert "columns" in fleet.attrs
        assert isinstance(fleet.attrs["columns"], set)
        assert "q_fuel" in fleet.attrs["columns"]
        assert "ei_h2o" in fleet.attrs["columns"]


class TestFleetToFlights:
    """Test fleet_to_flights function."""

    def test_single_flight_restoration(self) -> None:
        """Test restoring single flight from Fleet."""
        df = pd.DataFrame(
            {
                "latitude": [51.0, 52.0],
                "longitude": [0.0, 1.0],
                "altitude": [10000, 11000],
                "q_fuel": [43.0, 43.0],
                "ei_h2o": [1.24, 1.24],
                "flight_id": [0, 0],
            }
        )
        from pycontrails import Fleet

        fleet = Fleet(df)
        fleet.attrs["columns"] = set(df.columns)
        fleet.fl_attrs = {0: {"flight_id": "TEST123", "q_fuel": 43.0, "ei_h2o": 1.24}}

        flights = fleet_to_flights(fleet)

        assert len(flights) == 1
        assert flights[0].fuel is not None
        assert flights[0].fuel.q_fuel == 43.0
        assert flights[0].fuel.ei_h2o == 1.24

    def test_columns_removed_from_attrs(self) -> None:
        """Test that 'columns' key is removed from attrs after conversion."""
        df = pd.DataFrame(
            {
                "latitude": [51.0],
                "longitude": [0.0],
                "altitude": [10000],
                "q_fuel": [43.0],
                "ei_h2o": [1.24],
                "flight_id": [0],
            }
        )
        from pycontrails import Fleet

        fleet = Fleet(df)
        fleet.attrs["columns"] = set(df.columns)
        fleet.fl_attrs = {0: {"flight_id": "TEST123", "q_fuel": 43.0, "ei_h2o": 1.24}}

        flights = fleet_to_flights(fleet)

        # 'columns' should be removed from flight attrs
        assert "columns" not in flights[0].attrs


class TestRoundtripConversion:
    """Test roundtrip conversion: flights → fleet → flights."""

    def test_roundtrip_preserves_data(self) -> None:
        """Test that roundtrip conversion preserves flight data."""
        df = pd.DataFrame(
            {
                "latitude": [51.0, 52.0, 53.0],
                "longitude": [0.0, 1.0, 2.0],
                "altitude": [10000, 11000, 12000],
            }
        )
        fuel = NEATSFuel(q_fuel=43.0, ei_h2o=1.24)
        original_flight = Flight(df, fuel=fuel)
        original_flight.attrs["flight_id"] = "TEST123"

        # Roundtrip
        fleet = flights_to_fleet([original_flight])
        restored_flights = fleet_to_flights(fleet)

        assert len(restored_flights) == 1
        restored_flight = restored_flights[0]

        # Check data preservation
        pd.testing.assert_frame_equal(
            original_flight.dataframe.reset_index(drop=True),
            restored_flight.dataframe.reset_index(drop=True),
        )

    def test_roundtrip_preserves_fuel_object(self) -> None:
        """Test that roundtrip conversion preserves fuel object."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "altitude": [10000]})
        fuel = NEATSFuel(q_fuel=43.5, ei_h2o=1.25)
        original_flight = Flight(df, fuel=fuel)

        # Roundtrip
        fleet = flights_to_fleet([original_flight])
        restored_flights = fleet_to_flights(fleet)

        restored_fuel = restored_flights[0].fuel
        assert restored_fuel is not None
        assert restored_fuel.q_fuel == 43.5
        assert restored_fuel.ei_h2o == 1.25

    def test_roundtrip_preserves_attrs(self) -> None:
        """Test that roundtrip conversion preserves flight attributes."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "altitude": [10000]})
        fuel = NEATSFuel(q_fuel=43.0, ei_h2o=1.24)
        original_flight = Flight(df, fuel=fuel)
        original_flight.attrs["flight_id"] = "ABC123"
        original_flight.attrs["aircraft_type"] = "A320"

        # Roundtrip
        fleet = flights_to_fleet([original_flight])
        restored_flights = fleet_to_flights(fleet)

        assert restored_flights[0].attrs["flight_id"] == "ABC123"
        assert restored_flights[0].attrs["aircraft_type"] == "A320"

    def test_roundtrip_with_multiple_flights(self) -> None:
        """Test roundtrip with multiple flights."""
        df1 = pd.DataFrame({"latitude": [51.0, 52.0], "longitude": [0.0, 1.0], "altitude": [10000, 11000]})
        df2 = pd.DataFrame({"latitude": [53.0], "longitude": [2.0], "altitude": [12000]})
        df3 = pd.DataFrame(
            {"latitude": [54.0, 55.0, 56.0], "longitude": [3.0, 4.0, 5.0], "altitude": [13000, 14000, 15000]}
        )

        fuel = NEATSFuel(q_fuel=43.0, ei_h2o=1.24)

        flight1 = Flight(df1, fuel=fuel)
        flight2 = Flight(df2, fuel=fuel)
        flight3 = Flight(df3, fuel=fuel)

        flight1.attrs["flight_id"] = "FLIGHT1"
        flight2.attrs["flight_id"] = "FLIGHT2"
        flight3.attrs["flight_id"] = "FLIGHT3"

        original_flights = [flight1, flight2, flight3]

        # Roundtrip
        fleet = flights_to_fleet(original_flights)
        restored_flights = fleet_to_flights(fleet)

        assert len(restored_flights) == 3
        assert restored_flights[0].attrs["flight_id"] == "FLIGHT1"
        assert restored_flights[1].attrs["flight_id"] == "FLIGHT2"
        assert restored_flights[2].attrs["flight_id"] == "FLIGHT3"

        # Check waypoint counts
        assert len(restored_flights[0]) == 2
        assert len(restored_flights[1]) == 1
        assert len(restored_flights[2]) == 3


class TestGoldenFlightsRoundtrip:
    """Test roundtrip conversion with realistic golden flight data."""

    def test_roundtrip_with_golden_flights(self, golden_flights: List[FlightView]) -> None:
        """Test roundtrip conversion preserves golden flight data."""
        if not golden_flights:
            pytest.skip("No golden flights available")

        # Convert FlightView to Flight (FlightView is a subclass)
        original_flights = [FlightView.to_flight(fv) for fv in golden_flights]

        # Roundtrip
        fleet = flights_to_fleet(original_flights)
        restored_flights = fleet_to_flights(fleet)

        assert len(restored_flights) == len(original_flights)

        # Check that fuel objects are restored
        for restored in restored_flights:
            assert restored.fuel is not None
            assert hasattr(restored.fuel, "q_fuel")
            assert hasattr(restored.fuel, "ei_h2o")

    def test_golden_flights_columns_preserved(self, golden_flights: List[FlightView]) -> None:
        """Test that column names are preserved through roundtrip."""
        if not golden_flights:
            pytest.skip("No golden flights available")

        original_flights = [FlightView.to_flight(fv) for fv in golden_flights]

        # Get original column sets (excluding fuel columns which will be added)
        original_columns = [set(f.data.keys()) for f in original_flights]

        # Roundtrip
        fleet = flights_to_fleet(original_flights)
        restored_flights = fleet_to_flights(fleet)

        # Check column sets match (excluding q_fuel and ei_h2o which are synthetic)
        for orig_cols, restored in zip(original_columns, restored_flights):
            restored_cols = set(restored.data.keys())
            # Remove fuel columns for comparison
            restored_cols_no_fuel = {c for c in restored_cols if c not in ("q_fuel", "ei_h2o")}
            orig_cols_no_fuel = {c for c in orig_cols if c not in ("q_fuel", "ei_h2o")}
            assert restored_cols_no_fuel == orig_cols_no_fuel

    def test_golden_flights_fuel_values_preserved(self, golden_flights: List[FlightView]) -> None:
        """Test that fuel values are preserved through roundtrip."""
        if not golden_flights:
            pytest.skip("No golden flights available")

        original_flights = [FlightView.to_flight(fv) for fv in golden_flights]

        # Store original fuel values
        original_fuel_values = [(f.fuel.q_fuel, f.fuel.ei_h2o) for f in original_flights]

        # Roundtrip
        fleet = flights_to_fleet(original_flights)
        restored_flights = fleet_to_flights(fleet)

        # Check fuel values match
        for (orig_q_fuel, orig_ei_h2o), restored in zip(original_fuel_values, restored_flights):
            assert restored.fuel is not None
            np.testing.assert_allclose(restored.fuel.q_fuel, orig_q_fuel, rtol=1e-9)
            np.testing.assert_allclose(restored.fuel.ei_h2o, orig_ei_h2o, rtol=1e-9)
