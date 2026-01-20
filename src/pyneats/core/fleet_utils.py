"""Utilities for Fleet ↔ List[Flight] conversions."""

from __future__ import annotations

import numpy as np
from pycontrails import Fleet, Flight

from pyneats.steps.parsing.neats_parser import NEATSFuel  # type: ignore[attr-defined]

__all__ = [
    "flights_to_fleet",
    "fleet_to_flights",
]


def flights_to_fleet(flights: list[Flight]) -> Fleet:
    """
    Convert List[Flight] to Fleet, preserving fuel information.

    Fuel properties (q_fuel, ei_h2o) are extracted from flight.fuel and stored
    as columns in the Fleet dataframe. The original fuel object is set to None.

    Flights with different columns are harmonized by padding missing columns
    with NaN values. Original column sets are stored in attrs to enable
    restoration during fleet_to_flights().

    Args:
        flights: List of Flight objects with fuel information

    Returns:
        Fleet object with fuel information stored as columns
    """
    # 1. Store original columns and add fuel columns
    for flight in flights:
        flight.attrs["_original_columns"] = set(flight.data.keys())
        flight["q_fuel"] = np.full(len(flight), flight.fuel.q_fuel)
        flight["ei_h2o"] = np.full(len(flight), flight.fuel.ei_h2o)
        flight.fuel = None  # type: ignore[assignment]

    # 2. Harmonize: compute union of all columns and pad missing with NaN
    all_columns: set[str] = set()
    for flight in flights:
        all_columns.update(flight.data.keys())

    for flight in flights:
        for col in all_columns - set(flight.data.keys()):
            flight[col] = np.full(len(flight), np.nan)

    # 3. Now safe to create Fleet (all flights have same columns)
    fleet = Fleet.from_seq(flights)
    fleet.attrs["_fleet_columns"] = all_columns
    return fleet


def fleet_to_flights(fleet: Fleet) -> list[Flight]:
    """
    Convert Fleet back to List[Flight], restoring fuel information.

    Fuel properties (q_fuel, ei_h2o) are extracted from Fleet columns and used
    to reconstruct flight.fuel objects. Columns that were added during Fleet
    conversion (NaN padding) are removed to restore original column sets.

    Args:
        fleet: Fleet object with fuel information as columns

    Returns:
        List of Flight objects with restored fuel information
    """
    fleet_columns = fleet.attrs.pop("_fleet_columns", set())
    flights = fleet.to_flight_list()

    for flight in flights:
        # Restore original columns by removing padded ones
        original_columns = flight.attrs.pop("_original_columns", set())
        for col in fleet_columns - original_columns:
            flight.data.pop(col, None)

        # Restore fuel object
        flight.fuel = NEATSFuel.from_attrs(flight.attrs)

    return flights
