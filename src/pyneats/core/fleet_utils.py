"""
Utilities for Fleet ↔ List[Flight] conversions.

This module provides utility functions to convert between lists of Flight objects and Fleet objects,
preserving and restoring fuel information and original columns.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pycontrails import Fleet
from pycontrails import Flight

from pyneats.steps.parsing.neats_parser import NEATSFuel  # type: ignore[attr-defined]


__all__ = [
    "flights_to_fleet",
    "fleet_to_flights",
]

_ERROR_RECORD_ATTRS = (
    "departure_airport",
    "arrival_airport",
    "aobt",
    "aircraft_type",
    "engine_uid",
)


def flights_to_fleet(flights: list[Flight]) -> Fleet:
    """
    Convert a list of Flight objects to a Fleet, preserving fuel information.

    Fuel properties (q_fuel, ei_h2o) are extracted from flight.fuel and stored
    as columns in the Fleet dataframe. The original fuel object is set to None.
    Flights with different columns are harmonized by padding missing columns
    with NaN values. Original column sets are stored in attrs to enable
    restoration during fleet_to_flights().

    A flight manifest is stored in Fleet attrs so that dropped flights can be
    detected during fleet_to_flights().

    Parameters
    ----------
    flights : list of Flight
        List of Flight objects with fuel information.

    Returns
    -------
    Fleet
        Fleet object with fuel information stored as columns.
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

    # 3. Create unique flight_id from key columns to avoid pycontrails duplicate issues
    flight_key_attrs = ["flight_id", "arrival_airport", "departure_airport", "aobt"]
    for flight in flights:
        flight.attrs["_original_flight_id"] = flight.attrs["flight_id"]
        flight.attrs["flight_id"] = "_".join(
            str(flight.attrs[k]) for k in flight_key_attrs
        )

    # 3b. Build manifest keyed by composite flight_id for dropped-flight detection
    manifest: dict[str, dict[str, Any]] = {}
    for flight in flights:
        composite_id = flight.attrs["flight_id"]
        info = {k: flight.attrs.get(k, "UNKNOWN") for k in _ERROR_RECORD_ATTRS}
        info["flight_id"] = flight.attrs["_original_flight_id"]
        manifest[composite_id] = info

    # 4. Now safe to create Fleet (all flights have same columns)
    fleet = Fleet.from_seq(flights, broadcast_numeric=False)
    fleet.attrs["_fleet_columns"] = all_columns
    fleet.attrs["_flight_manifest"] = manifest
    return fleet


def fleet_to_flights(
    fleet: Fleet, step_name: str = "fleet_processing"
) -> tuple[list[Flight], list[dict[str, Any]]]:
    """
    Convert a Fleet object back to a list of Flight objects, restoring fuel information.

    Fuel properties (q_fuel, ei_h2o) are extracted from Fleet columns and used
    to reconstruct flight.fuel objects. Columns that were added during Fleet
    conversion (NaN padding) are removed to restore original column sets.

    Any flights present in the original manifest but missing from the Fleet
    are returned as error records.

    Parameters
    ----------
    fleet : Fleet
        Fleet object with fuel information as columns.
    step_name : str
        Name of the processing step, used in error messages for dropped flights.

    Returns
    -------
    tuple of (list of Flight, list of dict)
        Tuple of (restored flights, error records for dropped flights).
    """
    manifest = fleet.attrs.pop("_flight_manifest", {})
    fleet_columns = fleet.attrs.pop("_fleet_columns", set())
    flights = fleet.to_flight_list()

    surviving_ids: set[str] = set()
    for flight in flights:
        surviving_ids.add(flight.attrs["flight_id"])

        # Restore original flight_id
        flight.attrs["flight_id"] = flight.attrs.pop("_original_flight_id")

        # Restore original columns by removing padded ones
        original_columns = flight.attrs.pop("_original_columns", set())
        for col in fleet_columns - original_columns:
            flight.data.pop(col, None)

        # Restore fuel object
        flight.fuel = NEATSFuel.from_attrs(flight.attrs)

    # Create error records for dropped flights
    errors: list[dict[str, Any]] = []
    for composite_id, attrs in manifest.items():
        if composite_id not in surviving_ids:
            errors.append(
                {
                    "flight_information": attrs,
                    "error": f"Failed at {step_name}: flight dropped during fleet processing",
                }
            )

    return flights, errors
