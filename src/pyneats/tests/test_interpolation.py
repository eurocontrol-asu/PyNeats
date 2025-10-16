
from __future__ import annotations
import numpy as np
from typing import Mapping, Any
import pytest

from pyneats.steps.trajectory import Flight4D


from pyneats.steps.weather.weather_store import ZarrPaths, get_weather_from_zarr
from pyneats.runners.flight import FlightRunner  # adjust import path if your project differs
from pycontrails import Flight, Fleet
import json


def _composite_key(model_type: str, flight_case: Mapping[str,Any]) -> str:
    return "|".join([
        str(model_type).upper(),
        str(flight_case["flight_id"]),
        str(flight_case["adep"]),
        str(flight_case["ades"]),
        str(flight_case["reg"]),
    ])


@pytest.mark.characterization
def test_pyneats_interpolation_method(test_inputs: Any,
                                          flight_case: Any):
    """
    - Runs pipeline for one flight to check if the interpolation is working correctly

    """

    path = "/data/common/dataiku2/managed_folders/NEATS/Q3xncFlG/Flights_20250709_sample.csv"
    test_path = "/data/common/dataiku2/managed_folders/NEATS/Q3xncFlG/Flights_20250709_sample.json"

    
    with open(path) as fh:
        data = json.load(fh)
        flights = [Flight.from_dict(f) for f in data]

        
    df_flight = flight_case["df"]
    zarr_paths = test_inputs["zarr_paths"]
    t0, t1 = test_inputs["t0"], test_inputs["t1"]
    read_chunks = test_inputs["read_chunks"]



    Flight = flight.resample_and_fill(60)  # resample to 60s intervals