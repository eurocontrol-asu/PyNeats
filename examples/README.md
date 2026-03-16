# PyNeats Examples

This directory contains examples demonstrating how to use PyNeats for fleet-level climate impact computations.

## Examples

### fleet_computation_from_dataframe.py

Demonstrates how to compute climate impacts for a fleet of flights loaded from a pandas DataFrame.

**Usage:**
```bash
uv run examples/fleet_computation_from_dataframe.py \
  --weather-path /path/to/weather/data \
  --bada-path /path/to/bada/data \
  --njobs 4
```

**Arguments:**
- `--weather-path` (required): Path to meteorological data directory (should contain `icon_met.zarr`, `icon_rad.zarr`, etc.)
- `--bada-path` (required): Path to BADA (Base of Aircraft Data) directory
- `--njobs` (optional): Number of parallel jobs (default: 2)

**Example Data - End-to-End Demo:**
This example loads data from the JSON test file and converts it to a DataFrame, then processes it with the FleetRunnerLargeEmitter. It demonstrates:
- How to structure trajectory data as a pandas DataFrame
- The `json_to_dataframe()` helper function that converts JSON trajectories to DataFrames
- How to run the full climate impact computation pipeline

```bash
# ✅ This example runs successfully with test data
uv run examples/fleet_computation_from_dataframe.py \
  --weather-path /data/common/dataiku2/managed_folders/NEATS_CLEAN/dn2ByoqA/met_cache \
  --bada-path /data/common/dataiku2/config/projects/NEATS_CLEAN/lib/python/BADA/pyBADA \
  --njobs 2
```

### fleet_computation_from_json.py

Demonstrates how to compute climate impacts for a fleet of flights loaded from a JSON file.

**Usage:**
```bash
uv run examples/fleet_computation_from_json.py \
  --json-file /path/to/trajectories.json \
  --weather-path /path/to/weather/data \
  --bada-path /path/to/bada/data \
  --njobs 4
```

**Arguments:**
- `--json-file` (required): Path to JSON file containing flight trajectories
- `--weather-path` (required): Path to meteorological data directory
- `--bada-path` (required): Path to BADA (Base of Aircraft Data) directory
- `--njobs` (optional): Number of parallel jobs (default: 2)

**Example Data - Working End-to-End Demo:**
Test JSON files are available in `tests/data/golden/`:
- `fleet_5_flights_input.json` - Sample input with 5 flights that produces complete results

```bash
# ✅ This example runs successfully with test data
uv run examples/fleet_computation_from_json.py \
  --json-file tests/data/golden/fleet_5_flights_input.json \
  --weather-path /data/common/dataiku2/managed_folders/NEATS_CLEAN/dn2ByoqA/met_cache \
  --bada-path /data/common/dataiku2/config/projects/NEATS_CLEAN/lib/python/BADA/pyBADA \
  --njobs 2
```

### fleet_small_emitter.py

Demonstrates how to compute climate impacts for small emitters using the **OpenAirClim pipeline** (no CoCiP / weather-based contrail modelling).

**Usage:**
```bash
uv run examples/fleet_small_emitter.py \
  --json-file /path/to/trajectories.json \
  --weather-path /path/to/weather/data \
  --bada-path /path/to/bada/data \
  --tmp-dir /path/to/tmp \
  --njobs 4
```

**Arguments:**
- `--json-file` (required): Path to JSON file containing flight trajectories
- `--weather-path` (required): Path to meteorological data directory
- `--bada-path` (required): Path to BADA (Base of Aircraft Data) directory
- `--tmp-dir` (required): Path to a temporary directory for OpenAirClim file I/O
- `--njobs` (optional): Number of parallel jobs (default: 2)

**Example with test data:**
```bash
# ✅ This example runs successfully with test data
uv run examples/fleet_small_emitter.py \
  --json-file tests/data/golden/fleet_5_flights_input.json \
  --weather-path /data/common/dataiku2/managed_folders/NEATS_CLEAN/dn2ByoqA/met_cache \
  --bada-path /data/common/dataiku2/config/projects/NEATS_CLEAN/lib/python/BADA/pyBADA \
  --tmp-dir /tmp/openairclim \
  --njobs 2
```

### fleet_performance_only.py

