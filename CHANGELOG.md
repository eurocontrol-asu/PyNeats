# Changelog

All notable changes to PyNeats will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.9] - 2026-03-25

### Bug Fixes

- **accf**: Replace 0 with NaN in validity mask
- **physics**: Update CO2 AGWP coefficients from AirClim (Dahlmann et al., 2025)

### Changed

- **speed-filter**: Operate on DataFrame instead of FlightWithWeather

### Features

- **bada-adapters**: Expose v_stall_cas on BaseBADAAdapter
- **performance**: Add low-speed point filter using VStall threshold
- **bada-model**: Integrate speed filter in performance pipeline
- **parsing**: Reject flights with min pressure level > 500 hPa

## [0.7.8] - 2026-03-20

### Bug Fixes

- **ci**: Use git-cliff content output instead of changelog path
- **open_airclim**: Use self.params instead of self.default_params [AXM-628]

### Changed

- **report**: Replace climaccf_version with openairclim_version

### Documentation

- **changelog**: Regenerate with git-cliff for v0.7.8

### Testing

- **open_airclim**: Add regression tests for self.params fix

### Deps

- Add openairclim as formal dependency, pin pybada

## [0.7.7] - 2026-03-19

### Bug Fixes

- **runners**: Re-enable intermediate flight cleanup between pipeline steps

### CI/CD

- **release**: Disable PyPI publishing until trusted publisher is configured

### Documentation

- **examples**: Add --airport-fuel-path CLI arg to fleet examples

## [0.7.6] - 2026-03-18

### Bug Fixes

- **performance**: Retry both BADA versions in altitude fallback
- **tests**: Fix guardrail test fixtures and error message format
- **lint**: Replace ambiguous Unicode chars and fix RUF009 dataclass default

### Changed

- **performance**: Convert altitude filter to fallback mechanism
- **climate**: Express EAGWP in W·m⁻²·yr instead of J/m²

### Documentation

- **examples**: Add small emitter and performance-only runner examples

### Features

- **parsing**: Add min altitude FL filter to trajectory parser
- **parsing**: Reject trajectories spanning >24h [AXM-431]
- **performance**: Reject unrealistic fuel consumption [AXM-431]
- **climate**: Reject implausible non-CO2 impact [AXM-431]

## [0.7.5] - 2026-03-11

### Bug Fixes

- Fleet utils now sets and recovers flight id correctly when converting flights to fleet and back. Create golden outputs merge for DLR tests
- Apply audit fixes C2, C3, H3 and mark xfail DLR tests

### Features

- Add airport-specific q_fuel fallback (middle tier)
- Normalize ACFT_SERIES matching and add multi-engine test suite
- Extend airport fuel-property fallback to all fuel attributes
- Add FleetRunnerPerformanceOnly — stop pipeline after performance step

### Miscellaneous

- Untrack _version.py and add to .gitignore

### Testing

- Remove test_eng_unknown_resolves_different

### Build

- Trigger hatch-vcs on editable install to generate _version.py

## [0.7.4] - 2026-02-23

### Bug Fixes

- Method D Co2 equivalent computation and add background emission inventory for method D

## [0.7.3] - 2026-02-13

### Bug Fixes

- **ci**: Add fallback for changelog generation failures
- Mass can be missing in performance step, and will be estimated for subsequent cocip computations. interpolation in creation of golden outputs for tests with perturbations. allow some out of bond points in performance before triggering exception by propagation of state
- Minor lint format

## [0.7.2] - 2026-02-06

### Bug Fixes

- **ci**: Add GITHUB_TOKEN for changelog and exclude examples from lint
- **ci**: Allow empty test collection (exit code 5)

## [0.7.1] - 2026-02-04

### Bug Fixes

- **ci**: Use correct BADA_PATH environment variable
- **ci**: Skip requires_weather tests in CI

### Documentation

- Update CHANGELOG.md for v0.7.0
- **readme**: Improve installation and testing instructions
- **contributing**: Modernize with uv and make commands

### Miscellaneous

- Modernize project configuration (aetherx patterns)
- **makefile**: Add BADA_PATH and WEATHER_PATH arguments for tests
- Disable dependabot temporarily
- Clean up .gitignore
- Untrack CLAUDE.md and clustering module
- **makefile**: Make audit non-failing (informational only)

## [0.6.5] - 2026-01-20

### Bug Fixes

- Correct unit tests for NEATSFuel API and Fleet requirements
- Use datetime objects for time column in tests
- Correct unit tests to work with PyContrails Fleet API
- Correct all integration test errors
- Now the golden output includes 5 flights. good
- Resolve integration test errors
- Prevent mutation of golden flight data in integration tests
- Correct integration test issues - API, tolerances, and structure
- Resolve weather dtype and contrails tolerance issues
- Replicate main branch test structure EXACTLY
- Improving tests
- Update test_pipeline.py to use automatic parametrization
- Remove flight id, but still errors
- Extract first element from flight_id list in parametrization
- Add fixtures removed by ruff
- Resolve safe mypy errors and add strategic type ignores
- Update auto-generated _version.py to modern type syntax
- **fleet_utils**: Harmonize columns before Fleet.from_seq to handle heterogeneous flights
- **tests**: Fix climate_payload comparison in golden tests
- **scripts**: Fix JSON path for payload_factor and takeoff_mass
- **neats_fuel**: Handle array values in from_attrs when loading from JSON
- **scripts**: Adjust perturbation factors to avoid BADA failures
- **scripts**: Filter input to match successful outputs

### CI/CD

- Modernize GitHub Actions workflows and update README
- Make mypy non-blocking and fix workflow syntax

### Changed

- Simplify integration tests - replicate main branch approach
- **cocip**: Add run_fleet() method for vectorized processing
- **weather**: Add run_fleet() method for vectorized processing
- **fleet**: Delegate vectorized steps to step classes
- Extract Fleet conversion utilities to fleet_utils.py
- **fleet**: Create vectorized steps in _load_weather()
- Modernize type annotations to Python 3.11+ syntax
- Fix all ruff linting errors
- **fleet**: Improve type safety with discriminated unions and VectorizedStep protocol
- **tests**: Restructure tests with parametrized golden reference testing
- **tests**: Rename CLI options to --weather-path and --bada-path

### Documentation

- Simplify CLAUDE.md with schema-only validation approach

### Features

- Phase 1 - foundation and modern python tooling
- Easier documentation
- Install OpenAirClim
- Complete Phase 1 modernization tooling
- **scripts**: Add create_golden_outputs.py for generating test cases
- **scripts**: Improve error logging for failed flights
- **scripts**: Add mixed_columns test case for FleetRunner
- **scripts**: Add mixed_attrs test case for FleetRunner

### Miscellaneous

- Update dependencies and fix CI for current version
- Clean up outdated GitHub workflows
- Remove obsolete tests
- Clean up debug prints and unused code
- Remove unused schemas.py and validators.py

### Styling

- Improve code organization and safety
- Improve code organization and safety
- Apply ruff auto-formatting
- Apply pre-commit auto-fixes

### Testing

- Implement golden reference testing infrastructure
- Add simplified integration tests for basic step validation
- Add individual step tests following main branch structure
- Improve test infrastructure with markers, session fixtures, and better error messages
- Add FleetRunner integration test for full pipeline
- Add climate_payload verification to golden reference tests

## [0.2.0] - 2025-11-28

