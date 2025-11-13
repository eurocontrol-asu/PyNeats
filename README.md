# pyneats

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

> **Note:** `pyneats` depends on multiple scientific libraries with specific version requirements.  
> We recommend installing it in a fresh **conda** or **venv** environment.

```bash

git clone https://github.com/eurocontrol-asu/PyNeats.git
cd PyNeats
pip install -e .[accf]
pip install pybada --ignore-requires-python --no-deps
