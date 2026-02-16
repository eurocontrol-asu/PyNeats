# pyneats

[![CI](https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml/badge.svg)](https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/eurocontrol-asu/PyNeats/branch/main/graph/badge.svg)](https://codecov.io/gh/eurocontrol-asu/PyNeats)
[![PyPI version](https://badge.fury.io/py/pyneats.svg)](https://badge.fury.io/py/pyneats)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Typed](https://img.shields.io/badge/typed-mypy-blue)](https://mypy-lang.org/)
[![Docs](https://img.shields.io/badge/docs-live-brightgreen)](https://eurocontrol-asu.github.io/PyNeats/)

**pyneats** is an open-source Python library implementing the **MRV (Monitoring, Reporting, and Verification)** technical requirements for computing **non-CO₂ climate impacts of aviation**, expressed as **GWP (Global Warming Potential)** and related metrics.

It integrates multiple established open-source tools to provide a reproducible, end-to-end workflow for estimating aviation's climate effects beyond CO₂ emissions:

- [**PyContrails**](https://github.com/contrailcirrus/pycontrails) – for contrail prediction and atmospheric data processing
- [**ClimAccf**](https://github.com/dlr-pa/climaccf) – for calculating non-CO₂ aviation climate change functions (aCCFs)
- [**PyBADA**](https://github.com/eurocontrol-bada/pybada) – for aircraft performance modelling using EUROCONTROL's BADA datasets
- [**open-airclim**](https://github.com/dlr-pa/oac) – for integrating climate response functions and GWP calculations

The library is designed for **researchers, airspace operators, regulators, and industry** who need a transparent and auditable implementation for MRV purposes.

---

## ✨ Features

- **Full MRV compliance**: Implements the MRV technical requirements for non-CO₂ climate impact assessment
- **Multi-library integration**: Seamless interoperability between PyContrails, ClimAccf, PyBADA, and open-airclim
- **Aircraft- and flight-level analysis**: Uses flight trajectory, performance, and meteorological data
- **Contrail modelling**: Predicts contrail formation and persistence from actual flight and weather data
- **Climate metric computation**: Outputs Global Warming Potential (GWP) and other climate response metrics
- **Reproducible workflows**: Built on open-source tools with clear, documented interfaces

---

## 📦 Installation

### Prerequisites

- **Python 3.11+** (see [Python installation](https://www.python.org/downloads/))
- **uv** (fast Python package manager) – [Installation guide](https://docs.astral.sh/uv/getting-started/installation/)
- **make** (build automation tool) – typically pre-installed on Linux/macOS

### Quick Install (Recommended)

```bash
# Clone the repository
git clone https://github.com/eurocontrol-asu/PyNeats.git
cd PyNeats

# Install all dependencies (including PyBADA and open-airclim)
make install
```

This runs `uv sync` and installs PyBADA with the correct flags.

### Manual Installation

If you prefer not to use make:

```bash
# Clone the repository
git clone https://github.com/eurocontrol-asu/PyNeats.git
cd PyNeats

# Install dependencies
uv sync --all-groups

# Install PyBADA (requires special flags due to Python version constraints)
uv run pip install pybada --no-deps --ignore-requires-python

# Install open-airclim
uv run pip install git+https://github.com/dlr-pa/oac.git
```

### Verify Installation

```bash
# Run unit tests (no external data required)
make test-unit

# Show available make commands
make help
```

### For Contributors

Install pre-commit hooks for automatic code quality checks:

```bash
make pre-commit-install
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow guidelines.

---

## 🧪 Running Tests

PyNeats tests require external data (BADA aircraft performance data and weather data) for full integration testing.

```bash
# Run unit tests only (no external data required)
make test-unit

# Run all tests with BADA data
make test BADA_PATH=/path/to/bada

# Run all tests with BADA and weather data
make test BADA_PATH=/path/to/bada WEATHER_PATH=/path/to/weather

# Run tests without coverage (faster)
make test-fast BADA_PATH=/path/to/bada
```

You can also set environment variables instead:

```bash
export BADA_PATH=/path/to/bada
export WEATHER_PATH=/path/to/weather
make test
```

---

## 🏗️ Architecture

PyNeats is organized into modular components:

```
src/pyneats/
├── core/              # Shared types, constants, and protocols
├── runners/           # Fleet and flight-level computation orchestration
├── steps/             # Pipeline stages (parsing, weather, performance, emissions, climate)
│   ├── parsing/       # Trajectory parsing and flight reconstruction
│   ├── weather/       # Meteorological data handling (Zarr-based weather stores)
│   ├── interpolation/ # Trajectory and performance interpolation
│   ├── performance/   # Aircraft performance modeling (PyBADA integration)
│   ├── emissions/     # Fuel burn and emissions calculation
│   ├── climate_functions/  # Climate response functions (PyContrails, ClimAccf)
│   └── climate_metrics/    # GWP and climate impact metrics
└── resources/         # Bundled data files
```

**Key Design Principles:**
- **Modular pipeline**: Each step is independent and can be tested/reused separately
- **Type safety**: mypy type checking for reliability
- **Open-source integration**: Uses PyContrails, ClimAccf, PyBADA, and open-airclim
- **Performance-optimized**: Vectorized operations for fleet-level computations with joblib parallelization

---

## 🚀 Quick Start

### 1. Example: Climate Impact Computation from JSON

Process flight trajectories from a JSON file:

```bash
uv run python examples/fleet_computation_from_json.py \
  --json-file tests/data/golden/fleet_5_flights_input.json \
  --weather-path /path/to/weather/zarr/cache \
  --bada-path /path/to/bada/data \
  --njobs 4
```

See [examples/README.md](examples/README.md) for more examples and detailed instructions.

### 2. Example: Climate Impact Computation from DataFrame

Process flight data from a pandas DataFrame:

```bash
uv run python examples/fleet_computation_from_dataframe.py \
  --weather-path /path/to/weather/zarr/cache \
  --bada-path /path/to/bada/data \
  --njobs 4
```

### 3. Example: Build Weather Cache

Build and cache meteorological data from DWD for reuse:

```bash
uv run python examples/weather_cache.py \
  --dwd-path /path/to/dwd/icon/data \
  --zarr-path /path/to/output/zarr/cache \
  --date 2025-07-09 \
  --hour 0
```

### More Examples

For additional examples and detailed documentation, see [examples/README.md](examples/README.md).

---

## 🛠️ Development

### Available Make Commands

```bash
make help              # Show all available commands
make install           # Install all dependencies
make format            # Format code with ruff
make lint              # Run linting and type checking
make test              # Run tests with coverage
make test-fast         # Run tests without coverage
make test-unit         # Run unit tests only (no external data)
make audit             # Run security audit
make check             # Run all checks (lint + audit + test)
make pre-commit        # Run pre-commit on all files
make clean             # Clean build artifacts
```

---

## 📚 Documentation

- **[Architecture](docs/explanation/architecture.md)** – System design and module overview
- **[Examples](examples/README.md)** – Runnable examples with explanations
- **[Contributing](CONTRIBUTING.md)** – Development setup and contribution guidelines

---

## 📝 License

PyNeats is released under the **MIT License**. See [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for:
- How to set up the development environment
- Code style and quality guidelines
- Testing requirements
- Submission process for pull requests

---

## 🔗 Dependencies

PyNeats integrates with these established open-source projects:

| Library | Purpose | Link |
|---------|---------|------|
| **PyContrails** | Contrail prediction and atmospheric data | [github.com/contrailcirrus/pycontrails](https://github.com/contrailcirrus/pycontrails) |
| **ClimAccf** | Aviation climate change functions (aCCFs) | [github.com/dlr-pa/climaccf](https://github.com/dlr-pa/climaccf) |
| **PyBADA** | Aircraft performance modeling | [github.com/eurocontrol-bada/pybada](https://github.com/eurocontrol-bada/pybada) |
| **open-airclim** | Climate response functions and GWP | [github.com/dlr-pa/oac](https://github.com/dlr-pa/oac) |

---

## ❓ Support

For questions, bug reports, or feature requests, please [open an issue](https://github.com/eurocontrol-asu/PyNeats/issues) on GitHub.
