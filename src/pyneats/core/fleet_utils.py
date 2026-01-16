"""Utilities for Fleet ↔ List[Flight] conversions."""

from __future__ import annotations


import numpy as np
from pycontrails import Flight, Fleet

from pyneats.steps.parsing.neats_parser import NEATSFuel

__all__ = [
    "flights_to_fleet",
    "fleet_to_flights",
]


def flights_to_fleet(flights: list[Flight]) -> Fleet:
    """
    Convert List[Flight] to Fleet, preserving fuel information.

    Fuel properties (q_fuel, ei_h2o) are extracted from flight.fuel and stored
    as columns in the Fleet dataframe. The original fuel object is set to None.

    Args:
        flights: List of Flight objects with fuel information

    Returns:
        Fleet object with fuel information stored as columns
    """
    for flight in flights:
        flight.attrs["columns"] = set(flight.data.keys())
        flight["q_fuel"] = np.full(len(flight), flight.fuel.q_fuel)
        flight["ei_h2o"] = np.full(len(flight), flight.fuel.ei_h2o)
        flight.fuel = None

    fleet = Fleet.from_seq(flights)
    fleet.attrs["columns"] = set(fleet.data.keys())
    return fleet


def fleet_to_flights(fleet: Fleet) -> list[Flight]:
    """
    Convert Fleet back to List[Flight], restoring fuel information.

    Fuel properties (q_fuel, ei_h2o) are extracted from Fleet columns and used
    to reconstruct flight.fuel objects. Columns that were added during Fleet
    conversion are removed.

    Args:
        fleet: Fleet object with fuel information as columns

    Returns:
        List of Flight objects with restored fuel information
    """
    fleet_columns = fleet.attrs.pop("columns")
    flights = fleet.to_flight_list()

    for flight in flights:
        flight_columns = flight.attrs.pop("columns")
        columns_to_delete = fleet_columns.difference(flight_columns)

        for col in columns_to_delete:
            flight.data.pop(col)
        flight.fuel = NEATSFuel.from_attrs(flight.attrs)

    return flights
