#!/usr/bin/env python3
"""Generate golden test cases for PyNeats pipeline testing.

This script creates multiple golden test cases from a single input JSON by:
1. Running the default case to get baseline values
2. Creating perturbed variations of the input via :func:apply_parameters
3. Running the pipeline on each variation
4. Saving input/output pairs to the golden test directory

Two generation modes are available, both called sequentially from :func:main:

Mode 1 Per-File Legacy Generation (:func:generate_per_file_golden):
    Preserves the existing per-test-case *_input.json / *_output.json
    file-pair generation for backward compatibility with test_pipeline.py.

Mode 2 Aggregated Single-File Generation (:func:generate_aggregated_golden):
    Produces one combined input JSON and one combined output JSON containing
    one flight per test case.
    Error-expectation cases are included their errors propagate via the
    fleet runner's error_records.

All test case specifications are defined declaratively in :func:build_test_cases
using :class:TestCaseSpec. Each case is built from scratch via
:func:apply_parameters, the unified applicator that maps parameter names to
NM JSON locations through :data:PARAMETER_REGISTRY.

Usage:
    python scripts/create_golden_outputs.py \\
        --input tests/data/golden/fleet_5_flights_input.json \\
        --weather-path /path/to/weather \\
        --bada-path /path/to/bada \\
        --output-dir tests/data/golden

Test cases generated:
    Default & reference
        - {base}_input / {base}_output: Default (no modifications)
        - {base}_ref: All optional params populated at baseline, validated against schema

    Single-parameter perturbations (one param each, at its perturbation factor)
        - {base}_payload_factor: payload_factor in attrs
        - {base}_takeoff_mass: takeoff_mass in attrs
        - {base}_aircraft_mass_col: aircraft_mass column
        - {base}_fuel_flow_col: fuel_flow column
        - {base}_engine_efficiency_col: engine_efficiency column
        - {base}_q_fuel: calorific_value (q_fuel) in fuel_properties

    Legacy mixed-pattern cases (custom per-flight heterogeneity)
        - {base}_mixed_columns: different flights have different columns
        - {base}_mixed_attrs: different flights have different attributes

    Aggregated (Mode 2)
        - {base}_aggregated_input / {base}_aggregated_output:
          One flight per TC (except ref and mixed), including error-expectation TCs
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyneats.core.neats_default_parameters import (
    DEFAULT_AROMATICS_CONTENT,
    DEFAULT_HYDROGEN_CONTENT,
    DEFAULT_NAPHTHALEN_CONTENT,
    DEFAULT_PAYLOAD_FACTOR,
    DEFAULT_Q_FUEL,
    DEFAULT_SULPHUR_CONTENT,
)
from pyneats.core.views import FlightView
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter
from pyneats.steps.weather.weather_store import ZarrPaths

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Modification:
    """A single declarative mutation to apply to all flights in the input.

    Each modification targets a path inside flight_information and
    sets it to the given value. Fields that are not included in a
    :class:TestCaseSpec params dict are simply never written, so
    omission is handled by :func:apply_parameters.

    Aircraft properties (aircraft_properties.<field>):
    Target                                   Example
    aircraft_properties.aircraft_type(str)   Modification("aircraft_properties.aircraft_type", "B737-800W")
    aircraft_properties.aircraft_type(str)   Modification("aircraft_properties.aircraft_type", "AT72")
    aircraft_properties.aircraft_type(str)   Modification("aircraft_properties.aircraft_type", "ZZZZ")
    aircraft_properties.engine_uid(str)      Modification("aircraft_properties.engine_uid", "PW4060")
    aircraft_properties.engine_uid(str)      Modification("aircraft_properties.engine_uid", "CFM56-FAKE")
    aircraft_properties.engine_uid(str)      Modification("aircraft_properties.engine_uid", "LEAP-1A26")
    aircraft_properties.takeoff_mass(float)  Modification("aircraft_properties.takeoff_mass", 10000.0)
    aircraft_properties.takeoff_mass(float)  Modification("aircraft_properties.takeoff_mass", 999999.0)
    aircraft_properties.load_factor(float)   Modification("aircraft_properties.load_factor", 1.5)

    Fuel properties (fuel_properties.<field>):
    Target                                  Example
    fuel_properties.hydrogen_content(float) Modification("fuel_properties.hydrogen_content", 14.0)
    fuel_properties.calorific_value(float)  Modification("fuel_properties.calorific_value", 43_000_000.0)
    fuel_properties.aromatic_content(float) Modification("fuel_properties.aromatic_content", 0.30)
    fuel_properties.sulphur(float)          Modification("fuel_properties.sulphur", 0.005)
    fuel_properties.naphthalene(float)      Modification("fuel_properties.naphthalene", 0.04)

    Trajectory columns (trajectory.<json_field>):
    Target                  Example
    trajectory.am(callable) Modification("trajectory.am", _make_non_decreasing_mass)
    trajectory.am(callable) Modification("trajectory.am", _make_exceeds_mtow_mass)
    trajectory.am(float)    Modification("trajectory.am", 1.05)  (factor applied to baseline)
    trajectory.ff(float)    Modification("trajectory.ff", 0.95)
    trajectory.ee(float)    Modification("trajectory.ee", 1.02)
    trajectory.tasfloat)    Modification("trajectory.tas", 0.98)

    For trajectory columns the value can be:
    - A callable (baseline_arr, n_waypoints) -> list[float] that
      receives the baseline array and returns the replacement values.
    - A numeric factor applied element-wise: baseline[i] * factor.

    Attributes
    ----------
    target : str
        Dot-path into the NM JSON flight_information.
    value : Any
        The value to set (scalar, float factor, or callable for trajectory).
    """

    target: str
    value: Any


def _apply_single_modification(
    fi: dict[str, Any],
    flight_id: str,
    baseline: dict[str, Any],
    mod: Modification,
) -> None:
    """Apply one :class:Modification to a single flight's flight_information dict."""
    parts = mod.target.split(".")

    if parts[0] in ("aircraft_properties", "fuel_properties"):
        section = fi.setdefault(parts[0], {})
        section[parts[1]] = mod.value

    elif parts[0] == "trajectory":
        field = parts[1]
        waypoints = fi["trajectory"]["trajectory_data"]

        # Resolve JSON short name (am, ff, …) to internal baseline key
        internal = next(
            (
                s.internal_name
                for s in PARAMETER_REGISTRY.values()
                if s.category == "column" and s.json_field == field
            ),
            field,
        )
        base_arr = baseline.get(internal, {}).get(flight_id)

        if callable(mod.value):
            new_values = mod.value(base_arr, len(waypoints))
            for i, wp in enumerate(waypoints):
                if i < len(new_values):
                    wp[field] = new_values[i]
        elif isinstance(mod.value, (int, float)):
            if base_arr is not None:
                for i, wp in enumerate(waypoints):
                    if i < len(base_arr):
                        wp[field] = float(base_arr[i]) * mod.value


