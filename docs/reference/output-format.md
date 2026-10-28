# Output Format

After calling `runner.eval()` on a fleet runner (`FleetRunnerLargeEmitter`,
`FleetRunnerSmallEmitter`), results are available at `runner.results` as a
dict with two top-level keys:

```python
runner.results["fleet_meta_data"]   # dict: run-level metadata (tool versions)
runner.results["flight_results"]    # list[dict]: one entry per input flight (a multi-engine flight can give more)
```

`FleetRunnerPerformanceOnly` uses the same two keys with other entries (see
[Performance-only runner](#performance-only-runner)). The single-flight runners
(`FlightRunnerLargeEmitter`, `FlightRunnerSmallEmitter`) have no `results`
attribute: after `eval()`, the payload of a successful entry is in
`runner.flight_with_climate_impact.attrs["climate_impact"]`.

## `fleet_meta_data`

Collected once per run by [`FleetReport.collect`](https://github.com/eurocontrol-asu/PyNeats/blob/main/src/pyneats/steps/climate_metrics/report.py):

| Field | Type | Description |
|---|---|---|
| `pyneats_version` | string | PyNeats version (`pyneats.__version__`) |
| `pycontrails_version` | string | Installed pycontrails version (`"unknown"` if not found) |
| `openairclim_version` | string | Installed OpenAirClim version (`"unknown"` if not found) |
| `bada4_version` | string | `"4.2.1"`, fixed in the code: the default `bada4_version` of the performance step, that is the `bada_path` sub-directory read for BADA 4. Not read from the BADA files, and not updated when you set `params["performance"]["bada4_version"]` |
| `bada3_version` | string | `"3.16"`, fixed in the code: the default `bada3_version` of the performance step, that is the `bada_path` sub-directory read for BADA 3. Not read from the BADA files, and not updated when you set `params["performance"]["bada3_version"]` |
| `pybada_version` | string | Installed pyBADA version (`"unknown"` if not found) |

## `flight_results`

A list of dicts, one entry per input flight (a multi-engine flight can give
more, see **Multi-engine flights** below). There are three kinds of entry:

| Kind | How to recognise it |
|---|---|
| Successful result | no `"error"` key, and no `low_altitude_flight` in `flight_information` |
| Low-altitude zero result | `flight_information["low_altitude_flight"]` is `True` |
| Error record | has an `"error"` key |

Successful results come first, then low-altitude zero results, then error
records. The list is therefore not in input order: match entries on
`flight_information["flight_id"]` (with the airports and `aobt` when a flight
ID is not unique). The pipeline continues on per-flight failures, so partial
fleets remain usable. A failure that is not tied to one flight is not caught,
for example when loading the weather fails, or when the fleet-level weather
intersection or CoCiP evaluation raises for the whole fleet: `eval()` then
raises and `runner.results` stays `None`.

### Successful result

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
    "co2_baseline_kg": 11957.04,
    "fuel_burn_kg": 3785.07,
    "contrails_ef_J": 3.06e+11
  },
  "climate_metrics": [
    {
      "species": "CO2",
      "value": [
        { "horizon": 20,  "EAGWP_Wm2yr": 2.88e-10, "CO2eq_kg": 11957.04 },
        { "horizon": 50,  "EAGWP_Wm2yr": 5.68e-10, "CO2eq_kg": 11957.04 },
        { "horizon": 100, "EAGWP_Wm2yr": 8.88e-10, "CO2eq_kg": 11957.04 }
      ]
    },
    { "species": "Contrails", "value": [ ... ] },
    { "species": "CH4",       "value": [ ... ] },
    { "species": "O3",        "value": [ ... ] },
    { "species": "H2O",       "value": [ ... ] }
  ]
}
```

`flight_information` fields. A field whose value is unknown (`None`) is left
out, not set to `null`:

| Field | Type | Description |
|---|---|---|
| `flight_id` | string | Flight identifier (`flight_identification` in the input) |
| `departure_airport` | string | ICAO code |
| `arrival_airport` | string | ICAO code |
| `aobt` | string (JSON input) | Departure time as supplied in `departure_date_time` (the AO upload schema gives the flight-plan EOBT), copied verbatim; not parsed. With `trajectory_dataframe`, the value of its `aobt` column, unchanged (e.g. a pandas `Timestamp` in `examples/fleet_computation_from_dataframe.py`) |
| `model_type` | string | Model tag of the trajectory: `"NM"` when the fleet runner reads a JSON file (the default of `neats_json_to_flights`); with `trajectory_dataframe`, the value of its `model_type` column (e.g. `"CTFM"` for a DataFrame built with `concat_neats_flight(neats_json_to_flights(..., model_type="CTFM"))`) |
| `aircraft_type` | string | ICAO aircraft type |
| `aircraft_series` | string | `aircraft_version` as supplied; only when the input has it |
| `engine_uid` | string, or list of strings | Engine UID used: the declared one (stripped and upper-cased), else the one chosen from the BADA mapping. A list when the input gives a list of engines (see below) |
| `bada_version` | string | `"BADA4"` or `"BADA3"`. **Absent** when the AO provides fuel flow, engine efficiency and aircraft mass (each with at least one value), because the BADA performance model is then not run. BADA still gives the engine count, the wingspan and the airspeed limits |
| `bada_code` | string | BADA aircraft code. **Absent** in the same case as `bada_version` |
| `co2_baseline_kg` | float | Flight total CO2, kg |
| `fuel_burn_kg` | float | Flight total fuel burn, kg (sum of the per-segment fuel burn, empty values skipped) |
| `contrails_ef_J` | float | Large emitters (Method C): total contrail energy forcing from CoCiP, J. Small emitters (Method D): the 20-year contrail AGWP from OpenAirClim, without efficacy, in W m⁻² yr (not J) |

`climate_metrics` is a list with one entry per species. Each entry has three
horizons (20, 50 and 100 years), each with:

- `horizon`: years;
- `EAGWP_Wm2yr`: efficacy-adjusted absolute global warming potential, W m⁻² yr;
- `CO2eq_kg`: CO2-equivalent, kg. For CO2 it is the flight total CO2
  (`co2_baseline_kg`) at every horizon.

The `CH4` entry is CH4 including primary-mode ozone (PMO). PMO is computed
separately, with its own efficacy and conversion factors, and added to the CH4
values; there is no separate `PMO` entry.

The species and their order depend on the method:

- Large emitters (Method C): `CO2`, `Contrails`, `CH4`, `O3`, `H2O`. A flight
  whose aCCF calculation fails, or gives no ATR column, fails at the
  `non_co2_model` step and gives an error record.
- Small emitters (Method D): `CO2`, `CH4`, `O3`, `H2O`, `Contrails`. A flight
  whose OpenAirClim output has no contrail value fails at the
  `integrated_non_co2` step and gives an error record.

See [explanation/mrv-specification.md](../explanation/mrv-specification.md) §3.7 for the formulas.

**Multi-engine flights.** When `engine_uid` in the JSON input
(`trajectory_json_filepath`) is a list, each engine is run as a separate copy
of the flight. The copies are averaged into one result after the emission step, and `engine_uid` lists the engines of the
averaged copies. A copy that fails before the averaging gives its own error
record, with `flight_id` `"<flight_id>__eng<i>"` and the `engine_uid` of that
copy; the result then averages the copies that succeeded, and its
`engine_uid` does not list the failed engine. A flight that fails while the
JSON file is read is not yet split, so it gives one error record with its own
`flight_id` and the list of engines as `engine_uid`. A low-altitude multi-engine flight gives
one low-altitude zero result per copy, also with `flight_id`
`"<flight_id>__eng<i>"` and the `engine_uid` of that copy. `bada_version` and
`bada_code` of the averaged result are those of one copy. A multi-engine
flight can therefore have more than one entry in `flight_results`.
With `trajectory_dataframe`, a list of two or more engines is not supported:
`split_df_into_flights` raises `ValueError`, so `eval()` raises.

### Low-altitude zero result

A flight that never reaches the parser's `max_pressure_level` (default
550 hPa, about FL160) is rejected at parsing and returned as a zero result,
not as an error:

```json
{
  "flight_information": {
    "flight_id": "LOW1",
    "departure_airport": "LZIB",
    "arrival_airport": "LBBG",
    "aobt": "2025-07-09T18:07:00+0000",
    "aircraft_type": "A320",
    "engine_uid": "UNKNOWN",
    "low_altitude_flight": true,
    "co2_baseline_kg": NaN,
    "fuel_burn_kg": NaN,
    "contrails_ef_J": 0.0
  },
  "climate_metrics": [
    {
      "species": "CO2",
      "value": [
        { "horizon": 20,  "EAGWP_Wm2yr": 0.0, "CO2eq_kg": 0.0 },
        { "horizon": 50,  "EAGWP_Wm2yr": 0.0, "CO2eq_kg": 0.0 },
        { "horizon": 100, "EAGWP_Wm2yr": 0.0, "CO2eq_kg": 0.0 }
      ]
    },
    { "species": "CH4",       "value": [ ... ] },
    { "species": "O3",        "value": [ ... ] },
    { "species": "H2O",       "value": [ ... ] },
    { "species": "Contrails", "value": [ ... ] }
  ]
}
```

`flight_information` has the six fields of an error record (below), plus
`low_altitude_flight: true`, `co2_baseline_kg` and `fuel_burn_kg` (NaN, not
computed) and `contrails_ef_J` (0.0). `json.dumps` writes the NaN values as
`NaN`, which strict JSON parsers reject; replace them (for example with
`null`) before you send the results to such a parser. Every metric is 0.0. The species are
always `CO2`, `CH4`, `O3`, `H2O`, `Contrails`, in that order, for both methods.

### Error record

When a flight fails at any step, an error record is added instead of a result:

```json
{
  "flight_information": {
    "flight_id": "BADTS",
    "departure_airport": "LZIB",
    "arrival_airport": "LBBG",
    "aobt": "2025-07-09T18:07:00+0000",
    "aircraft_type": "A320",
    "engine_uid": "UNKNOWN"
  },
  "error": "Failed at parsing: ValueError(\"flight 'BADTS', trajectory point 0: ts 'not-a-time' is not a valid RFC 3339 date-time (...)\")"
}
```

- `flight_information` always has these six fields. A field the flight does
  not have is `"UNKNOWN"`. A flight that could not be read from the JSON and
  has no `flight_identification` gets the flight ID `input_flight_<index>`.
- `error` is `"Failed at <step>: <message>"`. `<step>` is the step name:
  `parsing`, `interpolation`, `weather intersection`, `humidity scaling`
  (only when `humidity_scaling` is set), `performance`, `emissions`,
  `CoCiP evaluation` and `non_co2_model` (large emitters),
  `integrated_non_co2` (small emitters), or `climate_impact`. `<message>` is usually the
  `repr()` of the exception.

## Consuming the output

```python
runner.eval()

# Fleet-level metadata
print(runner.results["fleet_meta_data"])

# Per-flight iteration
for entry in runner.results["flight_results"]:
    info = entry["flight_information"]

    if "error" in entry:
        print(f"{info['flight_id']}: failed: {entry['error']}")
        continue

    if info.get("low_altitude_flight"):
        print(f"{info['flight_id']}: low-altitude flight, zero result")
        continue

    # CO2eq at the 100-year horizon, per species [kg]
    co2eq_100 = {
        m["species"]: v["CO2eq_kg"]
        for m in entry["climate_metrics"]
        for v in m["value"]
        if v["horizon"] == 100
    }
    print(f"{info['flight_id']}: fuel {info['fuel_burn_kg']:.0f} kg, "
          f"CO2eq(100 y) by species {co2eq_100}")
```

`runner.results_as_dataframe()` returns one row per entry of `flight_results`:
the `flight_information` fields (including `low_altitude_flight` for
low-altitude zero results), an `error` column for error records, and the
metrics as `<species>_<horizon>_EAGWP_Wm2yr` and `<species>_<horizon>_CO2eq_kg`
columns.

## Performance-only runner

`FleetRunnerPerformanceOnly` stops after the performance step. Each successful
entry is (`flight_information` holds only the fields the flight has):

```json
{
  "flight_information": {
    "flight_id": "...", "departure_airport": "...", "arrival_airport": "...",
    "aobt": "...", "aircraft_type": "...", "engine_uid": "..."
  },
  "performance": {
    "timestamps": ["2025-07-09T18:17:00", ...],
    "fuel_flow": [...],
    "aircraft_mass": [...],
    "true_airspeed": [...],
    "engine_efficiency": [...]
  }
}
```

Units: `timestamps` are the times of the resampled trajectory points (60 s
apart by default), ISO 8601 in UTC, without an offset; `fuel_flow` kg/s
(whole aircraft); `aircraft_mass` kg; `true_airspeed` m/s;
`engine_efficiency` dimensionless fraction. Empty values are `None`. Error
records follow the successful entries; low-altitude flights are ordinary error
records here, and each engine copy of a multi-engine flight gives its own
entry (`flight_id` `"<flight_id>__eng<i>"`).

## Golden dump (`FlightView.to_dict`)

The golden test files (for example
[`tests/data/golden/fleet_5_flights_output.json`](https://github.com/eurocontrol-asu/PyNeats/blob/main/tests/data/golden/fleet_5_flights_output.json))
are **not** `runner.results`. `scripts/create_golden_outputs.py` writes
`[flight.to_dict() for flight in runner.fleet_with_climate_impact]` for a
`FleetRunnerLargeEmitter` run: one dict per successful flight, with the flight
attributes and the per-segment columns merged (a column wins over an attribute
with the same name). Low-altitude flights and errors are not in it.

Flight-level fields include those of `flight_information` above except
`co2_baseline_kg`, `fuel_burn_kg` and `contrails_ef_J` (these are only in the
nested `climate_impact`), the input attributes the flight has (e.g.
`takeoff_weight`, `payload_factor`, `q_fuel`, `hydrogen_content`), plus
`n_engine`, `gaseous_data_source` (e.g. `"FFM2"`), `nvpm_data_source`
(e.g. `"FA Model"`), the flight totals `total_co2`, `total_h2o`, `total_nox`,
... (kg; `total_nvpm_number` is a number of particles), and the nested
`climate_impact` (the successful result above). `flight_id` and `wingspan` are
per-segment columns in the dump.

Per-segment columns (lists of equal length) include the following; `thrust`,
`phase` and `thrust_segment` are absent when the AO provides fuel flow, engine
efficiency and aircraft mass:

- **Trajectory**: `waypoint`, `latitude`, `longitude`, `altitude` (m),
  `time` (integer seconds since the Unix epoch), `segment_duration`,
  `segment_length`, `ground_speed`, `true_airspeed`, `rocd`, `acceleration`,
  `phase`, `thrust_segment`.
  `true_airspeed` (m/s) is the value used by the performance, emission and
  contrail calculations: an untrusted true airspeed, provided or computed, is
  replaced before BADA is run (see
  [Input Prioritization](../explanation/input-prioritization.md)). When
  PyNeats computes the true airspeed (no AO `tas`), its last point is the
  value of the point before it, not empty; so are the BADA `fuel_flow` and
  `engine_efficiency` there, except when the fuel flow is derived from the
  aircraft mass (then `fuel_flow` is empty, NaN, at the last point).
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
  `ATR_20_H2O`, and `ATR_20_PMO` when PMO is on (default). `ATR_20_CH4`
  excludes PMO; `ATR_20_PMO` = 0.29 x `ATR_20_CH4`. Both are added into the
  `CH4` climate-metrics entry.
