# pyneats

[![CI](https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml/badge.svg)](https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/eurocontrol-asu/PyNeats/badge.svg?branch=main)](https://coveralls.io/github/eurocontrol-asu/PyNeats?branch=main)
[![PyPI version](https://badge.fury.io/py/pyneats.svg)](https://badge.fury.io/py/pyneats)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Typed](https://img.shields.io/badge/typed-mypy%20strict-blue)](https://mypy-lang.org/)

**pyneats** is an open-source Python library implementing the **MRV (Monitoring, Reporting, and Verification)** technical requirements for computing **non-CO₂ climate impacts of aviation**, expressed as **GWP (Global Warming Potential)** and related metrics.

It integrates multiple established open-source tools to provide a reproducible, end-to-end workflow for estimating aviation’s climate effects beyond CO₂ emissions:

- [**PyContrails**](https://github.com/contrailcirrus/pycontrails) – for contrail prediction and atmospheric data processing
- [**ClimAccf**](https://github.com/dlr-pa/climaccf) – for calculating non-CO₂ aviation climate change functions (aCCFs)
- [**PyBADA**](https://github.com/eurocontrol-bada/pybada) – for aircraft performance modelling using EUROCONTROL’s BADA datasets
- [**open-airclim**](https://github.com/openclimatefix/open-airclim) – for integrating climate response functions and GWP calculations (to be used for method D in future PyNeats versions)

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
- **uv** (fast Python package manager) – [Installation guide](https://github.com/astral-sh/uv#getting-started)

### Development Installation (Current)

**Note:** PyNeats is currently in active development and not yet published to PyPI. Installation is available for developers and contributors only via the source repository.

```bash
# 1. Clone the repository
git clone https://github.com/eurocontrol-asu/PyNeats.git
cd PyNeats

# 2. Install all dependencies (including dev tools)
uv sync --all-groups

# 3. Install PyBADA manually (has non-standard requirements)
uv pip install pybada --ignore-requires-python --no-deps
```

**Verify installation:**
```bash
# Run tests
uv run pytest tests/ -v

# Run an example
uv run examples/fleet_computation_from_json.py --help
```

### For Contributors

If you plan to contribute to PyNeats, see [CONTRIBUTING.md](CONTRIBUTING.md) for additional setup instructions and development workflow guidelines.

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
└── adapters/          # Wrappers around external libraries
```

**Key Design Principles:**
- **Modular pipeline**: Each step is independent and can be tested/reused separately
- **Type safety**: Strict mypy type checking for reliability
- **Open-source integration**: Uses PyContrails, ClimAccf, PyBADA, and open-airclim
- **Performance-optimized**: Vectorized operations for fleet-level computations with joblib parallelization

---

## 🚀 Quick Start

### 1. Example: Climate Impact Computation from JSON

Process flight trajectories from a JSON file:

```bash
uv run examples/fleet_computation_from_json.py \
  --json-file tests/data/golden/fleet_5_flights_input.json \
  --weather-path /path/to/weather/zarr/cache \
  --bada-path /path/to/bada/data \
  --njobs 4
```

See [examples/README.md](examples/README.md) for more examples and detailed instructions.

### 2. Example: Climate Impact Computation from DataFrame

Process flight data from a pandas DataFrame:

```bash
uv run examples/fleet_computation_from_dataframe.py \
  --weather-path /path/to/weather/zarr/cache \
  --bada-path /path/to/bada/data \
  --njobs 4
```

### 3. Example: Build Weather Cache

Build and cache meteorological data from DWD for reuse:

```bash
uv run examples/weather_cache.py \
  --dwd-path /path/to/dwd/icon/data \
  --zarr-path /path/to/output/zarr/cache \
  --date 2025-07-09 \
  --hour 0
```

### More Examples

For additional examples and detailed documentation, see [examples/README.md](examples/README.md).

---

## 📚 Documentation

- **[Architecture](docs/architecture.md)** – System design and module overview
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
| **PyBADA** | Aircraft performance modeling | [github.com/eurocontrol-bada/pybada](https://github.com/eurocontrol-bada/pybaba) |
| **open-airclim** | Climate response functions and GWP | [github.com/openclimatefix/open-airclim](https://github.com/openclimatefix/open-airclim) |

---

## ❓ Support

For questions, bug reports, or feature requests, please [open an issue](https://github.com/eurocontrol-asu/PyNeats/issues) on GitHub.
