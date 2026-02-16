# PyNeats

<p align="center">
  <a href="https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml"><img src="https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://codecov.io/gh/eurocontrol-asu/PyNeats"><img src="https://codecov.io/gh/eurocontrol-asu/PyNeats/branch/main/graph/badge.svg" alt="codecov" /></a>
  <a href="https://badge.fury.io/py/pyneats"><img src="https://badge.fury.io/py/pyneats.svg" alt="PyPI version" /></a>
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+" />
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff" /></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv" /></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/typed-mypy-blue" alt="Typed" /></a>
  <a href="https://eurocontrol-asu.github.io/PyNeats/"><img src="https://img.shields.io/badge/docs-live-brightgreen" alt="Docs" /></a>
</p>


It orchestrates [PyContrails](https://github.com/contrailcirrus/pycontrails), [PyBADA](https://github.com/eurocontrol-bada/pybada), [CLIMaCCF](https://github.com/dlr-pa/climaccf), and [OpenAirClim](https://github.com/dlr-pa/oac) into a modular, end-to-end pipeline.

---

## Getting Started

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Quick Start](tutorials/quickstart.md)**

    Install PyNeats and run your first climate impact computation.

-   :material-book-open-variant: **[Usage Guide](howto/usage.md)**

    Process DataFrames, build weather caches, choose runners.

-   :material-api: **[API Reference](reference/api/)**

    Auto-generated documentation for all public modules.

-   :material-sitemap: **[Architecture](explanation/architecture.md)**

    System design, step protocol, flight views, runners.

-   :material-file-document: **[MRV Specification](explanation/mrv_specification.md)**

    Detailed implementation of the MRV technical requirements.

</div>

---

## Pipeline at a Glance

```
Parsing → Interpolation → Weather → Performance → Emissions → Climate Functions → Climate Metrics
```

Each stage is an independent **Step** that can be swapped, tested, and configured separately via the step registry.

---

## Key Features

- **MRV compliant** — implements EC-CLIMA/2024/NP/0014
- **Method C** — CoCiP contrails + aCCFs for large emitters
- **Method D** — OpenAirClim for small emitters
- **Fleet-level** — parallel execution with `joblib` and per-flight fault tolerance
- **No new kernels** — relies on established open-source libraries for all numerics