def _modify_flight(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    modifications: list[Modification],
) -> list[dict[str, Any]]:
    """Apply a list of declarative :class:Modification objects to all flights.

    This is the single entry point for all structural mutations (aircraft type
    changes, engine UID overrides, mass column patterns, etc.) that cannot be
    expressed as simple numeric perturbation factors.

    Args:
        input_data: NM JSON flights
        baseline: Baseline values from :func:extract_baseline_values
        modifications: Ordered list of mutations to apply

    Returns:
        Deep-copied input with all modifications applied.
    """
    data = copy.deepcopy(input_data)

    for flight in data:
        fi = flight["flight_information"]
        flight_id = fi["flight_identification"]

        for mod in modifications:
            _apply_single_modification(fi, flight_id, baseline, mod)

    return data


def _make_non_decreasing_mass(
    baseline_arr: np.ndarray | None,
    n_waypoints: int,
) -> list[float]:
    """Create a mass array that increases at some points (violates monotonicity)."""
    if baseline_arr is None:
        return [70000.0] * n_waypoints
    arr = list(float(v) for v in baseline_arr)
    mid = len(arr) // 2
    if mid > 0:
        arr[mid] = arr[mid - 1] + 100.0  # bump up one point
    return arr


def _make_exceeds_mtow_mass(
    baseline_arr: np.ndarray | None,
    n_waypoints: int,
) -> list[float]:
    """Create a mass array with some values above ~78000 kg MTOW
    (mass takeoff weight) for A320.
    """
    if baseline_arr is None:
        return [85000.0] * n_waypoints
    arr = list(float(v) for v in baseline_arr)
    arr[0] = 85000.0  # exceed MTOW at first waypoint
    return arr


@dataclass(frozen=True)
class ParamSpec:
    """Specification for a single perturbable parameter.
    Parameter registry: single source of truth for all perturbable parameters

    Attributes
    ----------
    internal_name : str
        Key in baseline dict / FlightView attrs or columns.
    category : str
        "attr" for scalar flight attributes, "column" for trajectory arrays.
    json_section : str
        NM JSON section: "aircraft_properties", "fuel_properties", or "trajectory".
    json_field : str
        Field name in the NM JSON structure.
    default_value : Any
        Default constant from neats_default_parameters, or None.
    is_numeric : bool
        Whether a perturbation factor applies (False for strings like engine_uid).
    """

    internal_name: str
    category: str
    json_section: str
    json_field: str
    default_value: Any
    is_numeric: bool


PARAMETER_REGISTRY: dict[str, ParamSpec] = {
    # aircraft attrs
    "payload_factor": ParamSpec(
        "payload_factor",
        "attr",
        "aircraft_properties",
        "load_factor",
        DEFAULT_PAYLOAD_FACTOR,
        True,
    ),
    "takeoff_mass": ParamSpec(
        "takeoff_mass",
        "attr",
        "aircraft_properties",
        "takeoff_mass",
        None,
        True,
    ),
    "engine_uid": ParamSpec(
        "engine_uid",
        "attr",
        "aircraft_properties",
        "engine_uid",
        None,
        False,
    ),
    # fuel attrs
    "hydrogen_content": ParamSpec(
        "hydrogen_content",
        "attr",
        "fuel_properties",
        "hydrogen_content",
        DEFAULT_HYDROGEN_CONTENT,
        True,
    ),
    "h_c_ratio": ParamSpec(
        "h_c_ratio",
        "attr",
        "fuel_properties",
        "hydrogen_per_carbon_ratio",
        None,
        True,
    ),
    "aromatic_content": ParamSpec(
        "aromatic_content",
        "attr",
        "fuel_properties",
        "aromatic_content",
        DEFAULT_AROMATICS_CONTENT,
        True,
    ),
    "q_fuel": ParamSpec(
        "q_fuel",
        "attr",
        "fuel_properties",
        "calorific_value",
        DEFAULT_Q_FUEL,
        True,
    ),
    "naphthalene": ParamSpec(
        "naphthalene",
        "attr",
        "fuel_properties",
        "naphthalene",
        DEFAULT_NAPHTHALEN_CONTENT,
        True,
    ),
    "sulphur_content": ParamSpec(
        "sulphur_content",
        "attr",
        "fuel_properties",
        "sulphur",
        DEFAULT_SULPHUR_CONTENT,
        True,
    ),
    # trajectory columns
    "fuel_flow": ParamSpec(
        "fuel_flow",
        "column",
        "trajectory",
        "ff",
        None,
        True,
    ),
    "engine_efficiency": ParamSpec(
        "engine_efficiency",
        "column",
        "trajectory",
        "ee",
        None,
        True,
    ),
    "aircraft_mass": ParamSpec(
        "aircraft_mass",
        "column",
        "trajectory",
        "am",
        None,
        True,
    ),
    "true_airspeed": ParamSpec(
        "true_airspeed",
        "column",
        "trajectory",
        "tas",
        None,
        True,
    ),
}


