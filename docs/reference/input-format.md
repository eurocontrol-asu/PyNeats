# JSON Input Format

PyNeats accepts a JSON array where each entry represents a single flight. The
top-level file shape is:

```json
[
  { "flight_information": { ... } },
  { "flight_information": { ... } }
]
```

Each flight is a single object with one key: `flight_information`. Reference
sample: [`tests/data/golden/fleet_5_flights_input.json`](https://github.com/eurocontrol-asu/PyNeats/blob/main/tests/data/golden/fleet_5_flights_input.json).

## `flight_information` schema

| Field | Type | Required | Description |
|---|---|---|---|
| `confidential` | string (`"true"`/`"false"`) | yes | Confidentiality flag |
| `flight_identification` | string | yes | Flight identifier (callsign / ICAO flight ID) |
| `departure_date_time` | ISO-8601 string (tz-aware) | yes | Off-block time |
| `arrival_date_time` | ISO-8601 string (tz-aware) | yes | In-block time |
| `departure_airport` | ICAO code | yes | e.g. `"LZIB"` |
| `arrival_airport` | ICAO code | yes | e.g. `"LBBG"` |
| `aircraft_properties` | object | yes | See below |
| `fuel_properties` | object | yes | See below (all fields nullable) |
| `trajectory` | object | yes | See below |

### `aircraft_properties`

| Field | Type | Required | Description |
|---|---|---|---|
| `aircraft_type` | string | yes | ICAO type, e.g. `"A320"` |

### `fuel_properties`

All fields are nullable. When `null`, the value from the airport fuel file
(below) is used if an `airport_fuel_path` is configured on the runner, otherwise
the default.

| Field | Type | Unit | Use |
|---|---|---|---|
| `hydrogen_content` | float \| null | wt.% (percent by mass, e.g. 13.79) | scales `ei_h2o` and sets the SAF nvPM reduction; default 13.79 |
| `hydrogen_per_carbon_ratio` | float \| null | atomic (molar) H/C ratio | converted to wt.% when `hydrogen_content` is `null` |
| `calorific_value` | float \| null | J/kg (lower calorific value), 35e6–50e6 | default 42.8e6; outside the range the flight fails |
| `aromatic_content` | float \| null | not defined | stored, not used |
| `sulphur` | float \| null | not defined | stored, not used |
| `naphthalene` | float \| null | not defined | not used |

The AO upload gives `calorific_value` in MJ/kg; the NEATS application multiplies
it by 1e6 before calling PyNEATS. A value still in MJ/kg (e.g. `43.05`) is
outside 35e6–50e6 J/kg, so the flight fails at parsing with a message naming
the unit.

### Airport fuel file (`airport_fuel_path`)

Optional file passed to the runners (`airport_fuel_path=`). For a flight whose
`fuel_properties` value is `null`, the value for its `departure_airport` is used.
AO values always take precedence. PyNEATS reads this file itself, so no unit
conversion is applied: values must be in the units below.

- **CSV**: separator `;` or `,` (detected), decimal comma accepted, a column
  `Airport` (ICAO code). Recognised columns: `q_fuel` (J/kg), `h_c_ratio`
  (atomic), `aromatics_content`, `naphthalene`, `sulphur_content`. Empty cells
  are ignored.
- **JSON**: `{"EGLL": 43000000.0}` (q_fuel only) or
  `{"EGLL": {"q_fuel": 43000000.0, "h_c_ratio": 1.9}}`.

Only `q_fuel` and `h_c_ratio` affect results; the other columns are stored. Every
`q_fuel` must lie between 35e6 and 50e6 J/kg: otherwise the runner refuses the
file when it is built, naming the airports. A missing or unreadable file is
ignored with a warning, and the defaults apply.

Example (the layout of `Airport_Fuel_2025.csv`):

```text
Airport;aromatics_content;h_c_ratio;naphthalene;sulphur_content;q_fuel
EKYT;0,2125;;0,0136;0,000035;43050000
```

### `trajectory`

| Field | Type | Required | Description |
|---|---|---|---|
| `trj_data_source` | string | yes | Source label, e.g. `"Actual"`, `"Planned"` |
| `trajectory_data` | array of waypoints | yes | ≥ 2 entries |

Each waypoint:

| Field | Type | Unit | Description |
|---|---|---|---|
| `ts` | ISO-8601 string (tz-aware) | — | Waypoint timestamp |
| `lat` | float | degrees | Latitude (WGS84) |
| `lon` | float | degrees | Longitude (WGS84) |
| `fl` | float | flight level | Altitude (FL = altitude in hundreds of feet) |
| `ff` | float \| null | kg/s | Fuel flow, whole aircraft (optional) |
| `ee` | float \| null | — | Engine efficiency (optional) |
| `am` | float \| null | kg | Aircraft mass (optional) |

**Empty values in the optional fields.** A field that is `null` (or absent) at
every waypoint is treated as not provided: PyNEATS computes it (BADA for fuel
flow, engine efficiency and mass). A field provided at some waypoints and `null`
at others is used, and each `null` is skipped as if that waypoint had not been
sent: PyNEATS resamples the trajectory to one point per minute and interpolates
the field linearly between the nearest waypoints that have a value. Before the
first and after the last waypoint with a value, that nearest value is used. A
gap is therefore filled by a straight line, not by BADA.

## Validation rules

PyNeats applies the following validity checks during parsing
([`NeatsTrajectoryParser`](../reference/api/pyneats/steps/parsing/neats_parser.md)):

1. **Required columns present** — any missing column in `trajectory_data`
   raises `TrajectoryParserStepError`.
2. **Minimum altitude** — trajectories that never cross the configured
   `max_pressure_level` (default cruise validity) are rejected.
3. **Maximum duration** — trajectories spanning more than **24 hours** are
   rejected as likely data errors (concatenated flights, timezone bugs).
4. **Monotonic time** — rows are sorted by timestamp and deduplicated on the
   time column.
5. **Multi-engine lists** — a list-typed `engine_uid` must be processed via
   `FleetRunner`, not `FlightRunner`.

## Example

Minimal two-waypoint flight:

```json
[
  {
    "flight_information": {
      "confidential": "false",
      "flight_identification": "EAF2143",
      "departure_date_time": "2025-07-09T18:07:00+0000",
      "arrival_date_time": "2025-07-09T19:49:32+0000",
      "departure_airport": "LZIB",
      "arrival_airport": "LBBG",
      "aircraft_properties": { "aircraft_type": "A320" },
      "fuel_properties": {
        "hydrogen_content": null,
        "hydrogen_per_carbon_ratio": null,
        "aromatic_content": null,
        "calorific_value": null
      },
      "trajectory": {
        "trj_data_source": "Actual",
        "trajectory_data": [
          { "ts": "2025-07-09T18:17:00+0000", "lat": 48.17, "lon": 17.21, "fl": 4,   "ff": null, "ee": null, "am": null },
          { "ts": "2025-07-09T19:48:00+0000", "lat": 42.69, "lon": 23.41, "fl": 10,  "ff": null, "ee": null, "am": null }
        ]
      }
    }
  }
]
```

See [`tests/data/golden/`](https://github.com/eurocontrol-asu/PyNeats/tree/main/tests/data/golden) for
complete working samples covering all optional fields (aircraft_mass column,
engine_efficiency column, aggregated mode, payload factor, q_fuel override).