Demonstrates how to compute **performance metrics only** (fuel flow, aircraft mass, true airspeed, engine efficiency) without running emissions, contrails, or climate impact steps. Significantly faster than the full pipeline.

**Usage:**
```bash
uv run examples/fleet_performance_only.py \
  --json-file /path/to/trajectories.json \
  --weather-path /path/to/weather/data \
  --bada-path /path/to/bada/data \
  --njobs 4
```

**Arguments:**
- `--json-file` (required): Path to JSON file containing flight trajectories
- `--weather-path` (required): Path to meteorological data directory
- `--bada-path` (required): Path to BADA (Base of Aircraft Data) directory
- `--njobs` (optional): Number of parallel jobs (default: 2)

**Example with test data:**
```bash
# ✅ This example runs successfully with test data
uv run examples/fleet_performance_only.py \
  --json-file tests/data/golden/fleet_5_flights_input.json \
  --weather-path /data/common/dataiku2/managed_folders/NEATS_CLEAN/dn2ByoqA/met_cache \
  --bada-path /data/common/dataiku2/config/projects/NEATS_CLEAN/lib/python/BADA/pyBADA \
  --njobs 2
```

**Output** includes per-flight performance trajectory vectors:
- `timestamps` — waypoint timestamps
- `fuel_flow` — fuel flow rate
- `aircraft_mass` — aircraft mass along the trajectory
- `true_airspeed` — true airspeed
- `engine_efficiency` — engine thermal efficiency

## Output (full pipeline examples)

The `fleet_computation_*` and `fleet_small_emitter` examples produce detailed climate impact metrics including:
- **Flight Information**: Flight ID, airports, aircraft type, fuel burn
- **Climate Metrics**: CO₂, contrails, CH₄, O₃, H₂O impacts
- **Horizons**: 20, 50, and 100-year impact assessments
- **EAGWP**: Energy-adjusted global warming potential (J/m²)
- **CO₂ Equivalent**: Climate impact in CO₂-equivalent kilograms

### weather_cache.py

Builds and caches meteorological data from DWD (Deutscher Wetterdienst) in Zarr format for use in climate computations.

**Usage:**
```bash
uv run examples/weather_cache.py \
  --dwd-path /path/to/dwd/data \
  --zarr-path /path/to/output/zarr \
  --date 2025-07-09 \
  --hour 0
```

**Arguments:**
- `--dwd-path` (required): Path to DWD (Deutscher Wetterdienst) data directory
- `--zarr-path` (required): Path to output directory where Zarr stores will be created
- `--date` (optional): Date to cache data for (YYYY-MM-DD format, default: 2025-07-09)
- `--hour` (optional): Time of day to cache (0-23 hours, default: 0)
- `--include-wind` (optional): Include wind data cache (requires additional processing)
- `--overwrite` (optional): Overwrite existing Zarr stores

**Notes:**
- This process may take significant time depending on data size and system performance
- Once cached, the Zarr stores can be reused across multiple climate impact computations
- The cached data is required as input for all fleet computation examples

**Example:**
```bash
# Cache weather data
uv run examples/weather_cache.py \
  --dwd-path /path/to/dwd/icon/data \
  --zarr-path /output/weather/cache \
  --date 2025-07-09 \
  --hour 0

# Then use the cached data with fleet computations
uv run examples/fleet_computation_from_json.py \
  --json-file tests/data/golden/fleet_5_flights_input.json \
  --weather-path /output/weather/cache \
  --bada-path /path/to/bada/data \
  --njobs 2
```

## Fleet Runners

| Runner | Class | Pipeline stops after | Use case |
|---|---|---|---|
| **Large emitter** | `FleetRunnerLargeEmitter` | Climate metrics | Full climate impact (CoCiP contrails + non-CO₂) |
| **Small emitter** | `FleetRunnerSmallEmitter` | Climate metrics | OpenAirClim pipeline (no CoCiP) |
| **Performance only** | `FleetRunnerPerformanceOnly` | Performance | Fuel flow, mass, TAS only |

Key features shared by all runners:
- Per-flight error handling (continues processing even if individual flights fail)
- Configurable parallelism via joblib
- Support for both DataFrame and JSON input formats
- Automatic weather data loading from Zarr stores
