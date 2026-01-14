"""Fleet conversion utilities.

This module provides conversion functions between Flight sequences and Fleet objects.
These utilities are used by the Fleet-only architecture to convert between single flights
and Fleet representations.
"""

from typing import List

import numpy as np
from pycontrails import Flight, Fleet

from pyneats.steps.parsing.neats_parser import NEATSFuel


def flights_to_fleet(flights: List[Flight]) -> Fleet:
    """Convert list of flights to single Fleet object.

    Fuel objects are converted to columns (q_fuel, ei_h2o) and stored in the Fleet.
    Original column sets are tracked in fl_attrs[flight_id]['columns'] for later restoration.

    Args:
        flights: List of Flight objects to combine

    Returns:
        Fleet object containing all flights
    """
    for i, flight in enumerate(flights):
        # Store original columns in attrs (will be propagated to fl_attrs by Fleet.from_seq)
        flight.attrs["columns"] = set(flight.data.keys())

        # Store fuel parameters in attrs for later restoration
        flight.attrs["q_fuel"] = flight.fuel.q_fuel
        flight.attrs["hydrogen_content"] = flight.fuel.hydrogen_content

        # Convert fuel object to columns
        flight["q_fuel"] = np.full(len(flight), flight.fuel.q_fuel)
        flight["ei_h2o"] = np.full(len(flight), flight.fuel.ei_h2o)
        flight.fuel = None

    fleet: Fleet = Fleet.from_seq(flights)
    fleet.attrs["columns"] = set(fleet.data.keys())
    return fleet


def fleet_to_flights(fleet: Fleet) -> List[Flight]:
    """Convert Fleet object back to list of individual flights.

    Restores original column sets and fuel objects for each flight.

    Args:
        fleet: Fleet object to split

    Returns:
        List of Flight objects
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