# Perturbation factors for single-parameter test cases
PERTURBATIONS: dict[str, float] = {
    "payload_factor": 0.85,  # 85% of default (1.0 -> 0.85)
    "takeoff_mass": 1.02,  # 102% of baseline
    "aircraft_mass_col": 0.995,  # 99.5% of baseline (small to avoid BADA failures)
    "fuel_flow_col": 1.03,  # 103% of baseline
    "engine_efficiency_col": 0.97,  # 97% of baseline
    "true_airspeed_col": 1.01,  # 101% of baseline
    "hydrogen_content": 1.02,  # 102% of default (13.79 -> ~14.07)
    "q_fuel": 0.98,  # 98% of default (42.8M -> ~41.9M)
    "aromatic_content": 1.05,  # 105% of default (0.25 -> ~0.2625)
    "sulphur": 1.10,  # 110% of default (0.003 -> ~0.0033)
    "naphthalene": 0.95,  # 95% of default (0.03 -> ~0.0285)
    "mixed_columns": 1.0,  # Legacy: not a factor, kept for interface consistency
    "mixed_attrs": 1.0,  # Legacy: not a factor, kept for interface consistency
}


# Aggregated-mode flight selections one flight per TC, never EAF2143 (fails).
# Round-robin across the four reliable flights.
AGGREGATED_FLIGHT_SELECTIONS: dict[str, str] = {
    # Aircraft type cases
    "tc_ac_overspec": "RYR46YN",
    "tc_ac_no_bada4": "ACA812",
    "tc_ac_no_bada": "UAE62Y",  # expect_error: fleet propagates error
    # Engine cases
    "tc_eng_unspec": "FDX5067",
    "tc_eng_mismatch": "RYR46YN",
    "tc_eng_unknown": "ACA812",
    # Mass strategy cases
    "tc_mass_all_unspec": "UAE62Y",
    "tc_mass_no_tom_no_lf": "FDX5067",
    "tc_mass_no_am_no_lf": "RYR46YN",
    "tc_mass_no_am_no_tom": "ACA812",
    "tc_mass_no_am": "UAE62Y",
    "tc_mass_no_tom": "FDX5067",
    "tc_mass_no_lf": "RYR46YN",
    # Mass validation / error cases
    "tc_mass_below_oew": "ACA812",  # expect_error: fleet propagates error
    "tc_mass_not_decreasing": "UAE62Y",  # expect_error: fleet propagates error
    "tc_mass_exceeds_mtow": "FDX5067",  # expect_error: fleet propagates error
    "tc_tom_exceeds_mtow": "RYR46YN",  # expect_error: fleet propagates error
    # Load factor clamping
    "tc_lf_gt_one": "ACA812",
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

    runner = FleetRunnerLargeEmitter(cfg)
    runner.eval()

    if runner.fleet_with_climate_impact is None:
        raise RuntimeError(f"Pipeline produced no output. Errors: {runner.error_records}")

    return PipelineResult(
        outputs=list(runner.fleet_with_climate_impact),
        errors=list(runner.error_records) if runner.error_records else [],
    )


def extract_baseline_values(flights: list[FlightView]) -> dict[str, Any]:
    """Extract baseline values from output flights for perturbation.

    Extracts all parameters defined in :data:PARAMETER_REGISTRY so that
    every schema-defined optional property is available for perturbation.

    Returns a dict with baseline values keyed by {internal_name: {flight_id: value}}.
    """
    baseline: dict[str, Any] = {spec.internal_name: {} for spec in PARAMETER_REGISTRY.values()}

    for flight in flights:
        flight_id = flight.attrs.get("flight_id", "unknown")

        # scalar attrs
        for spec in PARAMETER_REGISTRY.values():
            if spec.category != "attr":
                continue
            if spec.internal_name == "takeoff_mass":
                # Special case: derived from first aircraft_mass waypoint
                aircraft_mass = flight["aircraft_mass"]
                baseline["takeoff_mass"][flight_id] = float(aircraft_mass[0])
            else:
                baseline[spec.internal_name][flight_id] = flight.attrs.get(
                    spec.internal_name, spec.default_value
                )

        # column values (as numpy arrays)
        for spec in PARAMETER_REGISTRY.values():
            if spec.category != "column":
                continue
            if flight.has(spec.internal_name):
                baseline[spec.internal_name][flight_id] = np.array(flight[spec.internal_name])

    return baseline


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


def apply_mixed_attrs(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float,  # Not used, kept for interface consistency
) -> list[dict[str, Any]]:
    """Apply different optional attributes to different flights.

    This creates a heterogeneous input where flights have different optional
    attributes, testing the FleetRunner's ability to handle varying attrs.

    Attribute assignment pattern:
    - Flight 0: payload_factor only
    - Flight 1: takeoff_mass only
    - Flight 2: hydrogen_content only
    - Flight 3: q_fuel only
    - Flight 4+: all optional attrs

    Args:
        input_data: Original input flight data
        baseline: Baseline values extracted from default case outputs
        factor: Perturbation factor (not used, kept for interface consistency)

    Returns:
        Modified input with heterogeneous attributes across flights
    """
    data = copy.deepcopy(input_data)

    # Define which attrs each flight should have
    # Pattern: [(has_payload_factor, has_takeoff_mass, has_hydrogen_content, has_q_fuel), ...]
    attr_patterns = [
        (True, False, False, False),  # Flight 0: payload_factor only
        (False, True, False, False),  # Flight 1: takeoff_mass only
        (False, False, True, False),  # Flight 2: hydrogen_content only
        (False, False, False, True),  # Flight 3: q_fuel only
        (True, True, True, True),  # Flight 4+: all optional attrs
    ]

    for idx, flight in enumerate(data):
        flight_id = flight["flight_information"]["flight_identification"]

        # Get pattern for this flight (cycle if more flights than patterns)
        pattern_idx = idx % len(attr_patterns)
        has_pf, has_tom, has_hc, has_qf = attr_patterns[pattern_idx]

        # Get baseline values for this flight
        pf_value = baseline["payload_factor"].get(flight_id, DEFAULT_PAYLOAD_FACTOR)
        tom_value = baseline["takeoff_mass"].get(flight_id)
        hc_value = baseline["hydrogen_content"].get(flight_id, DEFAULT_HYDROGEN_CONTENT)
        qf_value = baseline["q_fuel"].get(flight_id, DEFAULT_Q_FUEL)

        # Ensure aircraft_properties and fuel_properties exist
        ap = flight["flight_information"].setdefault("aircraft_properties", {})
        fp = flight["flight_information"].setdefault("fuel_properties", {})

        # Apply attrs based on pattern
        if has_pf:
            ap["load_factor"] = pf_value
        if has_tom and tom_value is not None:
            ap["takeoff_mass"] = tom_value
        if has_hc:
            fp["hydrogen_content"] = hc_value
        if has_qf:
            fp["calorific_value"] = qf_value

        _log.debug(
            "Flight %d (%s): pf=%s, tom=%s, hc=%s, qf=%s",
            idx,
            flight_id,
            has_pf,
            has_tom,
            has_hc,
            has_qf,
        )

    return data


def apply_parameters(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    params: dict[str, float],
) -> list[dict[str, Any]]:
    """Apply one or more parameter perturbations to input flights.

    This is a unified applicator that can inject any combination of parameters
    defined in :data:PARAMETER_REGISTRY. Each parameter is looked up in the
    registry to determine its JSON location and whether it is a scalar attribute
    or a per-waypoint column.

    Args:
        input_data: Original NM JSON input flights.
        baseline: Baseline values from :func:extract_baseline_values.
        params: Dict mapping parameter name => perturbation factor.
            For numeric params the applied value is baseline * factor.
            For non-numeric params (e.g. engine_uid) the factor is ignored
            and the baseline value is injected as-is.

    Returns:
        Deep-copied input with the requested parameters applied.

    Raises:
        KeyError: If a param name is not in :data:PARAMETER_REGISTRY.
    """
    data = copy.deepcopy(input_data)

    for flight in data:
        flight_id = flight["flight_information"]["flight_identification"]
        fi = flight["flight_information"]

        for param_name, factor in params.items():
            spec = PARAMETER_REGISTRY[param_name]
            base_value = baseline[spec.internal_name].get(flight_id)

            # fall back to the default constant when no baseline exists
            if base_value is None and spec.default_value is not None:
                base_value = spec.default_value
            if base_value is None:
                continue

            if spec.category == "attr":
                section = fi.setdefault(spec.json_section, {})
                if spec.is_numeric:
                    section[spec.json_field] = base_value * factor
                else:
                    # non-numeric (e.g. engine_uid string): inject as-is
                    section[spec.json_field] = base_value

            elif spec.category == "column":
                perturbed = (base_value * factor).tolist()
                waypoints = fi["trajectory"]["trajectory_data"]
                for i, wp in enumerate(waypoints):
                    if i < len(perturbed):
                        wp[spec.json_field] = perturbed[i]

    return data


def _validate_against_schema(
    flights: list[dict[str, Any]],
    schema_path: str,
) -> None:
    """Validate each flight dict against the JSON schema.

    Logs a warning per flight that fails validation rather than raising,
    so the caller can decide whether to abort.

    Args:
        flights: List of NM JSON flight dicts (each wrapped in
            {"flight_information": {...}}).
        schema_path: Path to the authoritative JSON schema file.
    """
    try:
        import jsonschema
    except ImportError:
        _log.warning("jsonschema package not installed -> skipping schema validation")
        return

    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)

    validator = jsonschema.Draft202012Validator(schema)

    for idx, flight in enumerate(flights):
        errors = list(validator.iter_errors(flight))
        if errors:
            fid = flight.get("flight_information", {}).get("flight_identification", f"index-{idx}")
            for err in errors:
                _log.warning(
                    "Schema validation issue for flight '%s': %s (path: %s)",
                    fid,
                    err.message,
                    ".".join(str(p) for p in err.absolute_path),
                )


