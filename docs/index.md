# PyNeats

**PyNeats** computes non-CO₂ aviation climate impacts (GWP, CO₂-equivalent) following the MRV technical specification.

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
