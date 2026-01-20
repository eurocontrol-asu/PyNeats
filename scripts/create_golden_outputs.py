#!/usr/bin/env python3
"""Generate golden test cases for PyNeats pipeline testing.

This script creates multiple golden test cases from a single input JSON by:
1. Running the default case to get baseline values
2. Creating perturbed variations of the input
3. Running the pipeline on each variation
4. Saving input/output pairs to the golden test directory

Usage:
    python scripts/create_golden_outputs.py \
        --input tests/data/golden/fleet_5_flights_input.json \
        --weather-path /path/to/weather \
        --bada-path /path/to/bada \
        --output-dir tests/data/golden

Test cases generated:
    - {base_name}: Default (no modifications)
    - {base_name}_payload_factor: payload_factor in attrs (perturbed)
    - {base_name}_takeoff_mass: takeoff_mass in attrs (perturbed)
    - {base_name}_aircraft_mass_col: aircraft_mass column (perturbed)
    - {base_name}_fuel_flow_col: fuel_flow column (perturbed)
    - {base_name}_engine_efficiency_col: engine_efficiency column (perturbed)
    - {base_name}_hydrogen_content: hydrogen_content in fuel_properties (perturbed)
    - {base_name}_q_fuel: calorific_value (q_fuel) in fuel_properties (perturbed)
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyneats.core.neats_default_parameters import (
    DEFAULT_HYDROGEN_CONTENT,
    DEFAULT_PAYLOAD_FACTOR,
    DEFAULT_Q_FUEL,
)
from pyneats.core.views import FlightView
from pyneats.runners.fleet import FleetRunner, FleetRunnerParams
from pyneats.steps.weather.weather_store import ZarrPaths

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
_log = logging.getLogger(__name__)


# Perturbation factors for each test case
PERTURBATIONS = {
    "payload_factor": 0.85,  # 85% of default (1.0 -> 0.85)
    "takeoff_mass": 1.02,  # 102% of baseline
    "aircraft_mass_col": 0.995,  # 99.5% of baseline (small to avoid BADA failures)
    "fuel_flow_col": 1.03,  # 103% of baseline
    "engine_efficiency_col": 0.97,  # 97% of baseline
    "hydrogen_content": 1.02,  # 102% of default (13.79 -> ~14.07)
    "q_fuel": 0.98,  # 98% of default (42.8M -> ~41.9M)
}


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate golden test cases for PyNeats pipeline testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to input JSON file (NM format)",
    )
    parser.add_argument(
        "--weather-path",
        type=Path,
        required=True,
        help="Path to weather data directory (containing icon_met.zarr, icon_rad.zarr)",
    )
    parser.add_argument(
        "--bada-path",
        type=Path,
        required=True,
        help="Path to BADA data directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to save golden test cases",
    )
    parser.add_argument(
        "--skip-default",
        action="store_true",
        help="Skip generating the default case (useful if it already exists)",
    )
    return parser.parse_args()


def load_input(path: Path) -> list[dict[str, Any]]:
    """Load input JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_input(data: list[dict[str, Any]], path: Path) -> None:
    """Save input JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _log.info("Saved input: %s", path)


def save_output(flights: list[FlightView], path: Path) -> None:
    """Save output JSON file in FlightView format."""
    data = [flight.to_dict() for flight in flights]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _log.info("Saved output: %s (%d flights)", path, len(flights))


def create_zarr_paths(weather_path: Path) -> ZarrPaths:
    """Create ZarrPaths from weather directory."""
    met_store = weather_path / "icon_met.zarr"
    rad_store = weather_path / "icon_rad.zarr"
    wind_store = weather_path / "icon_wind.zarr"

    if not met_store.is_dir():
        raise FileNotFoundError(f"Met store not found: {met_store}")
    if not rad_store.is_dir():
        raise FileNotFoundError(f"Rad store not found: {rad_store}")
    if not wind_store.is_dir():
        _log.warning("Wind store not found: %s (optional)", wind_store)
        wind_store = None  # type: ignore[assignment]

    return ZarrPaths(met_store, rad_store, wind_store)


def run_pipeline(
    input_path: Path,
    zarr_paths: ZarrPaths,
    bada_path: Path,
) -> list[FlightView]:
    """Run FleetRunner pipeline and return output flights."""
    cfg = FleetRunnerParams(
        trajectory_json_filepath=str(input_path),
        zarr_paths=zarr_paths,
        bada_path=str(bada_path),
        params={},
    )

    runner = FleetRunner(cfg)
    runner.eval()

    if runner.fleet_with_climate_impact is None:
        raise RuntimeError(f"Pipeline produced no output. Errors: {runner.error_records}")

    if runner.error_records:
        _log.warning("Pipeline had %d errors: %s", len(runner.error_records), runner.error_records)

    return list(runner.fleet_with_climate_impact)


def extract_baseline_values(flights: list[FlightView]) -> dict[str, Any]:
    """Extract baseline values from output flights for perturbation.

    Returns a dict with baseline values keyed by flight_id.
    """
    baseline: dict[str, Any] = {
        "payload_factor": {},
        "takeoff_mass": {},
        "aircraft_mass": {},
        "fuel_flow": {},
        "engine_efficiency": {},
        "hydrogen_content": {},
        "q_fuel": {},
    }

    for flight in flights:
        flight_id = flight.attrs.get("flight_id", "unknown")

        # Scalar attrs (use defaults if not present)
        baseline["payload_factor"][flight_id] = flight.attrs.get(
            "payload_factor", DEFAULT_PAYLOAD_FACTOR
        )
        baseline["hydrogen_content"][flight_id] = flight.attrs.get(
            "hydrogen_content", DEFAULT_HYDROGEN_CONTENT
        )
        baseline["q_fuel"][flight_id] = flight.attrs.get("q_fuel", DEFAULT_Q_FUEL)

        # Takeoff mass = first value of aircraft_mass column
        aircraft_mass = flight["aircraft_mass"]
        baseline["takeoff_mass"][flight_id] = float(aircraft_mass[0])

        # Column values (as numpy arrays)
        baseline["aircraft_mass"][flight_id] = np.array(aircraft_mass)
        baseline["fuel_flow"][flight_id] = np.array(flight["fuel_flow"])
        baseline["engine_efficiency"][flight_id] = np.array(flight["engine_efficiency"])

    return baseline


def apply_payload_factor(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,
) -> list[dict[str, Any]]:
    """Apply perturbed payload_factor (load_factor) to input flights.

    Note: In NM JSON format, payload_factor is stored as 'load_factor'
    in aircraft_properties.
    """
    data = copy.deepcopy(input_data)
    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        base_value = baseline["payload_factor"].get(flight_id, DEFAULT_PAYLOAD_FACTOR)
        # Ensure aircraft_properties exists
        ap = flight["flight_information"].setdefault("aircraft_properties", {})
        ap["load_factor"] = base_value * factor
    return data


def apply_takeoff_mass(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,
) -> list[dict[str, Any]]:
    """Apply perturbed takeoff_mass to input flights.

    Note: In NM JSON format, takeoff_mass is stored in aircraft_properties.
    """
    data = copy.deepcopy(input_data)
    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        base_value = baseline["takeoff_mass"].get(flight_id)
        if base_value is not None:
            # Ensure aircraft_properties exists
            ap = flight["flight_information"].setdefault("aircraft_properties", {})
            ap["takeoff_mass"] = base_value * factor
    return data


def apply_aircraft_mass_column(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,
) -> list[dict[str, Any]]:
    """Apply perturbed aircraft_mass column to input flights."""
    data = copy.deepcopy(input_data)
    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        base_values = baseline["aircraft_mass"].get(flight_id)
        if base_values is not None:
            perturbed = (base_values * factor).tolist()
            trajectory_data = flight["flight_information"]["trajectory"]["trajectory_data"]
            for i, waypoint in enumerate(trajectory_data):
                if i < len(perturbed):
                    waypoint["am"] = perturbed[i]
    return data


def apply_fuel_flow_column(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,
) -> list[dict[str, Any]]:
    """Apply perturbed fuel_flow column to input flights."""
    data = copy.deepcopy(input_data)
    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        base_values = baseline["fuel_flow"].get(flight_id)
        if base_values is not None:
            perturbed = (base_values * factor).tolist()
            trajectory_data = flight["flight_information"]["trajectory"]["trajectory_data"]
            for i, waypoint in enumerate(trajectory_data):
                if i < len(perturbed):
                    waypoint["ff"] = perturbed[i]
    return data


def apply_engine_efficiency_column(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,
) -> list[dict[str, Any]]:
    """Apply perturbed engine_efficiency column to input flights."""
    data = copy.deepcopy(input_data)
    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        base_values = baseline["engine_efficiency"].get(flight_id)
        if base_values is not None:
            perturbed = (base_values * factor).tolist()
            trajectory_data = flight["flight_information"]["trajectory"]["trajectory_data"]
            for i, waypoint in enumerate(trajectory_data):
                if i < len(perturbed):
                    waypoint["ee"] = perturbed[i]
    return data


def apply_hydrogen_content(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,
) -> list[dict[str, Any]]:
    """Apply perturbed hydrogen_content to input flights."""
    data = copy.deepcopy(input_data)
    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        base_value = baseline["hydrogen_content"].get(flight_id, DEFAULT_HYDROGEN_CONTENT)
        fuel_props = flight["flight_information"].get("fuel_properties", {})
        fuel_props["hydrogen_content"] = base_value * factor
        flight["flight_information"]["fuel_properties"] = fuel_props
    return data


def apply_q_fuel(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,
) -> list[dict[str, Any]]:
    """Apply perturbed calorific_value (q_fuel) to input flights."""
    data = copy.deepcopy(input_data)
    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        base_value = baseline["q_fuel"].get(flight_id, DEFAULT_Q_FUEL)
        fuel_props = flight["flight_information"].get("fuel_properties", {})
        fuel_props["calorific_value"] = base_value * factor
        flight["flight_information"]["fuel_properties"] = fuel_props
    return data


def filter_input_to_match_outputs(
    input_data: list[dict[str, Any]],
    outputs: list[FlightView],
) -> list[dict[str, Any]]:
    """Filter input flights to only include those that succeeded in pipeline.

    This ensures input and output JSON files have matching flights.
    """
    # Get flight IDs from successful outputs
    output_ids = {f.attrs.get("flight_id") for f in outputs}

    # Filter input to only include flights that succeeded
    filtered = [
        flight
        for flight in input_data
        if flight["flight_information"]["flight_identification"] in output_ids
    ]

    if len(filtered) < len(input_data):
        _log.warning(
            "Filtered input from %d to %d flights (some flights failed in pipeline)",
            len(input_data),
            len(filtered),
        )

    return filtered


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Validate inputs
    if not args.input.exists():
        _log.error("Input file not found: %s", args.input)
        return 1

    if not args.weather_path.is_dir():
        _log.error("Weather path not found: %s", args.weather_path)
        return 1

    if not args.bada_path.is_dir():
        _log.error("BADA path not found: %s", args.bada_path)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Derive base name from input file
    base_name = args.input.stem.replace("_input", "")
    _log.info("Base name: %s", base_name)

    # Create Zarr paths
    zarr_paths = create_zarr_paths(args.weather_path)

    # Load original input
    original_input = load_input(args.input)
    _log.info("Loaded %d flights from input", len(original_input))

    # === Pass 1: Generate default case and extract baseline ===
    _log.info("=" * 60)
    _log.info("Pass 1: Generating default case")
    _log.info("=" * 60)

    default_input_path = args.output_dir / f"{base_name}_input.json"
    default_output_path = args.output_dir / f"{base_name}_output.json"

    if not args.skip_default:
        # Save default input (copy of original)
        save_input(original_input, default_input_path)

        # Run pipeline
        _log.info("Running pipeline on default case...")
        default_outputs = run_pipeline(default_input_path, zarr_paths, args.bada_path)
        save_output(default_outputs, default_output_path)
    else:
        _log.info("Skipping default case (--skip-default)")
        # Load existing output to extract baseline
        with open(default_output_path, encoding="utf-8") as f:
            data = json.load(f)
        default_outputs = [FlightView.from_dict(d) for d in data]

    # Extract baseline values for perturbation
    baseline = extract_baseline_values(default_outputs)
    _log.info("Extracted baseline values from %d flights", len(default_outputs))

    # === Pass 2: Generate perturbed cases ===
    _log.info("=" * 60)
    _log.info("Pass 2: Generating perturbed cases")
    _log.info("=" * 60)

    # Define all test cases: (suffix, modifier_function, perturbation_key)
    test_cases = [
        ("payload_factor", apply_payload_factor, "payload_factor"),
        ("takeoff_mass", apply_takeoff_mass, "takeoff_mass"),
        ("aircraft_mass_col", apply_aircraft_mass_column, "aircraft_mass_col"),
        ("fuel_flow_col", apply_fuel_flow_column, "fuel_flow_col"),
        ("engine_efficiency_col", apply_engine_efficiency_column, "engine_efficiency_col"),
        ("hydrogen_content", apply_hydrogen_content, "hydrogen_content"),
        ("q_fuel", apply_q_fuel, "q_fuel"),
    ]

    for suffix, modifier_fn, perturb_key in test_cases:
        _log.info("-" * 40)
        _log.info("Generating case: %s (factor=%.3f)", suffix, PERTURBATIONS[perturb_key])

        # Apply modification
        modified_input = modifier_fn(original_input, baseline, PERTURBATIONS[perturb_key])

        # Save modified input to temporary path first
        case_input_path = args.output_dir / f"{base_name}_{suffix}_input.json"
        save_input(modified_input, case_input_path)

        # Run pipeline
        _log.info("Running pipeline...")
        try:
            outputs = run_pipeline(case_input_path, zarr_paths, args.bada_path)

            # Filter input to only include flights that succeeded
            filtered_input = filter_input_to_match_outputs(modified_input, outputs)

            # Re-save filtered input (overwrite)
            save_input(filtered_input, case_input_path)

            # Save output
            case_output_path = args.output_dir / f"{base_name}_{suffix}_output.json"
            save_output(outputs, case_output_path)
        except Exception as e:
            _log.error("Failed to generate case %s: %s", suffix, e)
            # Remove the input file if pipeline failed completely
            if case_input_path.exists():
                case_input_path.unlink()
            continue

    _log.info("=" * 60)
    _log.info("Done! Generated golden test cases in: %s", args.output_dir)
    _log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
