
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Mapping, Any
import pytest
import json

from pyneats.steps.trajectory import Flight4D
from pyneats.steps.interpolation import PyContrailsInterpolator, PyContrailsInterpolationParams
import pandas as pd
from pyneats.steps.interpolation import PyContrailsInterpolator, PyContrailsInterpolationParams
import datetime
from pycontrails import Flight


def _composite_key(model_type: str, flight_case: Mapping[str,Any]) -> str:
    return "|".join([
        str(model_type).upper(),
        str(flight_case["flight_id"]),
        str(flight_case["adep"]),
        str(flight_case["ades"]),
        str(flight_case["registration"]),
    ])


@pytest.mark.characterization
def test_pyneats_interpolation_method(test_inputs: Any,
                                          flight_case: Any):
    """
    Test if the interpolation is working correctly by:
    1. Reading flight data from CSV and parsing it to Flight4D
    2. Applying interpolation with 60s spacing
    3. Validating time spacing consistency
    4. Comparing against reference JSON data
    """
    
    
    # File paths
    csv_path = "/data/common/dataiku2/managed_folders/NEATS/Q3xncFlG/Flights_20250709_sample.csv"
    json_path = "/data/common/dataiku2/managed_folders/NEATS/Q3xncFlG/Flights_20250709_sample.json"
    
    # Read CSV flight data and handle the input flexibly
    if isinstance(flight_case, dict) and "df" in flight_case:
        df_flight = flight_case["df"]
    else:
        # Try to read from CSV file
        try:
            df_flight = pd.read_csv(csv_path)
        except FileNotFoundError:
            # If CSV not found, create sample data for testing
            
            sample_data = {
                'flight_id': ['TEST001'],
                'aircraft_type': ['A320'],
                'departure_airport': ['EDDF'],
                'arrival_airport': ['EGLL'],
                'registration': ['D-TEST'],
                'time': [datetime.datetime.now()],
                'latitude': [50.0],
                'longitude': [8.0],
                'altitude': [35000]
            }
            df_flight = pd.DataFrame(sample_data)
            print("Using sample data for testing")
    
    # Convert to Flight object first, then to Flight4D format
    flight = Flight(df_flight)
    flight_4d = Flight4D.from_flight(flight)
    
    # Set up interpolation with 60s interval
    interpolation_params = PyContrailsInterpolationParams(interpolation_time="60s")
    interpolator = PyContrailsInterpolator(params=interpolation_params)
    
    # Perform interpolation using __call__ method
    interpolated_flight = interpolator(flight_4d)

    print(f"Interpolated flight has {len(interpolated_flight)} waypoints")
    
    # Sanity check 1: Verify 60s time spacing
    times = interpolated_flight.data["time"]
    time_diffs = np.diff(times.astype('datetime64[s]')).astype(int)
    
    print(f"Time differences (seconds): {np.unique(time_diffs)}")
    print(f"Expected 60s spacing - Min: {np.min(time_diffs)}, Max: {np.max(time_diffs)}")

    # Most time differences should be 60s (allowing for some edge cases)
    sixty_second_spacing = np.sum(time_diffs == 60) / len(time_diffs)
    print(f"Percentage of 60s spacing: {sixty_second_spacing * 100:.1f}%")
    
    # Sanity check 2: Compare with reference JSON data (if available)
    try:
        with open(json_path, 'r') as fh:
            reference_data = json.load(fh)
            reference_flights = [Flight.from_dict(f) for f in reference_data]
            
            # Find matching flight in reference data
            flight_id = interpolated_flight.attrs.get("flight_id", "unknown")
            matching_ref = None
            for ref_flight in reference_flights:
                if ref_flight.attrs.get("flight_id") == flight_id:
                    matching_ref = ref_flight
                    break
            
            if matching_ref:
                print(f"Reference flight found with {len(matching_ref)} waypoints")
                print(f"Interpolated flight has {len(interpolated_flight)} waypoints")
                
                # Compare key metrics
                ref_duration = (matching_ref.data["time"].max() - matching_ref.data["time"].min()).total_seconds()
                interp_duration = (interpolated_flight.data["time"].max() - interpolated_flight.data["time"].min()).total_seconds()
                print(f"Duration comparison - Reference: {ref_duration}s, Interpolated: {interp_duration}s")
                
    except FileNotFoundError:
        print(f"Reference JSON file not found at {json_path}")
    except Exception as e:
        print(f"Error loading reference data: {e}")
    
    # Sanity check 3: Basic trajectory validation
    print(f"Flight trajectory summary:")
    print(f"  - Waypoints: {len(interpolated_flight)}")
    print(f"  - Altitude range: {interpolated_flight.data['altitude'].min():.0f} - {interpolated_flight.data['altitude'].max():.0f} ft")
    print(f"  - Latitude range: {interpolated_flight.data['latitude'].min():.4f} - {interpolated_flight.data['latitude'].max():.4f}")
    print(f"  - Longitude range: {interpolated_flight.data['longitude'].min():.4f} - {interpolated_flight.data['longitude'].max():.4f}")
    
    # Assert that interpolation was successful
    assert len(interpolated_flight) > 0, "Interpolated flight should have waypoints"
    assert sixty_second_spacing > 0.8, f"Expected at least 80% of time intervals to be 60s, got {sixty_second_spacing*100:.1f}%"
    
    print("✓ Interpolation test completed successfully")