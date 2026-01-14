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

### Using uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package manager. Install it first:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install PyNeats
git clone https://github.com/eurocontrol-asu/PyNeats.git
cd PyNeats

# Install all dependencies (including dev tools)
uv sync --all-groups

# Install pybada manually (has non-standard requirements)
uv pip install pybada --ignore-requires-python --no-deps
```

### Using pip

Alternatively, use pip in a fresh virtual environment:

```bash
git clone https://github.com/eurocontrol-asu/PyNeats.git
cd PyNeats
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
pip install pybada --ignore-requires-python --no-deps
