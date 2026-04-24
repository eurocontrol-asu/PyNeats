# Glossary

Project-wide glossary of domain terms, abbreviations and library names
encountered across the documentation. For the spec-specific abbreviations used
in formulas, see also the [Abbreviations](explanation/mrv-specification.md#abbreviations)
section of the MRV specification page.

## Climate science

| Term | Definition |
|---|---|
| **aCCF** | *algorithmic Climate Change Function* — a family of regression formulas that estimate climate impact (ATR, RF) from local atmospheric conditions. |
| **AGWP** | *Absolute Global Warming Potential* — cumulative radiative forcing over a time horizon per unit emission (W·m⁻²·yr·kg⁻¹). |
| **ATR** | *Average Temperature Response* — average global temperature change induced over a time horizon. |
| **CoCiP** | *Contrail Cirrus Prediction model* — Schumann et al. model for contrail energy forcing. Used in Method C via the `pycontrails` library. |
| **CO2e / CO2eq** | *CO₂-equivalent* — mass of CO₂ that would produce the same climate impact over a given horizon as a given quantity of another forcing agent. |
| **EAGWP** | *Efficacy-adjusted AGWP* — AGWP multiplied by a species-specific efficacy factor (ε). |
| **EF** | *Energy Forcing* — integrated radiative forcing over contrail extent (J). |
| **GWP** | *Global Warming Potential* — relative climate forcing per unit emission. |
| **MRV** | *Monitoring, Reporting, Verification* — the EU regulatory framework PyNeats implements. |
| **RF** | *Radiative Forcing* — imbalance in Earth's radiation budget (W·m⁻²). |
| **SAC** | *Schmidt-Appleman Criterion* — thermodynamic condition for contrail formation. |
| **ISSR** | *Ice-Supersaturated Region* — airmass where contrails can persist. |

## Aviation & trajectories

| Term | Definition |
|---|---|
| **AO** | *Aircraft Operator* — airline or operator reporting flights. |
| **BADA** | *Base of Aircraft Data* — EUROCONTROL aircraft-performance coefficient database (licensed). |
| **CTFM** | *Current Tactical Flight Model* — trajectory from live radar data. |
| **FTFM** | *Filed Tactical Flight Model* — trajectory from filed flight plan. |
| **RTFM** | *Regulated Tactical Flight Model* — trajectory as constrained by ATC regulations. |
| **OFP** | *Operational Flight Plan* — airline-produced flight plan, typically the richest primary source. |
| **QAR** | *Quick Access Recorder* — onboard data recorder, highest-fidelity primary source. |
| **MTOW / MPL / OEW / TOW** | Max Take-Off Weight / Max Payload / Operating Empty Weight / Take-Off Weight. |
| **FL** | *Flight Level* — altitude in hundreds of feet (FL350 ≈ 35,000 ft). |
| **NWP** | *Numerical Weather Prediction* — model-based forecast (e.g. ICON, ECMWF IFS). |
| **TAS** | *True Airspeed*. |

## Emissions

| Term | Definition |
|---|---|
| **EI** | *Emission Index* — mass of pollutant per mass of fuel burnt (g/kg fuel). |
| **nvPM** | *non-volatile Particulate Matter* — soot particles. |
| **vPM** | *volatile Particulate Matter* — organics/sulphates formed post-emission. |
| **BFFM2 / FFM2** | *Boeing Fuel Flow Method 2* — regression for NOₓ/CO/HC emission indices. |
| **MRR** | *Monitoring, Reporting and Regulation* — default engine lookup table. |

## Libraries & implementations

| Term | Definition |
|---|---|
| **CLIMaCCF** | Reference Python library implementing aCCFs (Yin, Dietmüller et al.). |
| **climaccf** | PyPI package name that distributes CLIMaCCF. |
| **`ACCFModel`** | PyNeats step class that wraps `climaccf`. |
| **`LocalACCFModel`** | PyNeats step class — in-tree reimplementation of aCCF v1.0A, emulating CLIMaCCF without the runtime dependency. |
| **pycontrails** | Python library providing CoCiP + atmospheric utilities. |
| **pyBADA** | EUROCONTROL Python wrapper over BADA performance coefficients. |
| **OpenAirClim** | Library for Method D (small-emitter climate metrics). |
| **DWD ICON** | German Weather Service NWP model — PyNeats default weather source. |
| **ERA5** | ECMWF reanalysis (historical) — alternative weather source. |
| **Zarr** | Chunked on-disk array format used by PyNeats weather cache. |

## Method codes

| Term | Definition |
|---|---|
| **Method C** | Large-emitter method — per-flight CoCiP + aCCF pipeline. |
| **Method D** | Small-emitter method — stand-alone OpenAirClim computation. |
