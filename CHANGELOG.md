# Changelog

All notable changes to PyNeats will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Features

- **open_airclim**: [**breaking**] Upgrade OpenAirClim from 0.13.0 to 0.20.0 (repository data 0.2.0, DOI 10.5281/zenodo.22962383) with the Method D setup decided by Ramon and Philippe on 2026-10-28: perturbation approach for O3 and CH4 (A.1), NOx given as NO2 (`nox = "NO2"`, A.2), the new contrail science accepted and documented (A.3), the bundled ELK 2025 base inventory kept (`rel_to_base`) and no SWV (A.4), and the default `"proportional"` CH4/CO2 attribution (A.5). AGWP values are now the flight's own share (aircraft `DEFAULT`), integrated from its RF over [t_0, t_0 + H). **Method D results change.** On 100 NM flights, as ratios of the fleet sums (0.20.0 / 0.13.0): CH4 + PMO ×0.67 (H = 20) and ×0.55 (H = 100), O3 ×1.16, contrails ×0.56, H2O ×1.00, CO2 unchanged

- **deps**: [**breaking**] Upgrade pycontrails from 0.60.2 to 0.65.0; Python 3.12 or later is now required (pycontrails 0.65 needs it). Changes that reach PyNEATS: (1) for engines without nvPM data in the ICAO EDB, nvPM now comes from the smoke numbers (SCOPE11 with T4/T2), or from constant emission indices when the smoke numbers are incomplete, instead of the "FA Model"; (2) a superseded engine UID is computed with its latest successor, given in the new flight attribute `engine_uid_used` (a list for a multi-engine flight); (3) ICAO EDB v31 → v32; (4) the nvPM fuel correction follows ICAO Annex 16 (changes nvPM only for fuels with a hydrogen content away from 13.8 %). CoCiP is unchanged. **Method C results change**, on the NM sample 2025-07-09 (4,683 flights, same flights computed and failed as with 0.60.2): fuel, CO2 and H2O identical, contrails +46.8 % (96 % of it from (1)), O3 −0.43 %, CH4 +0.48 % (NOx of superseded engines), total CO2eq +5.2 % (H = 20), +4.4 % (H = 50), +3.7 % (H = 100). **Method D**: contrails identical, total CO2eq −0.17 % (H = 20) to −0.10 % (H = 100)
- **performance**: `resolve_aircraft` gives `emissions_engine_uid_used`, the engine UID pycontrails computes the emissions with (the latest successor of a superseded UID; None when the UID is not in the EDB)

### Bug Fixes

- **emissions**: With pycontrails 0.65, SCOPE11 gives NaN nvPM at every point, with no warning, for engines that have smoke numbers but no bypass ratio in ICAO EDB v32: PW4098 (`5PW076`) and JT9D (`8PW086`, `8PW087`, `8PW088`; the MRR conservative engine of B741 and B74S, and ECTL mapping rows of B741, B742, B74R, B74S and B773). CoCiP then gave no contrail and the nvPM totals were 0. The emissions step now logs a warning and uses the pycontrails constant nvPM emission indices for such a flight; `nvpm_data_source` is `"Constant (fallback: ICAO EDB (SCOPE11 with T4/T2) gave NaN nvPM)"`
- **climate_metrics**: PMO k_AGWP at H = 100 set to the CH4 value 13.3563 (was 13.356, a rounding in the table; decided by Philippe 2026-11-12). Method C only: PMO EAGWP at H = 100 +0.0022 %, CH4 entry about +0.0006 % in magnitude; H = 20 and 50 unchanged
- **open_airclim**: A configured base inventory file that does not exist now raises `OpenAirClimStepError` naming the path instead of silently running without the base inventory; `base_inventory_path = None` remains the explicit opt-out

### Miscellaneous

- **open_airclim**: `[temperature]` of the bundled `openairclim.toml` set to the values PyNEATS uses: `CO2.lambda = 1.06` (Boucher & Reddy, openairclim 0.20.0 default) and the RSTS Table 3.1 mean efficacies (contrails 0.37, O3 1.05, CH4 1.04, H2O 1.0, PMO 1.0), replacing the Ponater et al. (2006) values (0.73; 0.59, 1.37, 1.14, 1.14, 1.37). A test keeps them equal to `EFFICACY`. No change to PyNEATS results: these settings are only used by openairclim's own dT/ATR/AGTP/AEGWP outputs, and PyNEATS reads AGWP without efficacy (confirmed by DLR, S. Völk, November 2026)

### Documentation

- **performance**: Figure 2 of the MRV specification (ICAO-BADA correspondence) replaced: the MRR conservative engine no longer appears as a key of the BADA mapping: the old figure showed the pre-v0.7.5 chain, where it selected a (type, engine) row; since v0.7.5 it only gives the emissions engine. Text added under the figure
- **open_airclim**: Method D settings table lists `[temperature]`; note that the CH4 RF of a flight first decreases and then returns towards 0 with openairclim 0.20.0, the expected behaviour (DLR)

## [1.0.1] - 2026-05-26

### Bug Fixes

- Adjustment of water factor

## [1.0.0] - 2026-04-24

### Documentation

- Restructure documentation into Diátaxis layout and add API reference
- Unblock htmlproofer on auto-generated API pages
- Update CHANGELOG.md for v1.0.0

## [0.7.10] - 2026-03-30

### Features

- **fleet**: Zero-value climate results for low-altitude flights & dependency updates (v0.7.10) ([#66](https://github.com/eurocontrol-asu/PyNeats/issues/66))

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