def apply_ref(
    input_data: list[dict[str, Any]],
    baseline: dict[str, Any],
    factor: float = 1.0,  # kept for interface consistency with other apply_* functions
    schema_path: str = str(Path(__file__).parent / "schemas/flight_schema.json"),
) -> list[dict[str, Any]]:
    """Apply ALL optional parameters at factor 1.0 to produce the reference case.

    The reference case has every optional field populated with its baseline
    value (no perturbation). After applying the parameters the result is
    validated against schemas/flight_schema.json to ensure completeness.

    Args:
        input_data: Original NM JSON input flights.
        baseline: Baseline values from :func:extract_baseline_values.
        factor: Ignored always uses 1.0 for the reference case.
        schema_path: Path to the JSON schema used for validation.

    Returns:
        Deep-copied input with every optional parameter populated.
    """
    all_params = {name: 1.0 for name in PARAMETER_REGISTRY}
    data = apply_parameters(input_data, baseline, all_params)

    _validate_against_schema(data, schema_path)
    return data


def _ref_params_except(*exclude: str) -> dict[str, float]:
    """Return all registry parameters at factor 1.0, minus the excluded ones.

    Instead of starting from a fully-populated reference and nulling fields
    out, each test case is built from scratch by including only the parameters
    it needs.

    Examples::

        # Everything except hydrogen_content
        apply_parameters(data, baseline, _ref_params_except("hydrogen_content"))

        # Everything except two fuel properties
        apply_parameters(data, baseline, _ref_params_except("q_fuel", "hydrogen_content"))

    Args:
        exclude: Parameter names (keys in :data:PARAMETER_REGISTRY) to omit.

    Returns:
        Dict of {param_name: 1.0} for every registered parameter not in exclude

    Raises:
        KeyError: If any name in exclude is not in :data:PARAMETER_REGISTRY.
    """
    unknown = set(exclude) - set(PARAMETER_REGISTRY)
    if unknown:
        raise KeyError(f"Unknown parameter(s) to exclude: {unknown}")
    return {name: 1.0 for name in PARAMETER_REGISTRY if name not in exclude}


