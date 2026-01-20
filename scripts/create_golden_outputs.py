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
from dataclasses import dataclass
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
PERTURBATIONS: dict[str, float] = {
    "payload_factor": 0.85,  # 85% of default (1.0 -> 0.85)
    "takeoff_mass": 1.02,  # 102% of baseline
    "aircraft_mass_col": 0.995,  # 99.5% of baseline (small to avoid BADA failures)
    "fuel_flow_col": 1.03,  # 103% of baseline
    "engine_efficiency_col": 0.97,  # 97% of baseline
    "hydrogen_content": 1.02,  # 102% of default (13.79 -> ~14.07)
    "q_fuel": 0.98,  # 98% of default (42.8M -> ~41.9M)
    "mixed_columns": 1.0,  # Not used, but kept for interface consistency
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


@dataclass
class PipelineResult:
    """Result of running the pipeline on a set of flights."""

    outputs: list[FlightView]
    errors: list[dict[str, Any]]

    @property
    def num_succeeded(self) -> int:
        """Number of flights that succeeded."""
        return len(self.outputs)

    @property
    def num_failed(self) -> int:
        """Number of flights that failed."""
        return len(self.errors)

    def get_failed_flight_ids(self) -> set[str]:
        """Get the set of flight IDs that failed."""
        return {err.get("flight_id", "unknown") for err in self.errors}


def run_pipeline(
    input_path: Path,
    zarr_paths: ZarrPaths,
    bada_path: Path,
) -> PipelineResult:
    """Run FleetRunner pipeline and return results with error information.

    Args:
        input_path: Path to input JSON file
        zarr_paths: Weather data paths
        bada_path: Path to BADA data directory

    Returns:
        PipelineResult containing successful outputs and error records
    """
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

    return PipelineResult(
        outputs=list(runner.fleet_with_climate_impact),
        errors=list(runner.error_records) if runner.error_records else [],
    )


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


def apply_mixed_columns(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,  # Not used, kept for interface consistency
) -> list[dict[str, Any]]:
    """Apply different optional columns to different flights.

    This creates a heterogeneous input where flights have different columns,
    testing the FleetRunner's ability to handle column harmonization.

    Column assignment pattern:
    - Flight 0: fuel_flow only
    - Flight 1: aircraft_mass only
    - Flight 2: engine_efficiency only
    - Flight 3: all three columns (fuel_flow, aircraft_mass, engine_efficiency)
    - Flight 4+: no optional columns

    Args:
        input_data: Original input flight data
        baseline: Baseline values extracted from default case outputs
        factor: Perturbation factor (not used, kept for interface consistency)

    Returns:
        Modified input with heterogeneous columns across flights
    """
    data = copy.deepcopy(input_data)

    # Define which columns each flight should have
    # Pattern: [(has_fuel_flow, has_aircraft_mass, has_engine_efficiency), ...]
    column_patterns = [
        (True, False, False),  # Flight 0: fuel_flow only
        (False, True, False),  # Flight 1: aircraft_mass only
        (False, False, True),  # Flight 2: engine_efficiency only
        (True, True, True),  # Flight 3: all columns
        (False, False, False),  # Flight 4+: no optional columns
    ]

    for idx, flight in enumerate(data):
        flight_id = flight["flight_information"]["flight_identification"]
        trajectory_data = flight["flight_information"]["trajectory"]["trajectory_data"]

        # Get pattern for this flight (cycle if more flights than patterns)
        pattern_idx = idx % len(column_patterns)
        has_ff, has_am, has_ee = column_patterns[pattern_idx]

        # Get baseline values for this flight
        ff_values = baseline["fuel_flow"].get(flight_id)
        am_values = baseline["aircraft_mass"].get(flight_id)
        ee_values = baseline["engine_efficiency"].get(flight_id)

        # Apply columns based on pattern
        for i, waypoint in enumerate(trajectory_data):
            if has_ff and ff_values is not None and i < len(ff_values):
                waypoint["ff"] = float(ff_values[i])
            if has_am and am_values is not None and i < len(am_values):
                waypoint["am"] = float(am_values[i])
            if has_ee and ee_values is not None and i < len(ee_values):
                waypoint["ee"] = float(ee_values[i])

        _log.debug(
            "Flight %d (%s): ff=%s, am=%s, ee=%s",
            idx,
            flight_id,
            has_ff,
            has_am,
            has_ee,
        )

    return data


def filter_input_to_match_outputs(
    input_data: list[dict[str, Any]],
    result: PipelineResult,
) -> list[dict[str, Any]]:
    """Filter input flights to only include those that succeeded in pipeline.

    This ensures input and output JSON files have matching flights.

    Args:
        input_data: Original input flight data
        result: Pipeline result containing outputs and errors

    Returns:
        Filtered list of input flights matching successful outputs
    """
    # Get flight IDs from successful outputs
    output_ids = {f.attrs.get("flight_id") for f in result.outputs}

    # Filter input to only include flights that succeeded
    filtered = [
        flight
        for flight in input_data
        if flight["flight_information"]["flight_identification"] in output_ids
    ]

    # Log detailed information about failed flights
    if result.num_failed > 0:
        _log.warning("=" * 60)
        _log.warning("PIPELINE FAILURES: %d flight(s) failed", result.num_failed)
        _log.warning("=" * 60)
        for error in result.errors:
            flight_id = error.get("flight_id", "unknown")
            error_msg = error.get("error", "Unknown error")
            step = error.get("step", "unknown step")
            _log.warning("  Flight '%s' failed at step '%s':", flight_id, step)
            _log.warning("    Error: %s", error_msg)
        _log.warning("-" * 60)
        _log.warning(
            "Filtered input: %d -> %d flights (excluded failed flights)",
            len(input_data),
            len(filtered),
        )
        _log.warning("=" * 60)

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
        default_result = run_pipeline(default_input_path, zarr_paths, args.bada_path)

        if default_result.num_failed > 0:
            _log.warning(
                "Default case had %d failures - these flights will be excluded from all cases",
                default_result.num_failed,
            )
            # Filter input to match successful outputs
            filtered_input = filter_input_to_match_outputs(original_input, default_result)
            save_input(filtered_input, default_input_path)
            # Update original_input to only include successful flights
            original_input = filtered_input

        save_output(default_result.outputs, default_output_path)
        default_outputs = default_result.outputs
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
    test_cases: list[tuple[str, Any, str]] = [
        ("payload_factor", apply_payload_factor, "payload_factor"),
        ("takeoff_mass", apply_takeoff_mass, "takeoff_mass"),
        ("aircraft_mass_col", apply_aircraft_mass_column, "aircraft_mass_col"),
        ("fuel_flow_col", apply_fuel_flow_column, "fuel_flow_col"),
        ("engine_efficiency_col", apply_engine_efficiency_column, "engine_efficiency_col"),
        ("hydrogen_content", apply_hydrogen_content, "hydrogen_content"),
        ("q_fuel", apply_q_fuel, "q_fuel"),
        # Special case: tests FleetRunner's column harmonization with heterogeneous inputs
        ("mixed_columns", apply_mixed_columns, "mixed_columns"),
    ]

    for suffix, modifier_fn, perturb_key in test_cases:
        _log.info("-" * 40)
        _log.info("Generating case: %s (factor=%.3f)", suffix, PERTURBATIONS[perturb_key])

        # Apply modification to the (possibly filtered) original input
        modified_input = modifier_fn(original_input, baseline, PERTURBATIONS[perturb_key])

        # Save modified input to temporary path first
        case_input_path = args.output_dir / f"{base_name}_{suffix}_input.json"
        save_input(modified_input, case_input_path)

        # Run pipeline
        _log.info("Running pipeline...")
        try:
            result = run_pipeline(case_input_path, zarr_paths, args.bada_path)

            # Filter input to only include flights that succeeded
            filtered_input = filter_input_to_match_outputs(modified_input, result)

            # Re-save filtered input (overwrite)
            save_input(filtered_input, case_input_path)

            # Save output
            case_output_path = args.output_dir / f"{base_name}_{suffix}_output.json"
            save_output(result.outputs, case_output_path)

            # Summary for this case
            _log.info(
                "Case '%s': %d succeeded, %d failed",
                suffix,
                result.num_succeeded,
                result.num_failed,
            )
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
