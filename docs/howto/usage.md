# Usage Guide

## Parse Trajectories

### From JSON (NEATS format)

Convert raw NEATS JSON records into a list of DataFrames ready for the pipeline:

```python
from pyneats.steps.parsing.neats_io import neats_json_to_flights

flights_df = neats_json_to_flights(flights=raw_json_list, model_type="CTFM")
```

If the same flight is spread across multiple sources (e.g. primary + secondary data), merge them with `concat_neats_flight`:

```python
from pyneats.steps.parsing.neats_io import concat_neats_flight

combined_df = concat_neats_flight(dfs=[primary_df, secondary_df])
```

Filter by flight ID or airport pair:

```python
from pyneats.steps.parsing.neats_io import select_json_flights

filtered = select_json_flights(
    flights=raw_json_list,
    flight_id="FLIGHT001",
    adep="EGLL",
    ades=None,
)
```

### From a DataFrame

If your flight data is already in a single pandas DataFrame with mixed flights, split it into per-flight DataFrames:

```python
from pyneats.steps.parsing.neats_io import split_df_into_flights

per_flight_dfs = split_df_into_flights(df=my_dataframe, attr_columns=["flight_id", "aircraft_type"])
```

Then run the fleet example:

```bash
uv run python examples/fleet_computation_from_dataframe.py \
  --weather-path /path/to/weather/zarr \
  --bada-path /path/to/bada/data \
  --njobs 4
```

See [fleet_computation_from_dataframe.py](https://github.com/eurocontrol-asu/PyNeats/blob/main/examples/fleet_computation_from_dataframe.py) for the full example.

## Build a Weather Cache

PyNeats supports two weather backends:

| Backend | Source | Class |
|---|---|---|
| **DWD ICON** | NWP model (operational) | `DWDFactory` |
| **ERA5** | Reanalysis (historical) | `ERA5Factory` |

### DWD ICON (recommended for operational use)

Pre-cache DWD ICON weather data for faster pipeline runs:

```bash
uv run python examples/weather_cache.py \
  --dwd-path /path/to/dwd/icon/data \
  --zarr-path /path/to/output/zarr \
  --date 2025-07-09 \
  --hour 0
```

This converts DWD ICON data into an optimised Zarr store that PyNeats can load directly.

To load the cache programmatically, use `get_weather_from_zarr`:

```python
from pyneats.steps.weather.weather_store import get_weather_from_zarr, ZarrPaths

weather = get_weather_from_zarr(
    zp=ZarrPaths(met_path="/path/to/met.zarr", wind_path="/path/to/wind.zarr"),
    t0="2025-07-09T00:00:00",
    t1="2025-07-09T23:59:59",
    chunks=None,
)
```

!!! tip "Cache troubleshooting"
    If you encounter stale or corrupted data, clear the in-memory dataset cache:
    ```python
    from pyneats.steps.weather.weather_store import clear_dataset_cache
    clear_dataset_cache()
    ```

## Choose a Runner

PyNeats provides different runners depending on the flight type:

| Runner | Use case |
|---|---|
| `FlightRunnerLargeEmitter` | Single large-emitter flight (Method C) |
| `FleetRunnerLargeEmitter` | Fleet of large emitters with parallelisation |
| `FlightRunnerSmallEmitter` | Single small-emitter flight (Method D) |
| `FleetRunnerSmallEmitter` | Fleet of small emitters |

```python
from pyneats.runners.large_emitter import FleetRunnerLargeEmitter

runner = FleetRunnerLargeEmitter(config=my_config)
report = runner.run(flights)
```

## Read the Output Report

Runners return a `FleetReport` (or `FlightReport` for single-flight runners):

```python
from pyneats.steps.climate_metrics.report import FlightReport, FleetReport

# Individual flight result
flight_report: FlightReport = runner.run_one(flight)

# Fleet result
fleet_report: FleetReport = runner.run(flights)

# Iterate over per-flight reports
for report in fleet_report.flight_reports:
    print(report.flight_id, report.co2_equivalent_kg)
```

The report also captures errors for flights that failed, allowing partial results to be used without crashing the entire fleet run.
