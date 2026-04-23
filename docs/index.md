---
hide:
  - navigation
  - toc
---

# PyNeats

<p align="center">
  <strong>Aviation non-CO₂ climate metrics pipeline — the MRV reference implementation.</strong>
</p>

<p align="center">
  <a href="https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml">
    <img src="https://github.com/eurocontrol-asu/PyNeats/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <a href="https://pypi.org/project/pyneats/">
    <img src="https://img.shields.io/pypi/v/pyneats" alt="PyPI" />
  </a>
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+" />
  <a href="https://eurocontrol-asu.github.io/PyNeats/">
    <img src="https://img.shields.io/badge/docs-live-brightgreen" alt="Docs" />
  </a>
</p>

---

## What is PyNeats?

PyNeats implements the computation pipeline defined in the *Reference set of technical specifications for the MRV* (EC-CLIMA/2024/NP/0014). It turns 4D flight trajectories into climate-forcing metrics (CO₂-equivalent, GWP) for the non-CO₂ effects of aviation — contrails, NOₓ, soot, water vapour.

The pipeline is **modular**: parsing, interpolation, weather, performance, emissions, climate functions, climate metrics — each step swappable, each built on established libraries (PyBADA, PyContrails, CLIMaCCF, OpenAirClim).

## Documentation

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Tutorials**

    ---

    Start here if you are new. Install PyNeats and run your first fleet computation.

    [:octicons-arrow-right-24: Quick Start](tutorials/quickstart.md)

-   :material-book-open-variant:{ .lg .middle } **How-To Guides**

    ---

    Task-oriented recipes: parse trajectories, build weather caches, pick a runner.

    [:octicons-arrow-right-24: Usage guide](howto/usage.md)

-   :material-file-document-outline:{ .lg .middle } **Reference**

    ---

    Auto-generated API reference from the source docstrings, plus CLI and I/O schemas.

    [:octicons-arrow-right-24: Example scripts](reference/example-scripts.md)

-   :material-lightbulb-on-outline:{ .lg .middle } **Explanation**

    ---

    The MRV specification, architecture, input prioritization, and design choices.

    [:octicons-arrow-right-24: MRV specification](explanation/mrv-specification.md)

</div>

## Installation

!!! note "PyPI availability"

    PyNeats is not yet published on PyPI — the repository is currently private.
    Once released, install with:

    ```bash
    uv add pyneats
    ```

    In the meantime, clone the repository and install from source (see
    [Quick Start](tutorials/quickstart.md)).

## License

PyNeats is licensed under the **EUPL 1.2** with an amendment from EUROCONTROL. See [LICENSE](https://github.com/eurocontrol-asu/PyNeats/blob/main/LICENSE.md) and the [amendment](https://github.com/eurocontrol-asu/PyNeats/blob/main/AMENDMENT_TO_EUPL_license.md).
