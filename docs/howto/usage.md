# Usage Guide

## Process Flights from a DataFrame

If your flight data is in a pandas DataFrame rather than JSON:

```bash
uv run python examples/fleet_computation_from_dataframe.py \
  --weather-path /path/to/weather/zarr \
  --bada-path /path/to/bada/data \
  --njobs 4
```

See [fleet_computation_from_dataframe.py](https://github.com/eurocontrol-asu/PyNeats/blob/main/examples/fleet_computation_from_dataframe.py) for the full example.

## Build a Weather Cache

Pre-cache DWD ICON weather data for faster pipeline runs:

```bash
uv run python examples/weather_cache.py \
  --dwd-path /path/to/dwd/icon/data \
  --zarr-path /path/to/output/zarr \
  --date 2025-07-09 \
  --hour 0
```

This converts DWD ICON data into an optimised Zarr store that PyNeats can load directly.

## Select Specific Flights

Filter flights by ID or airport pair using the I/O utilities:

```python
from pyneats.steps.parsing.neats_io import select_json_flights

filtered = select_json_flights(
    flights=all_flights,
    flight_id="FLIGHT001",
    adep=None,
    ades=None,
)
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

## Run Tests

```bash
# Unit tests only (no external data)
make test-unit

# Full test suite
make test BADA_PATH=/path/to/bada WEATHER_PATH=/path/to/weather

# Fast (no coverage)
make test-fast BADA_PATH=/path/to/bada
```
