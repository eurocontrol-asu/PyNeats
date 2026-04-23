# Output Format

After calling `runner.eval()`, results are available at `runner.results` as a
dict with two top-level keys:

```python
runner.results = {
    "fleet_meta_data": { ... },    # run-level metadata
    "flight_results":  [ ... ],    # one entry per flight
}
```

Reference sample: [`tests/data/golden/fleet_5_flights_output.json`](https://github.com/eurocontrol-asu/PyNeats/blob/main/tests/data/golden/fleet_5_flights_output.json).

## `fleet_meta_data`

Collected once per run by [`FleetReport.collect`](https://github.com/eurocontrol-asu/PyNeats/blob/main/src/pyneats/steps/climate_metrics/report.py). Captures
versions of all tools involved so results are reproducible:

| Field | Type | Description |
|---|---|---|
| `pyneats_version` | string | PyNeats release / git tag |
| `pycontrails_version` | string | pycontrails (CoCiP engine) version |
| `climaccf_version` | string | CLIMaCCF version (if used) |
| `pybada_version` | string | PyBADA version |
| `openairclim_version` | string | OpenAirClim version (Method D) |
| `python_version` | string | Python runtime version |

## `flight_results`

A list of dicts — one entry per flight, in the same order as the input. Each
entry is either:

- **A successful result**: a full per-segment payload (columns from all
  pipeline stages) with a nested `climate_impact` summary.
- **An error record**: `{"flight_id": ..., "error": ..., "error_type": ...}`
  for flights that failed at some step. The pipeline continues on per-flight
  failures — partial fleets remain usable.

### Successful flight entry

Top-level flight metadata (scalar fields):

| Field | Type | Description |
|---|---|---|
| `flight_id` | list[str] | Flight identifier per segment (constant) |
| `departure_airport` | string | ICAO |
| `arrival_airport` | string | ICAO |
| `model_type` | string | Parser model tag (e.g. `"NM"`) |
| `aobt` | ISO-8601 string | Actual off-block time |
| `aircraft_type` | string | ICAO type |
| `n_engine` | int | Engine count |
| `bada_version` | string | `"BADA4"` or `"BADA3"` |
| `bada_code` | string | BADA aircraft code |
| `engine_uid` | string | ICAO engine UID |
| `gaseous_data_source` | string | e.g. `"FFM2"` |
| `nvpm_data_source` | string | e.g. `"FA Model"` |
| `total_co2` / `total_h2o` / `total_nox` / ... | float | Fleet totals in kg |

Per-segment columns (all `list[float]` of equal length):

- **Trajectory**: `waypoint`, `latitude`, `longitude`, `altitude`,
  `time`, `segment_duration`, `segment_length`, `ground_speed`,
  `true_airspeed`, `rocd`, `acceleration`, `phase`, `thrust_segment`
- **Weather**: `u_wind`, `v_wind`, `air_temperature`, `specific_humidity`,
  `geopotential`, `potential_vorticity`, `air_pressure`, `level`
- **Performance**: `thrust`, `aircraft_mass`, `fuel_flow`, `fuel_burn`,
  `engine_efficiency`, `fuel_flow_per_engine`, `thrust_setting`
- **Emissions** (emission indices + mass per segment): `nox_ei`, `co_ei`,
  `hc_ei`, `nvpm_ei_m`, `nvpm_ei_n`, `co2`, `h2o`, `so2`, `sulphates`, `oc`,
  `nox`, `co`, `hc`, `nvpm_mass`, `nvpm_number`
- **Climate functions (CoCiP)**: `G`, `T_sat_liquid`, `rh`,
  `rh_critical_sac`, `sac`, `T_critical_sac`, `width`, `depth`, `rhi_1`,
  `persistent_1`, `iwc_1`, `f_surv`, `n_ice_per_m_0`, `n_ice_per_m_1`, `ef`,
  `contrail_age`, `sdr_mean`, `rsr_mean`, `olr_mean`, `rf_sw_mean`,
  `rf_lw_mean`, `rf_net_mean`, `cocip`
- **Climate functions (aCCF v1.0A)**: `ATR_20_O3`, `ATR_20_CH4`,
  `ATR_20_H2O`

### `climate_impact` (summary block)

Nested object with the final MRV-style result:

```json
{
  "flight_information": {
    "aobt": "2025-07-09T18:07:00+0000",
    "flight_id": "EAF2143",
    "departure_airport": "LZIB",
    "arrival_airport": "LBBG",
    "aircraft_type": "A320",
    "bada_version": "BADA4",
    "bada_code": "A320-214",
    "engine_uid": "1IA001",
    "model_type": "NM",
    "co2_baseline_kg": 11919.55,
    "fuel_burn_kg": 3773.20,
    "contrails_ef_J": 3.06e+11
  },
  "climate_metrics": [
    {
      "species": "CO2",
      "value": [
        { "horizon": 20,  "EAGWP_Wm2yr": 2.87e-10, "CO2eq_kg": 11919.55 },
        { "horizon": 50,  "EAGWP_Wm2yr": 5.66e-10, "CO2eq_kg": 11919.55 },
        { "horizon": 100, "EAGWP_Wm2yr": 8.85e-10, "CO2eq_kg": 11919.55 }
      ]
    },
    { "species": "Contrails", "value": [ ... ] },
    { "species": "CH4",       "value": [ ... ] },
    { "species": "O3",        "value": [ ... ] },
    { "species": "H2O",       "value": [ ... ] }
  ]
}
```

`climate_metrics` always contains one entry per species with three horizons
(20, 50, 100 years). See [explanation/mrv-specification.md](../explanation/mrv-specification.md) §3.7 for the formulas.

### Error record

When a flight fails at any step, an error record is appended to
`flight_results` instead of the full payload:

```json
{
  "flight_id": "EAF9999",
  "error": "missing required columns: ['latitude']",
  "error_type": "TrajectoryParserStepError",
  "stage": "parsing"
}
```

Low-altitude flights (never reaching the aCCF-valid cruise altitude) are
separated from "hard" errors as **zero-result** markers — they are not bugs
but legitimate out-of-scope flights.

## Consuming the output

Examples of typical access patterns:

```python
runner.eval()

# Fleet-level metadata
print(runner.results["fleet_meta_data"])

# Per-flight iteration
for flight_result in runner.results["flight_results"]:
    if "error" in flight_result:
        print(f"Failed: {flight_result['flight_id']}")
        continue

    summary = flight_result["climate_impact"]
    flight_id = summary["flight_information"]["flight_id"]
    co2eq_100 = next(
        v["CO2eq_kg"]
        for m in summary["climate_metrics"]
        if m["species"] == "CO2"
        for v in m["value"]
        if v["horizon"] == 100
    )
    print(f"{flight_id}: CO2eq(100y) = {co2eq_100:.0f} kg")
```
