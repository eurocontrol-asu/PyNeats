#!/usr/bin/env python3
"""Generate golden test cases for PyNeats pipeline testing.

This script creates multiple golden test cases from a single input JSON by:
1. Running the default case to get baseline values
2. Creating perturbed variations of the input via :func:`apply_parameters`
3. Running the pipeline on each variation
4. Saving input/output pairs to the golden test directory

All test case specifications are defined declaratively in :func:`build_test_cases`
using :class:`TestCaseSpec`. Each case is built from scratch via
:func:`apply_parameters`, the unified applicator that maps parameter names to
NM JSON locations through :data:`PARAMETER_REGISTRY`.

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
        - {base}_true_airspeed_col: true_airspeed column
        - {base}_hydrogen_content: hydrogen_content in fuel_properties
        - {base}_q_fuel: calorific_value (q_fuel) in fuel_properties
        - {base}_aromatic_content: aromatic_content in fuel_properties
        - {base}_sulphur: sulphur in fuel_properties
        - {base}_naphthalene: naphthalene in fuel_properties

    Ref-minus-one (all params except one — tests default fallback)
        - {base}_no_payload_factor
        - {base}_no_takeoff_mass
        - {base}_no_hydrogen_content
        - {base}_no_q_fuel
        - {base}_no_fuel_flow
        - {base}_no_aircraft_mass
        - {base}_no_engine_efficiency
        - {base}_no_true_airspeed

    Ref-minus-multiple (all params except a category)
        - {base}_no_fuel_props: no fuel properties at all
        - {base}_no_columns: no trajectory columns at all

    Legacy mixed-pattern cases (custom per-flight heterogeneity)
        - {base}_mixed_columns: different flights have different columns
        - {base}_mixed_attrs: different flights have different attributes
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
class ParamSpec:
    """Specification for a single perturbable parameter.
    Parameter registry: single source of truth for all perturbable parameters

    Attributes
    ----------
    internal_name : str
        Key in baseline dict / FlightView attrs or columns.
    category : str
        ``"attr"`` for scalar flight attributes, ``"column"`` for trajectory arrays.
    json_section : str
        NM JSON section: ``"aircraft_properties"``, ``"fuel_properties"``, or ``"trajectory"``.
    json_field : str
        Field name in the NM JSON structure.
    default_value : Any
        Default constant from neats_default_parameters, or ``None``.
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
        "payload_factor", "attr", "aircraft_properties",
        "load_factor", DEFAULT_PAYLOAD_FACTOR, True,
    ),
    "takeoff_mass": ParamSpec(
        "takeoff_mass", "attr", "aircraft_properties",
        "takeoff_mass", None, True,
    ),
    "engine_uid": ParamSpec(
        "engine_uid", "attr", "aircraft_properties",
        "engine_uid", None, False,
    ),
    # fuel attrs
    "hydrogen_content": ParamSpec(
        "hydrogen_content", "attr", "fuel_properties",
        "hydrogen_content", DEFAULT_HYDROGEN_CONTENT, True,
    ),
    "h_c_ratio": ParamSpec(
        "h_c_ratio", "attr", "fuel_properties",
        "hydrogen_per_carbon_ratio", None, True,
    ),
    "aromatic_content": ParamSpec(
        "aromatic_content", "attr", "fuel_properties",
        "aromatic_content", DEFAULT_AROMATICS_CONTENT, True,
    ),
    "q_fuel": ParamSpec(
        "q_fuel", "attr", "fuel_properties",
        "calorific_value", DEFAULT_Q_FUEL, True,
    ),
    "naphthalene": ParamSpec(
        "naphthalene", "attr", "fuel_properties",
        "naphthalene", DEFAULT_NAPHTHALEN_CONTENT, True,
    ),
    "sulphur_content": ParamSpec(
        "sulphur_content", "attr", "fuel_properties",
        "sulphur", DEFAULT_SULPHUR_CONTENT, True,
    ),
    # trajectory columns
    "fuel_flow": ParamSpec(
        "fuel_flow", "column", "trajectory",
        "ff", None, True,
    ),
    "engine_efficiency": ParamSpec(
        "engine_efficiency", "column", "trajectory",
        "ee", None, True,
    ),
    "aircraft_mass": ParamSpec(
        "aircraft_mass", "column", "trajectory",
        "am", None, True,
    ),
    "true_airspeed": ParamSpec(
        "true_airspeed", "column", "trajectory",
        "tas", None, True,
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

    Extracts all parameters defined in :data:`PARAMETER_REGISTRY` so that
    every schema-defined optional property is available for perturbation.

    Returns a dict with baseline values keyed by ``{internal_name: {flight_id: value}}``.
    """
    baseline: dict[str, Any] = {
        spec.internal_name: {} for spec in PARAMETER_REGISTRY.values()
    }

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
                baseline[spec.internal_name][flight_id] = np.array(
                    flight[spec.internal_name]
                )

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
    defined in :data:`PARAMETER_REGISTRY`. Each parameter is looked up in the
    registry to determine its JSON location and whether it is a scalar attribute
    or a per-waypoint column.

    Args:
        input_data: Original NM JSON input flights.
        baseline: Baseline values from :func:`extract_baseline_values`.
        params: Dict mapping parameter name → perturbation factor.
            For numeric params the applied value is ``baseline * factor``.
            For non-numeric params (e.g. ``engine_uid``) the factor is ignored
            and the baseline value is injected as-is.

    Returns:
        Deep-copied input with the requested parameters applied.

    Raises:
        KeyError: If a param name is not in :data:`PARAMETER_REGISTRY`.
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
            ``{"flight_information": {...}}``).
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
            fid = flight.get("flight_information", {}).get(
                "flight_identification", f"index-{idx}"
            )
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
    validated against ``schemas/flight_schema.json`` to ensure completeness.

    Args:
        input_data: Original NM JSON input flights.
        baseline: Baseline values from :func:`extract_baseline_values`.
        factor: Ignored — always uses 1.0 for the reference case.
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
        *exclude: Parameter names (keys in :data:`PARAMETER_REGISTRY`) to omit.

    Returns:
        Dict of ``{param_name: 1.0}`` for every registered parameter not in *exclude*.

    Raises:
        KeyError: If any name in *exclude* is not in :data:`PARAMETER_REGISTRY`.
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
        File name suffix, e.g. ``"ref"`` → ``{base}_ref_input.json``.
    params : dict[str, float]
        Parameter names → perturbation factors passed to :func:`apply_parameters`.
        An empty dict means "no optional parameters" (bare input).
    description : str
        Note for logging.
    validate_schema : bool
        If ``True``, validate the generated input against the flight schema.
    """

    suffix: str
    params: dict[str, float]
    description: str = ""
    validate_schema: bool = False


def build_test_cases() -> list[TestCaseSpec]:
    """Build the full list of golden test case specifications.

    All cases are built from scratch via :func:`apply_parameters`.
    The reference case includes every parameter at factor 1.0. Single-parameter
    perturbation cases include only that one parameter at its perturbation factor.
    "Ref-minus-one" cases include everything except one parameter to test
    fallback/default behaviour.

    Returns:
        Ordered list of :class:`TestCaseSpec` to generate.
    """
    cases: list[TestCaseSpec] = []

    # 1. Reference case: all params at baseline
    cases.append(TestCaseSpec(
        suffix="ref",
        params={name: 1.0 for name in PARAMETER_REGISTRY},
        description="Reference case: all optional params at baseline",
        validate_schema=True,
    ))

    # 2. Single-parameter perturbation cases
    # Each includes ONLY the one parameter being tested, at its perturbation factor.
    single_param_cases: list[tuple[str, str, float]] = [
        # (suffix, registry_param_name, factor)
        ("payload_factor", "payload_factor", PERTURBATIONS["payload_factor"]),
        ("takeoff_mass", "takeoff_mass", PERTURBATIONS["takeoff_mass"]),
        ("aircraft_mass_col", "aircraft_mass", PERTURBATIONS["aircraft_mass_col"]),
        ("fuel_flow_col", "fuel_flow", PERTURBATIONS["fuel_flow_col"]),
        ("engine_efficiency_col", "engine_efficiency", PERTURBATIONS["engine_efficiency_col"]),
        ("true_airspeed_col", "true_airspeed", PERTURBATIONS["true_airspeed_col"]),
        ("hydrogen_content", "hydrogen_content", PERTURBATIONS["hydrogen_content"]),
        ("q_fuel", "q_fuel", PERTURBATIONS["q_fuel"]),
        ("aromatic_content", "aromatic_content", PERTURBATIONS["aromatic_content"]),
        ("sulphur", "sulphur_content", PERTURBATIONS["sulphur"]),
        ("naphthalene", "naphthalene", PERTURBATIONS["naphthalene"]),
    ]
    for suffix, param_name, factor in single_param_cases:
        cases.append(TestCaseSpec(
            suffix=suffix,
            params={param_name: factor},
            description=f"Single perturbation: {param_name} at {factor:.3f}",
        ))
    
    # 3. Ref-minus-one cases: all params except one, testing fallback/default behaviour
    ref_minus_one_params = [
        "payload_factor",
        "takeoff_mass",
        "hydrogen_content",
        "q_fuel",
        "fuel_flow",
        "aircraft_mass",
        "engine_efficiency",
        "true_airspeed",
    ]
    for excluded in ref_minus_one_params:
        cases.append(TestCaseSpec(
            suffix=f"no_{excluded}",
            params=_ref_params_except(excluded),
            description=f"Ref minus {excluded} — tests default fallback",
        ))

    # 4. Ref-minus-multiple: test multiple missing params at once
    cases.append(TestCaseSpec(
        suffix="no_fuel_props",
        params=_ref_params_except(
            "hydrogen_content", "q_fuel", "aromatic_content",
            "naphthalene", "sulphur_content", "h_c_ratio",
        ),
        description="Ref minus all fuel properties — tests full fuel defaults",
    ))
    cases.append(TestCaseSpec(
        suffix="no_columns",
        params=_ref_params_except(
            "fuel_flow", "aircraft_mass", "engine_efficiency", "true_airspeed",
        ),
        description="Ref minus all trajectory columns — tests column-free path",
    ))

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

    # Generate test cases via unified apply_parameters
    _log.info("=" * 60)
    _log.info("Generating test cases")
    _log.info("=" * 60)

    test_cases = build_test_cases()

    # Append the legacy mixed-pattern cases that need custom per-flight logic
    # (these cannot be expressed as a simple params dict)
    legacy_cases: list[tuple[str, Any, str]] = [
        ("mixed_columns", apply_mixed_columns, "mixed_columns"),
        ("mixed_attrs", apply_mixed_attrs, "mixed_attrs"),
    ]

    for spec in test_cases:
        _log.info("-" * 40)
        _log.info(
            "Generating case: %s (%d params) — %s",
            spec.suffix,
            len(spec.params),
            spec.description,
        )

        # Build from scratch: apply only the requested parameters
        modified_input = apply_parameters(original_input, baseline, spec.params)

        # Optional schema validation (e.g. for the ref case)
        if spec.validate_schema:
            _validate_against_schema(modified_input, str(Path(__file__).parent / "schemas/flight_schema.json"))
        # Save modified input
        case_input_path = args.output_dir / f"{base_name}_{spec.suffix}_input.json"
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
            case_output_path = args.output_dir / f"{base_name}_{spec.suffix}_output.json"
            save_output(result.outputs, case_output_path)

            # Summary for this case
            _log.info(
                "Case '%s': %d succeeded, %d failed",
                spec.suffix,
                result.num_succeeded,
                result.num_failed,
            )
        except Exception as e:
            _log.error("Failed to generate case %s: %s", spec.suffix, e)
            # Remove the input file if pipeline failed completely
            if case_input_path.exists():
                case_input_path.unlink()
            continue

    # Legacy mixed-pattern cases (custom per-flight logic)
    for suffix, modifier_fn, perturb_key in legacy_cases:
        _log.info("-" * 40)
        _log.info("Generating legacy case: %s (factor=%.3f)", suffix, PERTURBATIONS[perturb_key])

        modified_input = modifier_fn(original_input, baseline, PERTURBATIONS[perturb_key])

        case_input_path = args.output_dir / f"{base_name}_{suffix}_input.json"
        save_input(modified_input, case_input_path)

        _log.info("Running pipeline...")
        try:
            result = run_pipeline(case_input_path, zarr_paths, args.bada_path)
            filtered_input = filter_input_to_match_outputs(modified_input, result)
            save_input(filtered_input, case_input_path)

            case_output_path = args.output_dir / f"{base_name}_{suffix}_output.json"
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

    _log.info("=" * 60)
    _log.info("Done! Generated golden test cases in: %s", args.output_dir)
    _log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
