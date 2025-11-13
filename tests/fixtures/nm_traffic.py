import json
from pathlib import Path
from typing import List
import pandas as pd
import pytest

from pyneats.core.views import FlightView


@pytest.fixture
def nm_input() -> List[pd.DataFrame]:
    traffic_path = Path(__file__).parent.parent / "data"

    if not traffic_path.is_dir():
        raise RuntimeError(f"Test traffic path directory does not exist: {traffic_path}")

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
    traffic_path = Path(__file__).parent.parent / "data"

    if not traffic_path.is_dir():
        raise RuntimeError(f"Test traffic path directory does not exist: {traffic_path}")

    filepath = traffic_path / "nm_output.json"

    if not filepath.exists():
        raise FileNotFoundError(filepath)

    with open(filepath, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    flights = []

    for d in data:
        f = FlightView.from_dict(d)
        flights.append(f)

    # Sort flights by flight_id
    flights_sorted = sorted(flights, key=lambda f: f.attrs["flight_id"])

    return flights_sorted