@dataclass
class TestCaseSpec:
    """Declarative specification for a single golden test case.

    Attributes
    ----------
    suffix : str
        File name suffix, e.g. "ref" => {base}_ref_input.json.
    params : dict[str, float]
        Parameter names => perturbation factors passed to :func:apply_parameters.
        An empty dict means "no optional parameters" (bare input).
    description : str
        Note for logging.
    validate_schema : bool
        If True, validate the generated input against the flight schema.
    modifications : list[Modification] | None
        Optional list of structural mutations applied after numeric perturbations.
        Processed by :func:_modify_flight.
    expect_error : bool
        If True, the pipeline is expected to fail for all flights. Only the
        input and error metadata are saved (no golden output).
    """

    suffix: str
    params: dict[str, float]
    description: str = ""
    validate_schema: bool = False
    modifications: list[Modification] | None = None
    expect_error: bool = False


def build_test_cases_legacy() -> list[TestCaseSpec]:
    """Build test case specs for Mode 1 (per-file legacy generation).

    This produces the original set of golden test cases that predates the
    tc_* naming convention: reference case, single-parameter perturbations.

    Legacy mixed-pattern cases (mixed_columns, mixed_attrs) are NOT
    included here, they use custom per-flight logic and are handled directly
    in :func:generate_per_file_golden.

    Returns:
        Ordered list of :class:TestCaseSpec for Mode 1 generation.
    """
    all_params = {name: 1.0 for name in PARAMETER_REGISTRY}
    cases: list[TestCaseSpec] = []

    # 1. Reference case: all params at baseline
    cases.append(
        TestCaseSpec(
            suffix="ref",
            params=all_params,
            description="TC_REF: all optional params at baseline",
            validate_schema=True,
        )
    )

    # 2. Single-parameter perturbation cases
    single_param_cases: list[tuple[str, str, float]] = [
        # (suffix, registry_param_name, factor)
        ("payload_factor", "payload_factor", PERTURBATIONS["payload_factor"]),
        ("takeoff_mass", "takeoff_mass", PERTURBATIONS["takeoff_mass"]),
        ("aircraft_mass_col", "aircraft_mass", PERTURBATIONS["aircraft_mass_col"]),
        ("fuel_flow_col", "fuel_flow", PERTURBATIONS["fuel_flow_col"]),
        ("engine_efficiency_col", "engine_efficiency", PERTURBATIONS["engine_efficiency_col"]),
        ("q_fuel", "q_fuel", PERTURBATIONS["q_fuel"]),
    ]
    for suffix, param_name, factor in single_param_cases:
        cases.append(
            TestCaseSpec(
                suffix=suffix,
                params={param_name: factor},
                description=f"Single perturbation: {param_name} at {factor:.3f}",
            )
        )

    return cases


