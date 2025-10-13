import pytest
from pyneats.steps.emissions.dlr_emissions import compute_dlr_emissions
from pyneats.steps.emissions.eurocontrol_emissions import compute_eurocontrol_emissions
from pyneats.steps.emissions.pycontrails_emissions import compute_pycontrails_emissions

def test_dlr_emissions():
    """Test the DLR emissions computation."""
    input_data = {
        "fuel_flow": 1.2,
        "time": 3600,
        "emission_factor": 3.16,
    }
    expected_emissions = 1.2 * 3600 * 3.16
    result = compute_dlr_emissions(input_data)
    assert result == pytest.approx(expected_emissions), f"DLR emissions mismatch: {result} != {expected_emissions}"

def test_eurocontrol_emissions():
    """Test the Eurocontrol emissions computation."""
    input_data = {
        "distance": 500,
        "emission_rate": 0.8,
    }
    expected_emissions = 500 * 0.8
    result = compute_eurocontrol_emissions(input_data)
    assert result == pytest.approx(expected_emissions), f"Eurocontrol emissions mismatch: {result} != {expected_emissions}"

def test_pycontrails_emissions():
    """Test the PyContrails emissions computation."""
    input_data = {
        "altitude": 10000,
        "speed": 250,
        "fuel_flow": 1.5,
    }
    expected_emissions = 10000 * 250 * 1.5  # Replace with actual formula if different
    result = compute_pycontrails_emissions(input_data)
    assert result == pytest.approx(expected_emissions), f"PyContrails emissions mismatch: {result} != {expected_emissions}"