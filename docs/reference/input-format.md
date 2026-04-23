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

All four fields are nullable. When `null`, airport-level fallback values are
used if an `airport_fuel_path` is configured on the runner.

| Field | Type | Unit |
|---|---|---|
| `hydrogen_content` | float \| null | mass fraction (0–1) |
| `hydrogen_per_carbon_ratio` | float \| null | — |
| `aromatic_content` | float \| null | mass fraction (0–1) |
| `calorific_value` | float \| null | J/kg |

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
| `ff` | float \| null | kg/s | Fuel flow (optional; derived if `null`) |
| `ee` | float \| null | — | Engine efficiency (optional) |
| `am` | float \| null | kg | Aircraft mass (optional) |

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