def build_test_cases() -> list[TestCaseSpec]:
    """Build test case specs for Mode 2 (tc_* test cases only).

    These are the structured test cases that exercise specific pipeline
    behaviours: aircraft type resolution, engine UID handling, mass strategy
    selection, and error/validation paths.

    Returns:
        Ordered list of :class:TestCaseSpec for Mode 2 generation.
    """
    all_params = {name: 1.0 for name in PARAMETER_REGISTRY}
    cases: list[TestCaseSpec] = []

    # Aircraft type cases (TC_AC_*)
    # TC_AC_OVERSPEC: overspecified AC type => BADA mapper remapping
    cases.append(
        TestCaseSpec(
            suffix="tc_ac_overspec",
            params=all_params,
            modifications=[Modification("aircraft_properties.aircraft_type", "B737-800W")],
            description="TC_AC_OVERSPEC: overspecified AC type: tests BADA mapper remapping",
        )
    )
    # TC_AC_NO_BADA4: AC only in BADA3 => fallback to BADA3
    cases.append(
        TestCaseSpec(
            suffix="tc_ac_no_bada4",
            params=all_params,
            modifications=[Modification("aircraft_properties.aircraft_type", "AT72")],
            description="TC_AC_NO_BADA4: AC type only in BADA3: tests BADA3 fallback",
        )
    )
    # TC_AC_NO_BADA: completely unknown AC type => abort
    cases.append(
        TestCaseSpec(
            suffix="tc_ac_no_bada",
            params=all_params,
            modifications=[Modification("aircraft_properties.aircraft_type", "ZZZZ")],
            description="TC_AC_NO_BADA: unknown AC type: expects abort",
            expect_error=True,
        )
    )

    # Engine cases (TC_ENG_*)
    # TC_ENG_UNSPEC: no engine_uid => select representative/conservative
    cases.append(
        TestCaseSpec(
            suffix="tc_eng_unspec",
            params=_ref_params_except("engine_uid"),
            description="TC_ENG_UNSPEC: no engine UID: select representative/conservative",
        )
    )
    # TC_ENG_MISMATCH: engine UID doesn't match AC => drop and use default
    cases.append(
        TestCaseSpec(
            suffix="tc_eng_mismatch",
            params=all_params,
            modifications=[Modification("aircraft_properties.engine_uid", "PW4060")],
            description="TC_ENG_MISMATCH: engine UID mismatch: drop and use default",
        )
    )
    # TC_ENG_UNKNOWN: known AC, unknown engine UID => use predecessor/successor
    cases.append(
        TestCaseSpec(
            suffix="tc_eng_unknown",
            params=all_params,
            modifications=[Modification("aircraft_properties.engine_uid", "CFM56-FAKE")],
            description="TC_ENG_UNKNOWN: unknown engine UID: use predecessor/successor",
        )
    )
    # TC_ENG_LEANBURN: lean-burn engine => lean for perf, rich for emissions
    # !!!! NOT IN USE !!! => see email to not test lean burn mapping for now
    # cases.append(TestCaseSpec(
    #     suffix="tc_eng_leanburn",
    #     params=all_params,
    #     modifications=[Modification("aircraft_properties.engine_uid", "LEAP-1A26")],
    #     description="TC_ENG_LEANBURN: lean-burn engine: lean for perf, rich for emissions",
    # ))

    # Mass strategy cases (TC_MASS_*: success)
    # TC_MASS_ALL_UNSPEC: no mass info at all => LF=1 iterative
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_all_unspec",
            params={},
            description="TC_MASS_ALL_UNSPEC: no mass params => LF=1 iterative",
        )
    )
    # TC_MASS_NO_TOM_NO_LF: only aircraft_mass column
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_no_tom_no_lf",
            params={"aircraft_mass": 0.97},
            description="TC_MASS_NO_TOM_NO_LF: only AM column",
        )
    )
    # TC_MASS_NO_AM_NO_LF: only takeoff_mass attr
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_no_am_no_lf",
            params={"takeoff_mass": 0.97},
            description="TC_MASS_NO_AM_NO_LF: only TOM attr",
        )
    )
    # TC_MASS_NO_AM_NO_TOM: only payload_factor attr
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_no_am_no_tom",
            params={"payload_factor": 0.8},
            description="TC_MASS_NO_AM_NO_TOM: only LF attr",
        )
    )
    # TC_MASS_NO_AM: takeoff_mass + payload_factor, no aircraft_mass
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_no_am",
            params={"takeoff_mass": 0.97, "payload_factor": 0.8},
            description="TC_MASS_NO_AM: TOM+LF, no AM",
        )
    )
    # TC_MASS_NO_TOM: aircraft_mass + payload_factor, no takeoff_mass
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_no_tom",
            params={"aircraft_mass": 0.97, "payload_factor": 0.8},
            description="TC_MASS_NO_TOM: AM+LF, no TOM",
        )
    )
    # TC_MASS_NO_LF: aircraft_mass + takeoff_mass, no payload_factor
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_no_lf",
            params={"aircraft_mass": 0.97, "takeoff_mass": 0.97},
            description="TC_MASS_NO_LF: AM+TOM, no LF",
        )
    )

    # Mass validation / error cases (TC_MASS_* => expects abort)
    # TC_MASS_BELOW_OEW: takeoff mass below OEW => abort
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_below_oew",
            params=all_params,
            modifications=[Modification("aircraft_properties.takeoff_mass", 10000.0)],
            description="TC_MASS_BELOW_OEW: mass below OEW: expects abort",
            expect_error=True,
        )
    )
    # TC_MASS_NOT_DECREASING: aircraft_mass not strictly decreasing => abort
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_not_decreasing",
            params=all_params,
            modifications=[Modification("trajectory.am", _make_non_decreasing_mass)],
            description="TC_MASS_NOT_DECREASING: mass not strictly decreasing: expects abort",
            expect_error=True,
        )
    )
    # TC_MASS_EXCEEDS_MTOW: some waypoint masses above MTOW => abort
    cases.append(
        TestCaseSpec(
            suffix="tc_mass_exceeds_mtow",
            params=all_params,
            modifications=[Modification("trajectory.am", _make_exceeds_mtow_mass)],
            description="TC_MASS_EXCEEDS_MTOW: some masses > MTOW: expects abort",
            expect_error=True,
        )
    )
    # TC_TOM_EXCEEDS_MTOW: takeoff mass above MTOW => abort
    cases.append(
        TestCaseSpec(
            suffix="tc_tom_exceeds_mtow",
            params=all_params,
            modifications=[Modification("aircraft_properties.takeoff_mass", 999999.0)],
            description="TC_TOM_EXCEEDS_MTOW: TOM > MTOW: expects abort",
            expect_error=True,
        )
    )

    # Load factor clamping (TC_LF_GT_ONE)
    # TC_LF_GT_ONE: load factor > 1 => clamped to 1.0
    cases.append(
        TestCaseSpec(
            suffix="tc_lf_gt_one",
            params=all_params,
            modifications=[Modification("aircraft_properties.load_factor", 1.5)],
            description="TC_LF_GT_ONE: LF > 1: clamped to 1.0",
        )
    )

    return cases


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


@dataclass
class GoldenContext:
    """Shared context for golden test case generation.

    Produced by :func:setup_baseline and consumed by both
    :func:generate_per_file_golden (Mode 1) and
    :func:generate_aggregated_golden (Mode 2).

    Attributes
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.
    base_name : str
        Base name derived from the input file (e.g. "fleet_5_flights").
    zarr_paths : ZarrPaths
        Weather data paths for the pipeline.
    original_input : list[dict]
        Original NM JSON flights (possibly filtered to exclude default failures).
    baseline : dict[str, Any]
        Baseline values extracted from default-case outputs, keyed by
        {internal_name: {flight_id: value}}.
    default_outputs : list[FlightView]
        Output flights from the default (unmodified) pipeline run.
    """

    args: argparse.Namespace
    base_name: str
    zarr_paths: ZarrPaths
    original_input: list[dict[str, Any]]
    baseline: dict[str, Any]
    default_outputs: list[FlightView]


