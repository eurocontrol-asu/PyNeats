# Example Scripts

PyNeats does not ship a dedicated CLI. The entry points are the scripts in the
[`examples/`](https://github.com/eurocontrol-asu/PyNeats/tree/main/examples)
directory, which expose the runners via `argparse`:

| Script | Runner | Purpose |
|---|---|---|
| `fleet_computation_from_json.py` | `FleetRunnerLargeEmitter` | Process a fleet from NEATS JSON |
| `fleet_computation_from_dataframe.py` | `FleetRunnerLargeEmitter` | Process a fleet from a pandas DataFrame |
| `fleet_performance_only.py` | `FleetRunnerPerformanceOnly` | Compute fuel flow & thrust without climate metrics |
| `fleet_small_emitter.py` | `FleetRunnerSmallEmitter` | Method D (OpenAirClim) for small emitters |
| `weather_cache.py` | — | Pre-build a Zarr weather cache from DWD ICON |

Run any script with `--help` for its full argument list:

```bash
uv run python examples/fleet_computation_from_json.py --help
```

See:

- [Usage guide](../howto/usage.md) — end-to-end recipes
- [Input format](input-format.md) — JSON input schema
- [Output format](output-format.md) — `runner.results` shape
