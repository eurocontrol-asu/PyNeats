# CLAUDE.md - PyNeats Fleet-Only Refactoring

**Project**: PyNeats - Aviation Climate Impact Assessment Library
**Refactoring**: Dual Architecture (Flight + Fleet) → Fleet-Only Architecture
**Start Date**: 2026-01-13
**Status**: Phase 0 - Planning ✓

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Goals & Success Criteria](#goals--success-criteria)
3. [Working Agreement](#working-agreement)
4. [Quality Standards](#quality-standards)
5. [Phase Breakdown](#phase-breakdown)
6. [Current Status](#current-status)
7. [References](#references)

---

## Project Overview

### **Problem Statement**
PyNeats currently has two major issues:

**1. Architecture Duplication**
- `FlightRunner`: Single-flight processing
- `FleetRunner`: Multi-flight processing with vectorization
- **Code duplication**: ~1400 lines of redundant code
- **Maintenance burden**: Changes must be applied twice
- **Divergence risk**: Implementations can drift, producing different results
- **Testing overhead**: Every step needs dual test coverage

**2. Legacy Python Setup**
- Using setuptools-scm instead of modern hatch-vcs (manual version management)
- No standardized developer workflows (Makefile)
- No pre-commit hooks for code quality
- No automated changelog generation
- No modern CI/CD with uv package manager
- No documentation site (MkDocs)
- Missing automated dependency updates (Dependabot)

### **Solution**
**Fleet-Only Architecture:**
- Single flight = Fleet of 1 flight
- All steps operate on `Fleet → Fleet`
- Conversion logic centralized in `fleet_utils.py`
- 36% code reduction while maintaining 100% behavioral compatibility

**Modern Python Practices (2026 Standards):**
- Migrate to `uv` for dependency management
- Migrate to `hatch-vcs` for automatic versioning from git tags (no more manual `__version__` updates!)
- Add `Makefile` for standardized commands
- Add pre-commit hooks (ruff formatter + linter, mypy)
- Add `cliff.toml` for automated changelogs
- Modernize CI/CD workflows with security audits
- Add MkDocs documentation site (deferred to later phase)
- Add Dependabot for dependency updates
- Add comprehensive README badges

### **Key Principles**
1. ✅ **No breaking changes** (initially - API stays compatible)
2. ✅ **Verified equivalence** (golden reference testing)
3. ✅ **Incremental migration** (one step at a time)
4. ✅ **Professional quality** (formatting, typing, testing)
5. ✅ **Modern tooling** (uv, hatch-vcs, pre-commit, cliff)
6. ✅ **Production-ready** (CI/CD, docs, badges, automated releases)

---

## Goals & Success Criteria

### **Primary Goals**

**Refactoring Goals:**
- [ ] Eliminate FlightRunner / FleetRunner duplication
- [ ] Achieve 80%+ test coverage (currently ~20%)
- [ ] Reduce codebase by ~1400 lines (~36%)
- [ ] Maintain 100% result compatibility (verified)
- [ ] Improve code maintainability and clarity

**Modernization Goals:**
- [ ] Migrate to `uv` package manager across all workflows
- [ ] Add modern development tooling (Makefile, pre-commit)
- [ ] Implement automated changelog generation (cliff)
- [ ] Add comprehensive CI/CD with security audits
- [ ] Create documentation site with MkDocs
- [ ] Add Dependabot for automated dependency updates
- [ ] Update README with professional badge row

### **Success Criteria**

#### **Functional Requirements**
- ✅ All golden reference tests pass (rtol=1e-6, atol=1e-9)
- ✅ Per-step equivalence tests pass (old vs new)
- ✅ No behavioral regressions detected
- ✅ All integration tests pass

#### **Code Quality Requirements**
- ✅ All formatting checks pass (`ruff format`, `ruff check`)
- ✅ All type checks pass (`mypy --strict`)
- ✅ Test coverage ≥80% (measured by `pytest-cov`)
- ✅ No performance regression (±5% acceptable)

#### **Documentation Requirements**
- ✅ All public APIs documented
- ✅ README updated with new architecture
- ✅ Examples updated
- ✅ Changelog generated (`cliff` / manual)

### **Out of Scope**
- ❌ Performance optimization (unless regression detected)
- ❌ New features or capabilities
- ❌ Public API redesign (can come later)
- ❌ Change to scientific calculations

---

## Working Agreement

### **Workflow**

#### **1. Claude Proposes Changes**
```
Claude: "I'm going to [action]. Here are the changes:

FILE: src/pyneats/core/validators.py
[Shows full file for new files, or diff for modifications]

Proceed?"
```

#### **2. User Reviews & Approves**
```
User:
- "Yes, proceed" → Claude applies changes
- "Change X to Y first" → Claude adjusts
- "No, different approach" → Claude proposes alternative
- "Explain Y" → Claude clarifies
```

#### **3. Claude Applies Changes**
```
Claude uses Write/Edit tools to modify files
```

#### **4. Claude Runs Quality Checks**
```bash
# Formatting
ruff format src/pyneats tests/

# Linting
ruff check src/pyneats tests/ --fix

# Type checking
mypy src/pyneats --strict

# Tests
pytest tests/ -v --tb=short
```

#### **5. Claude Reports Results**
```
Claude: "✓ Changes applied successfully
✓ ruff format: formatted 3 files
✓ ruff check: no issues
✓ mypy --strict: passed
✓ tests: 45/45 passed

Ready to commit?"
```

#### **6. User Approves Commit**
```
User: "Yes, commit"
```

#### **7. Claude Commits**
```bash
git add <files>
git commit -m "Phase 1: Add validators and schemas

- Add validate_columns, validate_attrs, validate_no_all_nan
- Add FlightSchema for declarative validation
- Add tests with 100% coverage
- All quality checks pass"

# After commit, Claude pushes to the working branch
git push -u origin claude/refactor-fleet-only-9triX
```

### **Branch Strategy**
- **Main branch**: `main` (protected, never commit here)
- **Refactoring branch**: `claude/refactor-fleet-only-9triX` (Claude commits and pushes here after user approval)
- **Phase branches**: Not needed - all work on single refactoring branch

### **Commit Message Format**
```
<phase>: <short description>

<detailed description>
- Bullet point changes
- What was added/modified/deleted
- Quality checks status

[optional footer: closes #issue, breaking changes, etc.]
```

**Example:**
```
Phase 1: Add core validators and fleet utilities

Add foundational validation and conversion utilities:
- validators.py: validate_columns, validate_attrs, validate_no_all_nan
- schemas.py: FlightSchema dataclass for declarative validation
- fleet_utils.py: flights_to_fleet, fleet_to_flights conversion
- tests: 15 unit tests with 100% coverage

Quality checks:
✓ ruff format + check: all pass
✓ mypy --strict: no errors
✓ pytest: 15/15 pass
```

### **Testing Requirements**

#### **Before Every Commit:**
```bash
# 1. Run formatting
ruff format src/pyneats tests/

# 2. Run linting
ruff check src/pyneats tests/ --fix

# 3. Run type checking
mypy src/pyneats

# 4. Run relevant tests
pytest tests/unit/test_<module>.py -v

# 5. Run full test suite (if time permits)
pytest tests/ -v
```

#### **After Each Phase:**
```bash
# Golden reference validation
pytest tests/test_regression_refactored.py -v

# Coverage check
pytest --cov=pyneats --cov-report=term --cov-report=html

# Performance benchmark (if applicable)
pytest tests/performance/ -v
```

---

## Quality Standards

### **Code Formatting & Linting**

#### **ruff** (All-in-One Formatter & Linter - 2026 Standard)
```bash
# Format code (replaces black + isort)
ruff format src/pyneats tests/

# Lint code
ruff check src/pyneats tests/ --fix
```
- Line length: 88
- Python 3.11+ target
- Replaces black and isort
- Must pass before commit
- Auto-fix enabled where safe

### **Type Checking**

#### **mypy** (Static Type Checker)
```bash
mypy src/pyneats
```
- Strict mode enabled
- Python 3.11+ target
- All public functions must have type hints
- Return types required
- Must pass with 0 errors before commit

### **Testing**

#### **pytest** (Test Runner)
```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# All tests with coverage
pytest --cov=pyneats --cov-report=html --cov-report=term-missing

# Specific markers
pytest -m "not slow and not requires_bada" -v
```

**Coverage Requirements:**
- Core utilities: 100%
- Step implementations: 80%+
- Runners: 80%+
- Overall: 80%+

### **Changelog**

#### **cliff** (Changelog Generator)
```bash
# Generate changelog (if cliff is available)
git cliff --output CHANGELOG.md

# OR manual changelog updates in CHANGELOG.md
```

**Note**: Will install `cliff` as part of modernization.

---

## Modernization Checklist

### **Modern Python Setup (2026 Standards)**

These modernization tasks will be integrated into Phase 0 and Phase 1.

#### **Build System & Dependencies**
- [ ] Migrate from `setuptools-scm` to `hatch-vcs` for automatic versioning from git tags
  - **Benefit**: No more manual `__version__` updates! Version comes from git tags automatically
  - Tag a release: `git tag v1.2.3` → hatch-vcs handles the rest
- [ ] Update `pyproject.toml` to use `dependency-groups` instead of `optional-dependencies`
- [ ] Add `py.typed` marker (already exists, verify)
- [ ] Ensure `src/` layout is optimal (already using src/)

#### **Developer Tooling**
- [ ] Create `Makefile` with standard commands:
  - `make install` - Install all dependencies with uv
  - `make check` - Run all quality checks
  - `make lint` - Linting + type checking
  - `make format` - Auto-format code
  - `make test` - Run tests with coverage
  - `make audit` - Security audit (pip-audit)
  - `make docs-serve` - Serve docs locally
- [ ] Create `.pre-commit-config.yaml`:
  - Ruff formatter (`ruff format`) and linter (`ruff check`)
  - MyPy type checker
  - Note: Ruff replaces both black and isort (2026 standard)
- [ ] Install pre-commit hooks: `uv run pre-commit install`

#### **CI/CD Workflows**
- [ ] Update `.github/workflows/test_package.yml` → `ci.yml`:
  - Migrate from pip to `uv`
  - Add security audit job (pip-audit)
  - Add coverage reporting to Coveralls
  - Matrix test Python 3.10, 3.11, 3.12, 3.13
  - **Preserve BADA data download step**
- [ ] Create `.github/workflows/publish.yml`:
  - Build and publish to PyPI on tag
  - Use trusted publishing (no API token needed)
- [ ] Create `.github/workflows/docs.yml`:
  - Deploy MkDocs to GitHub Pages
- [ ] Create `.github/workflows/release.yml`:
  - Auto-generate changelog with git-cliff
  - Create GitHub Release on tag

#### **Automated Updates**
- [ ] Create `.github/dependabot.yml`:
  - Weekly dependency updates
  - GitHub Actions updates
  - Group dev dependencies

#### **Changelog Automation**
- [ ] Create `cliff.toml`:
  - Conventional commit parsing
  - Auto-generate CHANGELOG.md on releases
  - Emoji prefixes for commit categories

#### **Documentation**
- [ ] Create `mkdocs.yml`:
  - Material theme
  - API documentation with mkdocstrings
  - Getting started guide
- [ ] Create `docs/` directory:
  - `docs/index.md` - Project overview
  - `docs/getting-started.md` - Installation and usage
  - `docs/api/` - Auto-generated API docs
- [ ] Test locally: `make docs-serve`

#### **README Modernization**
- [ ] Add professional badge row (following canonical standard):
  - CI status
  - Coverage (Coveralls)
  - PyPI version
  - Python 3.10+
  - Strict typing
  - Ruff badge
  - uv badge
  - (Docs badge: deferred to later phase)

#### **Configuration Updates**
- [ ] Update `pyproject.toml`:
  - Add hatch-vcs configuration for automatic versioning
  - Update ruff configuration (line length: **88**, target: py311+)
  - Update mypy to strict mode (target: py311+)
  - Update pytest configuration
  - Add coverage configuration
  - Update Python requirement to 3.11+ (pycontrails dependency requires it)

### **BADA Download Preservation**

**Critical**: Current GitHub Actions workflow downloads BADA data. Must preserve in new CI/CD.

**Current approach** (from `.github/workflows/test_package.yml`):
```yaml
- name: Checkout BADA data
  uses: actions/checkout@v4
  with:
    repository: eurocontrol-asu/bada-data  # ← Corrected repository name
    token: ${{ secrets.BADA_ACCESS_TOKEN }}
    path: bada_data
```

**New BADA structure** (in bada-data repository):
```
bada_data/
  ├── BADA3/
  │   └── *.OPF files
  └── BADA4/
      ├── aircraft_type_1/
      │   └── *.xml
      ├── aircraft_type_2/
      │   └── *.xml
      └── ...
```

**New approach** (in updated `ci.yml`):
- Keep exact same checkout step (with corrected repo name)
- Set environment variables for tests:
  - `BADA3_PATH=${{ github.workspace }}/bada_data/BADA3`
  - `BADA4_PATH=${{ github.workspace }}/bada_data/BADA4`
- Tests use `@pytest.mark.requires_bada` and auto-skip if not available
- Default to BADA4 for tests

### **Golden Reference Data**

**Critical**: User will provide golden reference data for validation testing.

**File location**:
- `tests/data/input_flights_5.json` - Raw NM JSON format (before any processing)
- `tests/data/output_flights_5.json` - FlightView objects with ALL columns (after full pipeline)

**Data structure**:
- **Input**: 5 flights in NM JSON format (raw trajectory, aircraft properties, no weather/performance/emissions)
- **Output**: Same 5 flights as FlightView JSON with ALL columns:
  - 4D trajectory (lat, lon, altitude, time)
  - Weather (temperature, humidity, winds, etc.)
  - Performance (fuel_flow, ROCD, TAS, etc.)
  - Emissions (nvPM, CO2, NOx, etc.)
  - Climate metrics (aCCF, contrails, etc.)

**Testing Strategy**:
Following current PyNeats testing patterns, but enhanced with 2026 best practices:

**Tier 1: Unit Tests** (No flight data)
```python
# tests/unit/test_validators.py
# tests/unit/test_fleet_utils.py
# tests/unit/test_schemas.py

@pytest.mark.parametrize("required,optional", [
    (["lat", "lon"], ["alt"]),
    (["time"], ["fuel_flow"]),
])
def test_validate_columns(required, optional):
    # Pure unit tests with synthetic data
    pass
```

**Tier 2: Step Equivalence Tests** (Use output_flights as golden reference)
```python
# tests/integration/test_step_equivalence.py

@pytest.fixture
def golden_flights():
    """Load output_flights_5.json as FlightView objects"""
    return load_output_flights()

@pytest.mark.parametrize("flight_id", ["flight_0", "flight_1", ...])
def test_emissions_step_equivalence(golden_flights, flight_id):
    """Test PyContrailsEmissionModel: Old vs New (Fleet)"""
    flight = get_flight_by_id(golden_flights, flight_id)

    # Create input (strip emissions columns from golden output)
    input_flight = FlightWithPerformance.from_flight(flight.copy())

    # OLD: Single flight processing
    old_params = PyContrailsEmissionParams()
    old_step = PyContrailsEmissionModel(old_params)
    old_output = old_step(input_flight)

    # NEW: Fleet processing
    new_params = PyContrailsEmissionParams()
    new_step = PyContrailsEmissionModel(new_params)
    fleet_input = flights_to_fleet([input_flight])
    fleet_output = new_step(fleet_input)
    new_output = fleet_to_flights(fleet_output)[0]

    # Compare: Both should match golden output
    check_cols = list(FlightWithEmissions.REQUIRED)
    assert_frame_equal(
        old_output.to_dataframe()[check_cols],
        new_output.to_dataframe()[check_cols],
        rtol=1e-6, atol=1e-9
    )
    assert_frame_equal(
        new_output.to_dataframe()[check_cols],
        flight.to_dataframe()[check_cols],
        rtol=1e-6, atol=1e-9
    )
```

**Tier 3: Full Pipeline Test** (Regression test)
```python
# tests/integration/test_full_pipeline_regression.py

@pytest.fixture
def input_flights():
    """Load raw NM JSON (no weather)"""
    return load_input_flights()

@pytest.fixture
def expected_outputs():
    """Load output_flights_5.json (has all columns)"""
    return load_output_flights()

def test_full_pipeline_regression(input_flights, expected_outputs):
    """End-to-end: Ensure refactored pipeline produces identical results"""

    # Run NEW UnifiedRunner
    runner = UnifiedRunner()
    runner.set_weather(weather_provider)  # Uses actual weather or mock
    results = runner.run(input_flights)

    # Compare with golden outputs
    for result, expected in zip(results, expected_outputs):
        assert_frame_equal(
            result.to_dataframe(),
            expected.to_dataframe(),
            rtol=1e-6, atol=1e-9
        )
```

**Key Testing Principles** (2026 Best Practices):
1. ✅ **Fixtures-based**: Use conftest.py for reusable fixtures
2. ✅ **Parametrized**: Test multiple flights/scenarios efficiently
3. ✅ **Type-safe**: All fixtures and tests fully type-hinted
4. ✅ **Isolated**: Each step tested independently
5. ✅ **Descriptive**: Test names clearly state what's being validated
6. ✅ **Fast**: Unit tests run in milliseconds
7. ✅ **Deterministic**: No flaky tests, all comparisons use explicit tolerances

**Usage**:
- Load golden data via fixtures in `conftest.py`
- Each step test creates proper input type (e.g., `FlightWithPerformance.from_flight()`)
- Instantiate steps with params (e.g., `step = PyContrailsEmissionModel(params)`)
- Call step as callable: `output = step(input)`
- Compare with golden output using `assert_frame_equal(rtol=1e-6, atol=1e-9)`

---

## Phase Breakdown

### **Phase 0: Setup & Contract**
**Duration**: Week 1
**Status**: ⏳ In Progress

- [x] Create CLAUDE.md specification
- [x] Define success criteria
- [x] Establish working agreement
- [x] Define modernization plan (2026 standards)
- [x] Create refactoring branch (`claude/refactor-fleet-only-9triX`)
- [ ] User reviews and approves CLAUDE.md
- [ ] User approves fleet-only refactoring plan
- [ ] User approves modernization plan

**Deliverables**: This document, approved by user

---

### **Phase 1: Foundation - Tests, Utilities & Modern Tooling**
**Duration**: Week 1-2
**Status**: ⏳ Not Started

#### **Objectives**
**Refactoring:**
- Build core validation primitives
- Extract fleet conversion utilities
- Enhance test infrastructure
- Create unit tests for new utilities (user will provide golden reference data separately)

**Modernization:**
- Migrate to modern Python tooling (uv, hatch-vcs)
- Add developer productivity tools (Makefile, pre-commit)
- Modernize CI/CD workflows
- Prepare documentation infrastructure (MkDocs deferred to later phase)

#### **Tasks**

**Workstream A: Refactoring Foundation**
- [ ] **1.1** Enhance `tests/conftest.py`
  - Add fixture: `input_flights()` → loads `tests/data/input_flights_5.json`
  - Add fixture: `golden_flights()` → loads `tests/data/output_flights_5.json` as `List[FlightView]`
  - Keep existing: `weather_path` fixture with environment variable support
  - BADA skip logic (`@pytest.mark.requires_bada`)
  - Support for BADA3 and BADA4 separate paths (BADA3_PATH, BADA4_PATH environment variables)
  - Default to BADA4 for tests
  - Weather skip logic (`@pytest.mark.requires_weather`)
  - All fixtures fully type-hinted
  - Quality: ruff format + check, mypy strict

- [ ] **1.2** Create `src/pyneats/core/validators.py`
  - `validate_columns(df, required, optional)`
  - `validate_attrs(attrs, required, optional)`
  - `validate_no_all_nan(df, columns)`
  - Quality: 100% test coverage

- [ ] **1.3** Create `src/pyneats/core/schemas.py`
  - `FlightSchema` dataclass
  - Predefined schemas (SCHEMA_FLIGHT_4D, SCHEMA_WITH_WEATHER, etc.)
  - `validate_flight()` and `validate_fleet()` methods
  - Quality: 100% test coverage

- [ ] **1.4** Create `src/pyneats/core/fleet_utils.py`
  - `flights_to_fleet(flights: List[Flight]) -> Fleet`
  - `fleet_to_flights(fleet: Fleet) -> List[Flight]`
  - Move from FleetRunner._seq_to_fleet / _fleet_to_seq
  - Quality: 100% test coverage, roundtrip tests

- [ ] **1.5** Create `tests/unit/test_validators.py`
  - Parametrized tests for `validate_columns()`, `validate_attrs()`, `validate_no_all_nan()`
  - Test edge cases (empty, all NaN, missing columns)
  - Test error messages and exception types
  - Use synthetic data (no golden data needed)
  - 100% coverage of validator functions
  - Quality: ruff format + check, mypy strict

- [ ] **1.6** Create `tests/unit/test_schemas.py`
  - Test FlightSchema validation
  - Test predefined schemas (SCHEMA_FLIGHT_4D, SCHEMA_WITH_WEATHER, etc.)
  - Parametrized tests for valid/invalid data
  - Use synthetic data
  - 100% coverage
  - Quality: ruff format + check, mypy strict

- [ ] **1.7** Create `tests/unit/test_fleet_utils.py`
  - Test `flights_to_fleet()` preserves data
  - Test `fleet_to_flights()` preserves data
  - Test roundtrip equivalence
  - Test fuel object restoration
  - Use golden_flights fixture for realistic data
  - 100% coverage
  - Quality: ruff format + check, mypy strict

**Workstream B: Modernization**

- [ ] **1.8** Update `pyproject.toml`
  - Migrate from `setuptools-scm` to `hatch-vcs` (automatic versioning from git tags)
  - Change `optional-dependencies` to `dependency-groups`
  - Add dev group: pytest, ruff, mypy, pre-commit, pip-audit
  - Add docs group: mkdocs-material, mkdocstrings (for future use)
  - Update ruff configuration (line length: 88, target: py311+)
  - Update mypy to strict mode (target: py311+)
  - Update pytest, coverage configurations
  - Update Python requirement to 3.11+ (pycontrails requires it)
  - Add hatch-vcs version configuration

- [ ] **1.9** Create `Makefile`
  - `install`, `check`, `lint`, `format`, `test`, `audit`
  - All commands use `uv` instead of pip
  - Test: `make help` shows all commands

- [ ] **1.10** Create `.pre-commit-config.yaml`
  - Ruff formatter (`ruff format`) and linter (`ruff check`)
  - MyPy type checker
  - Note: Ruff replaces black and isort
  - Install: `uv run pre-commit install`
  - Test: `uv run pre-commit run --all-files`

- [ ] **1.11** Create `cliff.toml`
  - Conventional commit parsing
  - Emoji categories (🚀 Features, 🐛 Fixes, etc.)
  - Test: `git cliff --latest` (after first commit)

- [ ] **1.12** Create `.github/dependabot.yml`
  - Weekly pip dependency updates
  - Weekly GitHub Actions updates
  - Group dev dependencies

- [ ] **1.13** Update `.github/workflows/test_package.yml` → `ci.yml`
  - Migrate from pip to uv
  - Add lint job (ruff + mypy)
  - Add security job (pip-audit)
  - **Preserve BADA download step** (set BADA3_PATH and BADA4_PATH environment variables)
  - Add coverage upload to Coveralls
  - Matrix: Python 3.12 + 3.13
  - Test: Push to trigger workflow

- [ ] **1.14** Create `.github/workflows/publish.yml`
  - Build with `uv build`
  - Publish to PyPI on tag (trusted publishing)
  - Test: Create test tag

- [ ] **1.15** Create `.github/workflows/release.yml`
  - Generate changelog with git-cliff
  - Create GitHub Release on tag
  - Test: Create test tag

- [ ] **1.16** Update `README.md`
  - Add professional badge row (CI, Coverage, PyPI, Python, Typed, Ruff, uv)
  - Update installation instructions (use uv)
  - Update example code if needed

- [ ] **1.17** Verify `src/pyneats/py.typed` exists
  - If missing, create empty file
  - Marks package as typed (PEP 561)

#### **Validation Criteria**
```bash
# Refactoring checks
ruff format src/pyneats tests/
ruff check src/pyneats tests/
mypy src/pyneats --strict
pytest tests/unit/ -v

# Verify golden reference data exists (provided by user)
ls tests/data/input_flights_5.json   # Raw NM JSON (input)
ls tests/data/output_flights_5.json  # FlightView JSON (output with all columns)

# Test data loads correctly
python -c "
import json
from pyneats.core.views import FlightView

# Load and validate input
with open('tests/data/input_flights_5.json') as f:
    inputs = json.load(f)
    print(f'✓ Loaded {len(inputs)} input flights')

# Load and validate output
with open('tests/data/output_flights_5.json') as f:
    data = json.load(f)
    outputs = [FlightView.from_dict(d) for d in data]
    print(f'✓ Loaded {len(outputs)} golden flights')
    print(f'✓ Columns: {list(outputs[0].data.keys())[:5]}...')
"

# Modernization checks
make help  # Makefile works
make lint  # All linting passes
make test  # All tests pass
uv run pre-commit run --all-files  # Pre-commit works

# CI/CD workflow syntax
gh workflow list  # All workflows listed
gh workflow view ci  # Syntax valid

# Verify uv installation
uv --version
uv sync --all-groups  # Dependencies install correctly
```

#### **Commit**
```bash
git add src/pyneats/core/{validators,schemas,fleet_utils}.py
git add tests/conftest.py
git add tests/unit/{test_validators,test_schemas,test_fleet_utils}.py
git add pyproject.toml Makefile .pre-commit-config.yaml cliff.toml
git add .github/{workflows/*.yml,dependabot.yml}
git add README.md src/pyneats/py.typed
git commit -m "Phase 1: Foundation + Modern Python tooling

Refactoring foundation:
- validators.py: validate_columns, validate_attrs, validate_no_all_nan
- schemas.py: FlightSchema for declarative validation
- fleet_utils.py: flights_to_fleet, fleet_to_flights conversion
- Enhanced conftest.py with fixtures for input/golden flights
- Unit tests: test_validators, test_schemas, test_fleet_utils
- Following current PyNeats test patterns + 2026 best practices

Modernization (2026 standards):
- Migrated to hatch-vcs for automatic versioning from git tags
- Added Makefile for standardized dev commands (install, lint, test, audit)
- Added pre-commit hooks (ruff format + check, mypy strict)
- Migrated CI/CD to uv package manager
- Added security audits (pip-audit)
- Added Dependabot for automated dependency updates
- Added cliff for automated changelog generation
- Added professional README badges
- Preserved BADA download in CI workflows (BADA3/BADA4 paths)
- Updated to Python 3.11+ and ruff line length 88

Testing improvements:
- Fixtures-based: input_flights, golden_flights
- Parametrized tests for comprehensive coverage
- Type-safe: All fixtures and tests fully type-hinted
- Following existing test patterns (PyContrailsEmissionModel, CoCiPModel)

Quality checks:
✓ ruff format + check: all pass
✓ mypy --strict: no errors
✓ pytest: all unit tests pass (100% coverage on new code)
✓ make lint: all pass
✓ pre-commit: all hooks pass"
```

---

### **Phase 2: Per-Step Refactoring**
**Duration**: Week 3-6
**Status**: ⏳ Not Started

Refactor **one step at a time** in order of increasing complexity.

#### **Step Order (Easiest → Hardest)**
1. CoCiP (already vectorized)
2. Weather intersection (already vectorized)
3. Humidity scaling (already vectorized)
4. Climate metrics (simple)
5. NonCO2/aCCF (moderate)
6. Parsing (needs parallelization)
7. Interpolation (needs parallelization)
8. Emissions (needs parallelization)
9. BADA Performance (most complex)

---

#### **Phase 2.1: Refactor CoCiP**
**Status**: ⏳ Not Started

- [ ] **2.1.1** Modify `src/pyneats/steps/climate_functions/cocip.py`
  - Change `CoCiPModel.__call__()` to accept Fleet input
  - Add Fleet validation
  - Keep single implementation (already works with Fleet)
  - Maintain backward compatibility temporarily

- [ ] **2.1.2** Create `tests/integration/test_step_equivalence.py::test_cocip_step_equivalence`
  - Use golden_flights fixture
  - Parametrize over all 5 flights
  - Test pattern:
    ```python
    # Create input (strip contrail columns from golden)
    input_flight = FlightWithEmissions.from_flight(flight.copy())

    # OLD: Single flight
    params = ContrailsParams(met=weather.met(), rad=weather.rad())
    old_step = CoCiPModel(params)
    old_output = old_step(input_flight)

    # NEW: Fleet
    fleet_input = flights_to_fleet([input_flight])
    new_step = CoCiPModel(params)
    fleet_output = new_step(fleet_input)
    new_output = fleet_to_flights(fleet_output)[0]

    # Compare both with golden
    assert_frame_equal(old_output, new_output, rtol=1e-6, atol=1e-9)
    assert_frame_equal(new_output, golden, rtol=1e-6, atol=1e-9)
    ```

- [ ] **2.1.3** Run validation
  ```bash
  pytest tests/integration/test_step_equivalence.py::test_cocip_step_equivalence -v
  ```

- [ ] **2.1.4** Commit and push
  ```bash
  git add src/pyneats/steps/climate_functions/cocip.py tests/integration/test_step_equivalence.py
  git commit -m "Phase 2.1: Refactor CoCiP to Fleet-only (verified equivalent)"
  git push
  ```

---

#### **Phase 2.2: Refactor Weather Intersection**
**Status**: ⏳ Not Started

- [ ] **2.2.1** Modify `src/pyneats/steps/weather/weather_provider.py`
- [ ] **2.2.2** Create equivalence test
- [ ] **2.2.3** Validate
- [ ] **2.2.4** Commit

---

#### **Phase 2.3: Refactor Humidity Scaling**
**Status**: ⏳ Not Started

- [ ] **2.3.1** Modify humidity scaling step
- [ ] **2.3.2** Create equivalence test
- [ ] **2.3.3** Validate
- [ ] **2.3.4** Commit

---

#### **Phase 2.4: Refactor Climate Metrics**
**Status**: ⏳ Not Started

- [ ] **2.4.1** Modify climate metrics step
- [ ] **2.4.2** Create equivalence test
- [ ] **2.4.3** Validate
- [ ] **2.4.4** Commit

---

#### **Phase 2.5: Refactor NonCO2/aCCF**
**Status**: ⏳ Not Started

- [ ] **2.5.1** Modify aCCF step
- [ ] **2.5.2** Create equivalence test
- [ ] **2.5.3** Validate
- [ ] **2.5.4** Commit

---

#### **Phase 2.6: Refactor Parsing**
**Status**: ⏳ Not Started

- [ ] **2.6.1** Modify parsing step (add parallelization loop)
- [ ] **2.6.2** Create equivalence test
- [ ] **2.6.3** Validate
- [ ] **2.6.4** Commit

---

#### **Phase 2.7: Refactor Interpolation**
**Status**: ⏳ Not Started

- [ ] **2.7.1** Modify interpolation step
- [ ] **2.7.2** Create equivalence test
- [ ] **2.7.3** Validate
- [ ] **2.7.4** Commit

---

#### **Phase 2.8: Refactor Emissions**
**Status**: ⏳ Not Started

- [ ] **2.8.1** Modify emissions step
- [ ] **2.8.2** Create equivalence test
- [ ] **2.8.3** Validate
- [ ] **2.8.4** Commit

---

#### **Phase 2.9: Refactor BADA Performance**
**Status**: ⏳ Not Started

- [ ] **2.9.1** Modify BADA step (complex - mass iteration)
- [ ] **2.9.2** Create equivalence test (looser tolerance)
- [ ] **2.9.3** Validate
- [ ] **2.9.4** Commit

---

### **Phase 3: Runner Unification**
**Duration**: Week 7
**Status**: ⏳ Not Started

#### **Objectives**
- Create unified `Runner` that works with Fleet only
- Deprecate `FlightRunner` (don't delete yet)
- Simplify `FleetRunner` to use new architecture

#### **Tasks**

- [ ] **3.1** Create `src/pyneats/runners/runner.py`
  - UnifiedRunner class
  - Uses fleet_utils for conversion
  - Linear pipeline with error handling
  - Quality: mypy strict, 80%+ coverage

- [ ] **3.2** Create `tests/test_regression_refactored.py`
  - Compare UnifiedRunner output vs golden reference data
  - Single-flight validation
  - Fleet validation
  - All metrics must match (rtol=1e-6, atol=1e-9)

- [ ] **3.3** Update `tests/integration/test_pipeline_stages.py`
  - Use UnifiedRunner instead of FlightRunner/FleetRunner

- [ ] **3.4** Run full regression suite
  ```bash
  pytest tests/test_regression_refactored.py -v
  ```

- [ ] **3.5** Deprecate FlightRunner (add deprecation warning)
  ```python
  # In flight.py
  import warnings
  warnings.warn("FlightRunner is deprecated, use UnifiedRunner", DeprecationWarning)
  ```

#### **Validation Criteria**
```bash
# Golden tests pass
pytest tests/test_regression_refactored.py -v

# All integration tests pass
pytest tests/integration/ -v

# Coverage maintained
pytest --cov=pyneats --cov-report=term
# Should show ≥80% coverage
```

#### **Commit**
```bash
git add src/pyneats/runners/runner.py
git add tests/test_regression_refactored.py
git commit -m "Phase 3: Add UnifiedRunner (Fleet-only architecture)"
```

---

### **Phase 4: Cleanup & Documentation**
**Duration**: Week 8
**Status**: ⏳ Not Started

#### **Objectives**
- Remove deprecated code (after validation)
- Update all documentation
- Final quality pass
- Prepare for merge to main

#### **Tasks**

- [ ] **4.1** Delete `src/pyneats/runners/flight.py` (if approved)
  - Requires user approval
  - Only after all tests pass with UnifiedRunner

- [ ] **4.2** Update `README.md`
  - Remove FlightRunner references
  - Update examples to use UnifiedRunner
  - Update architecture diagrams

- [ ] **4.3** Update `docs/index.md` and `docs/architecture.md`
  - Document new Fleet-only architecture
  - Update pipeline diagrams
  - Add migration guide (for users)

- [ ] **4.4** Update `examples/`
  - `examples/single_flight_computation.py`
  - `examples/fleet_computation_from_json.py`
  - `examples/fleet_computation_from_dataframe.py`

- [ ] **4.5** Generate/Update `CHANGELOG.md`
  ```bash
  # If cliff available
  git cliff --output CHANGELOG.md

  # Or manually add:
  ## [Unreleased] - 2026-01-XX

  ### Changed
  - **BREAKING**: Refactored to Fleet-only architecture
  - Removed FlightRunner (use UnifiedRunner instead)
  - Simplified internal pipeline structure

  ### Added
  - Core validators and schemas for type-safe validation
  - Fleet conversion utilities
  - Comprehensive test suite (80%+ coverage)

  ### Removed
  - FlightRunner class (deprecated in previous version)
  - Duplicate code in FleetRunner (~1400 lines)
  ```

- [ ] **4.6** Run full quality check
  ```bash
  # Formatting
  ruff format src/pyneats tests/ examples/

  # Linting
  ruff check src/pyneats tests/ examples/

  # Type checking
  mypy src/pyneats

  # Tests
  pytest tests/ -v --cov=pyneats --cov-report=term --cov-report=html

  # Golden validation
  pytest tests/test_regression_refactored.py -v
  ```

- [ ] **4.7** Performance benchmarks
  ```bash
  pytest tests/performance/ -v
  # Ensure no regression (±5% acceptable)
  ```

#### **Validation Criteria**
```bash
# All quality checks pass
ruff format --check src/ tests/ examples/
ruff check src/ tests/ examples/
mypy src/pyneats

# All tests pass
pytest tests/ -v

# Coverage ≥80%
pytest --cov=pyneats --cov-fail-under=80

# Golden tests pass
pytest tests/test_regression_refactored.py -v

# No performance regression
pytest tests/performance/ -v
```

#### **Commit**
```bash
git add -A
git commit -m "Phase 4: Complete Fleet-only refactoring

Documentation and cleanup:
- Update README, docs, examples
- Remove deprecated FlightRunner
- Update CHANGELOG
- All quality checks pass
- Coverage: 82%
- Golden tests: PASS
- Performance: no regression"
```

---

## Current Status

### **Phase Progress**
- **Phase 0**: ✓ Complete (Planning & CLAUDE.md)
- **Phase 1**: ⏳ Not Started (Foundation)
- **Phase 2**: ⏳ Not Started (Step Refactoring)
- **Phase 3**: ⏳ Not Started (Runner Unification)
- **Phase 4**: ⏳ Not Started (Cleanup & Documentation)

### **Current Phase**: Phase 0 - Planning ✓

### **Last Updated**: 2026-01-13

### **Active Branch**: `claude/refactor-fleet-only-9triX`

### **Blockers**: None

### **Next Actions**
1. ✓ Branch created: `claude/refactor-fleet-only-9triX`
2. ⏳ User reviews and approves CLAUDE.md
3. Begin Phase 1: Foundation

---

## References

### **Key Files**
- **This Document**: `CLAUDE.md` (refactoring contract)
- **Main Code**: `src/pyneats/`
- **Tests**: `tests/`
- **Golden Reference Data**: `tests/data/test_flights_5.json` (provided by user, includes inputs + outputs)
- **Configuration**: `pyproject.toml`

### **Quality Tools Configuration**

All tools configured in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.format]
# Ruff replaces black and isort

[tool.mypy]
strict = true
python_version = "3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.hatch.version]
source = "vcs"  # Automatic versioning from git tags
```

### **Test Markers**
- `@pytest.mark.requires_bada` - Requires BADA coefficients (BADA3 or BADA4)
- `@pytest.mark.requires_weather` - Requires weather data
- `@pytest.mark.slow` - Long-running tests (>10s)
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.benchmark` - Performance benchmarks

### **Running Tests**

```bash
# Fast tests (no BADA, no weather)
pytest -m "not slow and not requires_bada and not requires_weather" -v

# With BADA and weather
pytest --met-cache-dir=/path/to/cache -v

# Specific phase
pytest tests/unit/test_validators.py -v

# With coverage
pytest --cov=pyneats --cov-report=html -v

# Golden validation
pytest tests/test_regression_refactored.py -v
```

### **Contact & Questions**
- For questions about this refactoring, refer to this document
- For PyNeats questions, see `README.md` and `docs/`
- For issues, see GitHub issues

---

## Notes

### **Important Reminders**
- ⚠️ Claude commits ONLY after user approval
- ⚠️ User controls when to push to remote
- ⚠️ All changes must pass quality checks before commit
- ⚠️ Golden reference data (user-provided) is the source of truth for behavioral equivalence
- ⚠️ Each phase is independently reviewable and revertible

### **Decision Log**

**2026-01-13: Chose Fleet-only over Flight|Fleet polymorphism**
- Reason: Simpler, less code duplication, single source of truth
- Alternative: Polymorphic run(Flight|Fleet) would duplicate conversion logic across all steps

**2026-01-13: Chose incremental per-step refactoring**
- Reason: Lower risk, easier to validate, can pause/resume
- Alternative: Big-bang refactoring would be faster but riskier

**2026-01-13: Chose golden reference testing strategy**
- Reason: Mathematical proof of equivalence, regression detection
- Alternative: Manual testing would be error-prone

---

**End of CLAUDE.md**

*This document is a living contract and will be updated as the refactoring progresses.*
