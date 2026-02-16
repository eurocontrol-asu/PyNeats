# Quick Start

This tutorial walks you through installing PyNeats and running your first climate impact computation.

## Prerequisites

- **Python 3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended package manager)
- **BADA data** — EUROCONTROL aircraft performance coefficients (required for full pipeline)
- **Weather data** — DWD ICON or ERA5 meteorological data in Zarr format

## Step 1: Install

```bash
git clone https://github.com/eurocontrol-asu/PyNeats.git
cd PyNeats
make install
```

This runs `uv sync` and installs external dependencies (PyBADA, open-airclim).

!!! tip "Verify installation"
    ```bash
    make test-unit
    ```
    Unit tests run without external data.

## Step 2: Prepare Data

PyNeats requires two external data sources:

| Data | Format | Source |
|---|---|---|
| BADA coefficients | Directory | EUROCONTROL (licensed) |
| Weather | Zarr store | DWD ICON or ERA5 |

Set the paths as environment variables or pass them as CLI arguments:

```bash
export BADA_PATH=/path/to/bada/data
export WEATHER_PATH=/path/to/weather/zarr
```

## Step 3: Run the Pipeline

Process a fleet of flights from a JSON file:

```bash
uv run python examples/fleet_computation_from_json.py \
  --json-file tests/data/golden/fleet_5_flights_input.json \
  --weather-path $WEATHER_PATH \
  --bada-path $BADA_PATH \
  --njobs 4
```

The pipeline executes these steps sequentially for each flight:

1. **Parse** — Extract 4D trajectory from input data
2. **Interpolate** — Resample to 60-second intervals
3. **Weather** — Intersect trajectory with meteorological fields
4. **Performance** — Compute fuel flow and thrust via BADA
5. **Emissions** — Calculate emission indices (NOₓ, nvPM, etc.)
6. **Climate functions** — Estimate climate forcing (CoCiP, aCCFs)
7. **Climate metrics** — Convert to GWP / CO₂-equivalent

## Next Steps

- [Usage guide](../howto/usage.md) — Processing flights from DataFrames, building weather caches
- [Architecture](../explanation/architecture.md) — System design and module overview
- [Python API](../reference/api/) — Auto-generated API reference