def setup_baseline(args: argparse.Namespace) -> GoldenContext:
    """Run the default case and extract baseline values for perturbation.

    This is the shared preamble for both generation modes. It:

    1. Creates the output directory and Zarr paths.
    2. Loads the original input JSON.
    3. Runs the default (unmodified) pipeline unless --skip-default.
    4. Extracts baseline values from the default output.

    Args:
        args: Parsed CLI arguments.

    Returns:
        A :class:GoldenContext containing all shared state.

    Raises:
        SystemExit: If required paths do not exist.
    """
    # Validate inputs
    if not args.input.exists():
        _log.error("Input file not found: %s", args.input)
        sys.exit(1)

    if not args.weather_path.is_dir():
        _log.error("Weather path not found: %s", args.weather_path)
        sys.exit(1)

    if not args.bada_path.is_dir():
        _log.error("BADA path not found: %s", args.bada_path)
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Derive base name from input file
    base_name = args.input.stem.replace("_input", "")
    _log.info("Base name: %s", base_name)

    # Create Zarr paths
    zarr_paths = create_zarr_paths(args.weather_path)

    # Load original input
    original_input = load_input(args.input)
    _log.info("Loaded %d flights from input", len(original_input))

    # === Generate default case and extract baseline ===
    _log.info("=" * 60)
    _log.info("Setup: Generating default case")
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

    return GoldenContext(
        args=args,
        base_name=base_name,
        zarr_paths=zarr_paths,
        original_input=original_input,
        baseline=baseline,
        default_outputs=default_outputs,
    )


# Mode 1 Per-file legacy generation
def generate_per_file_golden(ctx: GoldenContext) -> None:
    """Mode 1: Generate per-test-case input/output file pairs.

    Preserves the exact same generation logic used for backward
    compatibility with test_pipeline.py and test_fleet_pipeline.py.

    For each :class:TestCaseSpec from :func:build_test_cases:

    1. Apply numeric perturbations via :func:apply_parameters.
    2. Apply structural modifications via :func:_modify_flight (if any).
    3. Run the fleet pipeline.
    4. Filter input to match successful outputs.
    5. Save {base}_{suffix}_input.json and {base}_{suffix}_output.json.

    Legacy mixed-pattern cases (mixed_columns, mixed_attrs) are handled
    separately with their custom per-flight logic.

    Args:
        ctx: Shared golden context from :func:setup_baseline.
    """
    _log.info("=" * 60)
    _log.info("Mode 1: Generating per-file test cases")
    _log.info("=" * 60)

    test_cases = build_test_cases_legacy()

    # Legacy mixed-pattern cases that need custom per-flight logic
    # (these cannot be expressed as a simple params dict)
    legacy_cases: list[tuple[str, Any, str]] = [
        ("mixed_columns", apply_mixed_columns, "mixed_columns"),
        ("mixed_attrs", apply_mixed_attrs, "mixed_attrs"),
    ]

    for spec in test_cases:
        _log.info("-" * 40)
        _log.info(
            "Generating case: %s (%d params, %d mods%s) %s",
            spec.suffix,
            len(spec.params),
            len(spec.modifications) if spec.modifications else 0,
            ", expect_error" if spec.expect_error else "",
            spec.description,
        )

        # Build from scratch: apply only the requested parameters
        modified_input = apply_parameters(ctx.original_input, ctx.baseline, spec.params)

        if spec.modifications:
            modified_input = _modify_flight(modified_input, ctx.baseline, spec.modifications)

        # Optional schema validation (e.g. for the ref case)
        if spec.validate_schema:
            _validate_against_schema(
                modified_input,
                str(Path(__file__).parent / "schemas/flight_schema.json"),
            )

        # Save modified input
        case_input_path = ctx.args.output_dir / f"{ctx.base_name}_{spec.suffix}_input.json"
        save_input(modified_input, case_input_path)

        _log.info("Running pipeline...")
        try:
            result = run_pipeline(case_input_path, ctx.zarr_paths, ctx.args.bada_path)

            if spec.expect_error:
                _log.info(
                    "Case '%s' (expect_error): %d succeeded, %d failed",
                    spec.suffix,
                    result.num_succeeded,
                    result.num_failed,
                )
                continue

            # Re-save filtered input (overwrite)
            filtered_input = filter_input_to_match_outputs(modified_input, result)
            save_input(filtered_input, case_input_path)

            # Save output
            case_output_path = ctx.args.output_dir / f"{ctx.base_name}_{spec.suffix}_output.json"
            save_output(result.outputs, case_output_path)

            _log.info(
                "Case '%s': %d succeeded, %d failed",
                spec.suffix,
                result.num_succeeded,
                result.num_failed,
            )
        except Exception as e:
            if spec.expect_error:
                _log.info(
                    "Case '%s' (expect_error): pipeline raised %s: %s",
                    spec.suffix,
                    type(e).__name__,
                    e,
                )
            else:
                _log.error("Failed to generate case %s: %s", spec.suffix, e)
                if case_input_path.exists():
                    case_input_path.unlink()
            continue

    # Legacy mixed-pattern cases (custom per-flight logic)
    for suffix, modifier_fn, perturb_key in legacy_cases:
        _log.info("-" * 40)
        _log.info("Generating legacy case: %s (factor=%.3f)", suffix, PERTURBATIONS[perturb_key])

        modified_input = modifier_fn(ctx.original_input, ctx.baseline, PERTURBATIONS[perturb_key])

        case_input_path = ctx.args.output_dir / f"{ctx.base_name}_{suffix}_input.json"
        save_input(modified_input, case_input_path)

        _log.info("Running pipeline...")
        try:
            result = run_pipeline(case_input_path, ctx.zarr_paths, ctx.args.bada_path)
            filtered_input = filter_input_to_match_outputs(modified_input, result)
            save_input(filtered_input, case_input_path)

            case_output_path = ctx.args.output_dir / f"{ctx.base_name}_{suffix}_output.json"
            save_output(result.outputs, case_output_path)

            _log.info(
                "Case '%s': %d succeeded, %d failed",
                suffix,
                result.num_succeeded,
                result.num_failed,
            )
        except Exception as e:
            _log.error("Failed to generate case %s: %s", suffix, e)
            if case_input_path.exists():
                case_input_path.unlink()
            continue

    _log.info("Mode 1 complete.")

