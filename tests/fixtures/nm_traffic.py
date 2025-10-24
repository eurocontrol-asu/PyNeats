import os
import pandas as pd
import pytest
import json
from pathlib import Path
from typing import List
from pyneats.core.views import FlightView


@pytest.fixture
def nm_input() -> List[pd.DataFrame]:
    traffic_path = os.environ.get("TEST_TRAFFIC_DIR", "./tests/data")
    print(traffic_path)
    traffic_path = Path(traffic_path)

    if not traffic_path.is_dir():
        raise RuntimeError(
            f"Test traffic path directory does not exist: {traffic_path}"
        )

    filepath = traffic_path / "nm_input.csv"

    if not filepath.exists():
        raise FileNotFoundError(filepath)

    # Read CSV
    df = pd.read_csv(
        filepath,
        sep=";",
        decimal=",",
        dayfirst=True,
        dtype={
            "AIRCRAFT_ID": "string",
            "ADEP": "string",
            "ADES": "string",
            "REGISTRATION": "string",
            "MODEL_TYPE": "string",
        },
    )

    # Clean string columns
    for col in ["AIRCRAFT_ID", "ADEP", "ADES", "REGISTRATION"]:
        df[col] = df[col].astype("string").str.strip()

    # Sort by AIRCRAFT_ID
    df = df.sort_values("AIRCRAFT_ID")

    # Group by AIRCRAFT_ID and return as list of DataFrames
    grouped_dfs = [group.copy() for _, group in df.groupby("AIRCRAFT_ID")]

    return grouped_dfs


@pytest.fixture
def nm_output() -> List[FlightView]:
    traffic_path = os.environ.get("TEST_TRAFFIC_DIR", "./tests/data")
    print(traffic_path)
    traffic_path = Path(traffic_path)

    if not traffic_path.is_dir():
        raise RuntimeError(
            f"Test traffic path directory does not exist: {traffic_path}"
        )

    filepath = traffic_path / "nm_output.json"

    if not filepath.exists():
        raise FileNotFoundError(filepath)

    with open(filepath, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    flights = []

    for d in data:
        f = FlightView.from_dict(d)

        # This is needed because it forces it as column instead of attribute when reading from dict
        # We should force overloaded to_dict to save flight_id as single value (so that is parsed as an attribute) or
        # also overload the from_dict
        f["altitude"] = f.altitude
        f.attrs["flight_id"] = f["flight_id"][0]
        flights.append(f)

    # Sort flights by flight_id
    flights_sorted = sorted(flights, key=lambda f: f.attrs["flight_id"])

    return flights_sorted
