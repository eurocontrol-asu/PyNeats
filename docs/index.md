# pyneats Documentation

**pyneats** is a modular Python framework for computing the **non-CO₂ climate impact of aviation**, with a focus on **transparent, reproducible, and composable pipelines**.

It acts as a lightweight orchestrator on top of established scientific libraries:

- [PyContrails](https://github.com/contrailcirrus/pycontrails) — contrail formation & lifecycle modeling (e.g., CoCiP)
- [PyBADA](https://github.com/openap-ats/pybada) — aircraft performance & fuel flow modeling
- [ClimAccf](https://github.com/dlr-climaccf/climaccf) — climate metrics such as GWP and ATR
- Meteorological data sources (DWD ICON, ERA5, etc.)

---

## Key Features

- **Step-based pipeline design** — Each stage takes a `Flight` and returns a `Flight`, validated via zero-copy typed views.
- **Adapters for external models** — Thin wrappers for PyContrails, PyBADA, ClimAccf, DWD, etc., provide a single choke point for integration.
- **Fail-fast validation** — Each step has a domain-specific error type (e.g., `WeatherStepError`, `EmissionsStepError`).
- **No unnecessary copies** — Memory-efficient operations by reusing `Flight.data` and `attrs` where possible.
- **CLI-ready** — A `pyneats run` command can execute pipelines from YAML/JSON configs.

---