# Mode 2 Aggregated single-file generation

def _extract_single_flight(
    original_input: list[dict[str, Any]],
    flight_id: str,
) -> dict[str, Any] | None:
    """Extract a single flight from the original input by flight_identification.

    Args:
        original_input: List of NM JSON flight dicts.
        flight_id: The flight_identification value to match.

    Returns:
        Deep copy of the matching flight dict, or None if not found.
    """
    for flight in original_input:
        if flight["flight_information"]["flight_identification"] == flight_id:
            return copy.deepcopy(flight)
    return None


def generate_aggregated_golden(ctx: GoldenContext) -> None:
    """Mode 2: Generate a single aggregated input/output JSON pair.

    For each non-ref, non-mixed test case from :func:build_test_cases:

    1. Look up the hardcoded flight from :data:AGGREGATED_FLIGHT_SELECTIONS.
    2. Extract that single flight from the original input.
    3. Apply :func:apply_parameters with the TC's params.
    4. Apply :func:_modify_flight if the TC has structural modifications.
    5. Rename flight_identification to {original_id}__{tc_suffix} for uniqueness.
    6. Aggregate all modified flights into one list.

    The aggregated input is saved as {base}_aggregated_input.json, then
    the fleet pipeline is run once. The output (only successful flights) is
    saved as {base}_aggregated_output.json.

    Error-expectation TCs are included their flights will appear in the
    fleet runner's error_records while successful flights appear in the
    output. This tests the fleet runner's ability to handle mixed
    success/failure in a single batch.

    Args:
        ctx: Shared golden context from :func:setup_baseline.
    """
    _log.info("=" * 60)
    _log.info("Mode 2: Generating aggregated single-file golden data")
    _log.info("=" * 60)

    test_cases = build_test_cases()
    aggregated_flights: list[dict[str, Any]] = []
    included_suffixes: list[str] = []
    skipped_suffixes: list[str] = []

    for spec in test_cases:
        # Look up the hardcoded flight selection
        selected_flight_id = AGGREGATED_FLIGHT_SELECTIONS.get(spec.suffix)
        if selected_flight_id is None:
            _log.warning(
                "No flight selection for TC '%s' in AGGREGATED_FLIGHT_SELECTIONS skipping",
                spec.suffix,
            )
            skipped_suffixes.append(spec.suffix)
            continue

        # Extract the single flight from original input
        single_flight = _extract_single_flight(ctx.original_input, selected_flight_id)
        if single_flight is None:
            _log.warning(
                "Flight '%s' not found in original input for TC '%s' skipping",
                selected_flight_id,
                spec.suffix,
            )
            skipped_suffixes.append(spec.suffix)
            continue

        # Apply numeric perturbations (wrapping in a list for apply_parameters)
        modified = apply_parameters([single_flight], ctx.baseline, spec.params)

        # Apply structural modifications if any
        if spec.modifications:
            modified = _modify_flight(modified, ctx.baseline, spec.modifications)

        # Rename flight_identification to avoid collisions:
        # {original_id}__{tc_suffix}
        modified_flight = modified[0]
        new_id = f"{selected_flight_id}__{spec.suffix}"
        modified_flight["flight_information"]["flight_identification"] = new_id

        aggregated_flights.append(modified_flight)
        included_suffixes.append(spec.suffix)

        _log.debug(
            "Aggregated TC '%s': flight '%s' -> '%s'%s",
            spec.suffix,
            selected_flight_id,
            new_id,
            " (expect_error)" if spec.expect_error else "",
        )

    _log.info(
        "Aggregated %d flights from %d TCs (skipped: %s)",
        len(aggregated_flights),
        len(included_suffixes),
        ", ".join(skipped_suffixes) if skipped_suffixes else "none",
    )

    if not aggregated_flights:
        _log.warning("No flights to aggregate skipping Mode 2")
        return

    # Save aggregated input
    agg_input_path = ctx.args.output_dir / f"{ctx.base_name}_aggregated_input.json"
    save_input(aggregated_flights, agg_input_path)

    # Run fleet pipeline once on the aggregated input
    _log.info("Running fleet pipeline on aggregated input (%d flights)...", len(aggregated_flights))
    try:
        result = run_pipeline(agg_input_path, ctx.zarr_paths, ctx.args.bada_path)

        # Keep ALL flights in input (including error-expectation ones) so that
        # test_cases_pipeline.py can verify both success and error outcomes from
        # a single fleet run. Save aggregated output
        agg_output_path = ctx.args.output_dir / f"{ctx.base_name}_aggregated_output.json"
        save_output(result.outputs, agg_output_path)

        _log.info(
            "Aggregated result: %d succeeded, %d failed",
            result.num_succeeded,
            result.num_failed,
        )

        if result.num_failed > 0:
            _log.info(
                "Failed flight IDs: %s",
                ", ".join(sorted(result.get_failed_flight_ids())),
            )
    except Exception as e:
        _log.error("Failed to generate aggregated golden data: %s", e)
        if agg_input_path.exists():
            agg_input_path.unlink()

    _log.info("Mode 2 complete.")


def main() -> int:
    """Main entry point runs both generation modes sequentially.

    1. :func:setup_baseline default case + baseline extraction.
    2. :func:generate_per_file_golden Mode 1: per-test-case file pairs.
    3. :func:generate_aggregated_golden Mode 2: single aggregated file pair.
    """
    args = parse_args()

    # Shared setup: default case + baseline extraction
    ctx = setup_baseline(args)

    # Mode 1: per-file legacy generation (backward compatible)
    generate_per_file_golden(ctx)

    # Mode 2: aggregated single-file generation
    generate_aggregated_golden(ctx)

    _log.info("=" * 60)
    _log.info("Done! Generated golden test cases in: %s", args.output_dir)
    _log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
