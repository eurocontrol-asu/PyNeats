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

The AO upload schema also allows a bare single flight object at top level.
PyNeats does not accept it: `FleetRunner` stops with a `TypeError`. Put the
flight in an array.

**Units at the PyNeats boundary.** PyNeats reads the AO upload after the NEATS
application has converted two fields: `tas` from knots to m/s (× 1852 / 3600)
and `calorific_value` from MJ/kg to J/kg (× 1e6). PyNeats does not convert
these again. The other values are used in the units of the AO upload; `fl` is
converted to metres by PyNeats (see [`trajectory`](#trajectory)).

In the tables below, **AO range** is the range of the AO upload schema.
PyNeats does not enforce it: what PyNeats checks is given in the description
of each field and in [Checks on the input](#checks-on-the-input).

The repository schema `scripts/schemas/flight_schema.json` (used to validate
the golden test inputs) is narrower than the AO upload schema and than this
page: it types `confidential` as a string, does not allow a list for
`engine_uid`, requires `arrival_date_time`, and does not list
`aircraft_version`, `ets_exemption` or `nwp_date_time`. Where the two differ,
this page describes what PyNeats reads.

## `flight_information` schema

| Field | Type | Needed by PyNeats | Description |
|---|---|---|---|
| `flight_identification` | string | yes | ICAO callsign (flight-plan Item 7). Copied to `flight_id`, which names the flight in logs, error records and outputs |
| `departure_date_time` | ISO-8601 date-time string, UTC | yes | See below |
| `arrival_date_time` | ISO-8601 date-time string, UTC | no | Not used (see below) |
| `departure_airport` | ICAO code, 4 letters | yes | e.g. `"LZIB"`. Also the key of the [airport fuel file](#airport-fuel-file-airport_fuel_path) |
| `arrival_airport` | ICAO code, 4 letters | yes | e.g. `"LBBG"` |
| `aircraft_properties` | object | yes | See below |
| `fuel_properties` | object \| null | no | See below. `null` or absent: every fuel property takes its default |
| `trajectory` | object | yes | See below |
| `confidential` | boolean \| null | no | Not read by PyNeats |
| `ets_exemption` | string \| null | no | Not read by PyNeats |
| `nwp_date_time` | ISO-8601 date-time string \| null | no | Not read by PyNeats: every flight of a run uses the weather stores given to the runner (`zarr_paths`) |

"Needed by PyNeats: yes" means that a flight without the field fails at
parsing (in `FleetRunner`, an error record; the other flights go on).

**`departure_date_time`.** The AO upload schema gives the departure date and
time of flight-plan Item 13, in UTC, which ICAO Doc 4444 defines as the
estimated off-block time (EOBT). PyNeats copies the string as given, without
parsing it, to the attribute and output field `aobt`. It is used only to
identify the flight (with `flight_identification` and the two airports) and in
the outputs: the time of each trajectory point comes from `ts`, not from this
field. Because the string is not parsed, the same instant written as `Z` and as
`+0000` gives two different flight keys.

**`arrival_date_time`.** Not used: PyNeats drops it when it reads the flight.
In NM trajectories it equals the time of the last trajectory point (see
[Ground points and taxi](#ground-points-and-taxi)).

### `aircraft_properties`

| Field | Type | Unit | AO range | Needed by PyNeats |
|---|---|---|---|---|
| `aircraft_type` | string | — | ICAO type designator, 2–4 characters | yes |
| `aircraft_version` | string \| null | — | 2 or more of `A`–`Z`, `0`–`9`, space, `_`, `-` | no |
| `engine_uid` | string \| list of strings \| null | — | at most 4 in a list | no |
| `takeoff_mass` | float \| null | kg | ≥ 1 | no |
| `load_factor` | float \| null | dimensionless fraction | 0–1 | no |

**`aircraft_type`** is the ICAO aircraft type designator (flight-plan Item 9),
e.g. `"A320"`. A flight without it fails at parsing. PyNeats looks it up,
upper-cased, in the BADA mapping tables, together with `aircraft_version` and
`engine_uid` (see [BADA Type Mapping](../explanation/input-prioritization.md#bada-type-mapping)).
A type that is not in the mapping makes the flight fail, also when the AO
provides fuel flow, engine efficiency and aircraft mass. The emissions step
receives the type as given. To see, without running a flight, which BADA model
and which engine a type gets, use
[`resolve_aircraft`](../howto/usage.md#check-the-bada-model-and-engine-of-an-aircraft).

**`aircraft_version`** is the version of the aircraft, for a type designator
used for several versions, e.g. `"A320-214"`. PyNeats stores it as
`aircraft_series` and uses it only to choose the BADA mapping row: it removes
every character that is not a letter or a digit, upper-cases the rest, and
looks up (type, version, engine), then (type, version), before the rows
without a version. A version that is not in the tables is not an error: the
look-up goes on with the next key. When `null`, the rows with a version are
skipped.

**`engine_uid`** is the engine unique identifier (UID) of the ICAO Aircraft
Engine Emissions Databank (EDB), e.g. `"3CM026"`; it is not an engine name.
PyNeats strips and upper-cases it and uses it twice:

- as a key of the BADA mapping: the (type, version, engine) and (type, engine)
  rows;
- for the emissions: pycontrails takes the EDB data of this UID for the NOx,
  CO, HC and nvPM emission indices.

When `engine_uid` is `null` or absent, the emissions use the MRR conservative
engine of the type (`MRR_conservative_mapping.csv`), or, for a type that is not
in that file, the engine of the BADA mapping row. The engine of the BADA model
can differ from the engine used for the emissions;
[`resolve_aircraft`](../howto/usage.md#check-the-bada-model-and-engine-of-an-aircraft)
shows both, with the source of the emissions engine.

PyNeats does not check the UID against the EDB and logs nothing about it. For
a UID that is not in the EDB, pycontrails uses constant emission indices for
NOx, CO, HC and nvPM mass and number, and emits a Python `UserWarning`
("Cannot find 'engine_uid' … in EDB"); this warning does not go through the
PyNeats log.

A list (at most 4 UIDs in the AO upload schema) is accepted by `FleetRunner`
only, in the JSON input and in a `trajectory_dataframe`. Each UID of the list
is run as a separate copy of the whole flight, and the copies are averaged into
one result (see [Output Format](output-format.md), "Multi-engine flights"). An
empty list gives an error record. `FlightRunner` rejects a list at parsing.

**`takeoff_mass`** is the take-off mass in kg: the aircraft mass at the
beginning of the take-off run, including everything and everyone carried at
that moment (MRR Annex IIIa §1(29)). PyNeats stores it as `takeoff_weight`,
and the output `takeoff_weight` shows the AO value.

- **Use.** It is the mass at the first point of the trajectory used: the
  first point of the 60 s resampled trajectory, or, when the retry without the
  points below FL20 is used, the first point at or above FL20. From there the
  mass decreases with the AO fuel flow if provided, else with the BADA fuel
  flow (see [Input Prioritization](../explanation/input-prioritization.md)).
- **Priority.** When the AO gives aircraft mass (`am`), `takeoff_mass` is not
  used. When the two differ by more than 1,000 kg or 2 % of the first aircraft
  mass, whichever is larger, one warning per flight names the flight and both
  masses; a smaller difference is logged at debug level only.
- **Check.** A value below the BADA OEW or above 1.05 × the BADA MTOW of the
  aircraft type fails the flight, with or without aircraft mass, and without a
  retry with BADA 3. The bounds are those of the first BADA model that loads
  (the model of the mapping row: BADA 4, or BADA 3 when the row has no BADA 4
  model; BADA 3 when that model cannot be loaded) and are included. The error names the flight, the value, the bound and the BADA
  model. A value in tonnes is caught this way, and most values in pounds.
- **Missing.** When `null`, no check is made, and the mass is estimated from
  `load_factor` (see
  [Mass Estimation](../explanation/input-prioritization.md#mass-estimation)).

**`load_factor`** is payload mass / maximum payload mass, a fraction from 0 (no
payload, e.g. a ferry flight) to 1 (full payload) (MRR Annex IIIa §1(32)); it is
not a seat load factor. The maximum payload is the BADA MPL, or MTOW − OEW when
the BADA file gives none. PyNeats stores it as `payload_factor`.

- **Use.** Only when the AO gives neither aircraft mass nor take-off mass: the
  take-off mass is then estimated as
  min(MTOW, OEW + `load_factor` × MPL + 1.15 × trip fuel) (see
  [Mass Estimation](../explanation/input-prioritization.md#mass-estimation)).
- **Check.** A value above 1 is set to 1.0 with a warning that names the flight
  and the value; it is not divided by 100, so a percentage such as 80 becomes
  1.0. A negative value, or a value that cannot be read as a number, fails the
  flight at parsing (a numeric string such as `"0.5"` is read as 0.5).
- **Missing.** When `null`, the default 1 (full payload) is used.

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
the unit. The value is the lower calorific value of the fuel (MRR Annex IIIa
§1(38)); PyNeats uses it to rescale the BADA fuel flow, but not an AO fuel flow
(see [Additional Parameters](../explanation/mrv-specification.md#additional-parameters)).

`hydrogen_content` is the hydrogen mass content in percent (13.79 means
13.79 %), not a 0–1 fraction. `ei_h2o` is the Jet A value × `hydrogen_content` /
13.8. PyNeats does not check its range: a fraction such as `0.1379` is read as
0.1379 wt.% and gives an `ei_h2o` 100 times too small, without an error.

`hydrogen_per_carbon_ratio` is the number of hydrogen atoms per carbon atom
(MRR Annex IIIa §1(36)), about 1.9–2.2 for Jet A. It is used only when
`hydrogen_content` is `null`, converted to wt.% as
100 × r × 1.008 / (12.011 + r × 1.008). Its range is not checked either.

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
| `trj_data_source` | string | no | `"Actual"` or `"Planned"` in the AO upload schema. Not read by PyNeats |
| `trajectory_data` | array of waypoints | yes | See below |

The AO upload schema asks for the points in ascending time, with at least one
point every 60 seconds. PyNeats does not rely on either: it sorts the points by
time, drops a point whose `ts`, `lat`, `lon` or `fl` is missing, keeps the
first point (in input order) of the points that have the same time, and
resamples the trajectory to one point per minute. A flight with no point left
fails at parsing; so does a flight whose `trajectory` is `null`.

Each waypoint:

| Field | Type | Unit | AO range | Description |
|---|---|---|---|---|
| `ts` | ISO-8601 date-time string | — | — | Waypoint timestamp, UTC (see below) |
| `lat` | float | degrees | −90 to 90 | Latitude (WGS84) |
| `lon` | float | degrees | −180 to 180 | Longitude (WGS84) |
| `fl` | number (integer in the AO upload) | flight level (hundreds of feet) | ≥ −20 | Pressure altitude, e.g. 342 is 34,200 ft |
| `tas` | float \| null | m/s (knots in the AO upload) | ≥ 0 | True airspeed (optional) |
| `ff` | float \| null | kg/s | ≥ 0 | Fuel flow, whole aircraft (optional) |
| `ee` | float \| null | dimensionless fraction | 0–1 | Overall propulsion efficiency (optional) |
| `am` | float \| null | kg | ≥ 0 | Aircraft mass (optional) |

PyNeats does not check the ranges of `lat`, `lon`, `fl`, `tas`, `ff`, `ee` and
`am` point by point; the checks that apply to the flight are given below and in
[Checks on the input](#checks-on-the-input).

**`ts`.** A UTC offset is applied (`"2025-11-02T12:02:00+02:00"` is 10:02 UTC);
a time without offset is read as UTC. Fractional seconds are cut to whole
seconds, so of the points within the same second only the first in input
order is kept. A `ts` that is not a
valid date-time fails the flight, with a message naming the flight and the
point.

**`fl`** is a flight level: pressure altitude in hundreds of feet in the
International Standard Atmosphere. PyNeats converts it to metres as
FL × 30.48 m; it is never read as a geometric altitude, or as an altitude in
feet or metres.

**`tas`** is the true airspeed. The AO upload gives it in knots, and the NEATS
application converts it to m/s before calling PyNeats. When provided, it is
used instead of the true airspeed PyNeats computes from the ground speed and
the wind. Provided or computed, each point is checked, and an implausible
true airspeed is replaced (see "Untrusted airspeeds" in
[Input Prioritization](../explanation/input-prioritization.md#performance-input-decision-tree)).
PyNeats does not check the unit: a value left in knots reads 1.94 times too
fast. Such points are mostly above the BADA maximum operating speed or Mach 1,
so they are replaced as untrusted, and a flight with more than 80 % of its time
untrusted fails (not when the AO provides fuel flow, engine efficiency and
aircraft mass). Slow points, for example near the airports, can stay below
those limits and are then used as sent.

**`ff`** is the fuel flow in kg/s for the whole aircraft: the fuel mass that
passes into all the engines per second (MRR Annex IIIa §1(33)), not the flow of
one engine. It is used as given, without the rescaling applied to the BADA fuel
flow, for the fuel burn, the CO2 and the other emissions; pycontrails divides it
by the number of engines where it needs the flow per engine. When the AO gives
`ff` but no `am`, the aircraft mass decreases along the trajectory with the AO
fuel flow, so the mass decrease equals the reported fuel burn. The fuel-burn
plausibility check (total fuel burn at most 1.2 × (MTOW − OEW)) runs on the AO
fuel flow. A flight it rejects fails without retries when the AO gives no `am`,
or gives `ee` and `am` as well (every retry would use the same AO fuel flow);
with `am` and no `ee` the retries still run. A fuel flow sent in kg/h is caught
this way. A fuel flow per engine, or in g/s, is too small and is
not caught. See [Input Prioritization](../explanation/input-prioritization.md).

**`ee`** is the overall propulsion efficiency: thrust × true airspeed /
(fuel flow × lower calorific value), a fraction (MRR Annex IIIa §1(34); the
regulation words it as a percentage, the AO upload schema as a value from 0 to
1). It is used in the contrail formation criterion (Schmidt–Appleman), whose
mixing-line slope is proportional to 1 / (1 − `ee`). AO values are used as
given: they are not clipped and not range-checked. When `ee` is not provided,
PyNeats computes it from BADA thrust and BADA fuel flow and clips it to
0–0.5; the AO values are not clipped to that range.

**`am`** is the aircraft mass in kg along the trajectory: the take-off mass
minus the fuel burnt so far (MRR Annex IIIa §1(28)). When provided, it is used
point by point and wins over `takeoff_mass` (see above). Without `ff`, the fuel
flow is derived from the decrease of `am` from each point to the next (see
"Mass decrease" in [Input Prioritization](../explanation/input-prioritization.md)).
Its range is not checked; the fuel-burn plausibility check applies to the fuel
flow derived from it.

**Empty values in the optional fields.** A field that is `null` (or absent) at
every waypoint is treated as not provided: PyNEATS computes it as when the field
is absent (BADA, or fuel flow from the mass decrease when `am` is given). A field provided at some waypoints and `null`
at others is used, and each `null` is skipped as if that waypoint had not been
sent: PyNEATS resamples the trajectory to one point per minute and interpolates
the field linearly between the nearest waypoints that have a value. Before the
first and after the last waypoint with a value, that nearest value is used. A
gap is therefore filled by a straight line, not by BADA.

### Ground points and taxi

!!! note "NM trajectories start at take-off and end at landing"
    NM trajectories have no ground or taxi points. On a sample of 4,959 NM
    flights:

    - the first point is the reference point of the departure airport, stamped
      with the take-off time: it lies within 1 NM of the airport reference
      point in 98.7 % of the flights. It comes a median 10 minutes after
      `departure_date_time` (5–95 %: 5–22 minutes): the time before take-off
      (taxi-out, and any delay, since `departure_date_time` is the EOBT) is
      not in the trajectory;
    - the time of the last point equals `arrival_date_time` in every flight.
      This point is the landing, not the arrival at the gate: the taxi-in is
      not in the trajectory either.

    PyNeats removes no point for being a ground or taxi point, and it adds
    none. The points it drops are listed in
    [Checks on the input](#checks-on-the-input); the retry without the points
    below FL20 also removes the first point. In a few NM flights (24 of the
    sample) the first points (2 to 18 of them) have the same time; PyNeats
    then keeps only point 0.
    Taxi fuel is therefore not included in the fuel burn, CO2 and emissions.
    An AO `takeoff_mass` is applied at the first point of the trajectory used,
    whatever that point is; for NM data, the take-off.

## Checks on the input

The table lists what PyNeats checks on the input fields, and what happens
when a check fails. "Fails" means that the flight
gets no result: `FleetRunner` gives it an error record and goes on with the
other flights, `FlightRunner` raises.

| Check | Step | Result |
|---|---|---|
| Top level is a bare single object | reading the JSON file | `FleetRunner` stops with a `TypeError` |
| `ts` not a valid date-time | reading the JSON file | fails |
| `flight_identification`, `departure_date_time`, `departure_airport`, `arrival_airport` or `aircraft_type` missing | parsing | fails |
| No point with all of `ts`, `lat`, `lon` and `fl` (or `trajectory` is `null`) | parsing | fails |
| Points with a missing `ts`, `lat`, `lon` or `fl`; points with the same time | parsing | dropped (of the points with the same time, the first in input order is kept) |
| Trajectory spans more than 24 hours | parsing | fails (likely concatenated flights or a time zone error) |
| `load_factor` above 1 | parsing | set to 1.0, with a warning |
| `load_factor` negative or not readable as a number | parsing | fails |
| `engine_uid` is a list | parsing | fails in `FlightRunner`; `FleetRunner` runs one copy per engine (an empty list gives an error record) |
| `calorific_value` outside 35e6–50e6 J/kg | parsing | fails |
| Trajectory never reaches the pressure level `max_pressure_level` (default 550 hPa, about FL160) | parsing | no climate calculation: in `FleetRunner` a low-altitude zero result (see [Output Format](output-format.md)); in `FlightRunner` the flight fails |
| `aircraft_type` not in the BADA mapping | performance | fails |
| `takeoff_mass` below OEW or above 1.05 × MTOW | performance | fails, without the BADA 3 and FL20 retries |
| `takeoff_mass` differs from the first `am` by more than max(1,000 kg, 2 %) | performance | warning; `am` is used |
| Untrusted true airspeed (provided or computed) | performance | replaced; the flight fails when more than 80 % of its time is untrusted or no point is trusted, except when the AO provides fuel flow, engine efficiency and aircraft mass |
| Total fuel burn above 1.2 × (MTOW − OEW) | performance | rejected; retried with BADA 3 and without the points below FL20, except when the AO provides fuel flow without aircraft mass, or fuel flow, engine efficiency and aircraft mass: the flight then fails at once |

When the first BADA attempt and the BADA 3 retry both fail and the failure is
not final, PyNeats retries once without the points below FL20 (all of them, not
only the first ones). The performance checks are described in
[Input Prioritization](../explanation/input-prioritization.md). Not checked:
`hydrogen_content`, `hydrogen_per_carbon_ratio`, `engine_uid` against the EDB
(pycontrails only emits a `UserWarning`),
the unit of `tas`, the range of `ee` and `am`, and the ranges of `lat`, `lon`
and `fl`. The parsing checks are done by
[`NeatsTrajectoryParser`](../reference/api/pyneats/steps/parsing/neats_parser.md).

## Example

Minimal flight. The trajectory must reach cruise levels: a flight that stays
below about FL160 gets no climate calculation (see above).

```json
[
  {
    "flight_information": {
      "flight_identification": "EAF2143",
      "departure_date_time": "2025-07-09T18:07:00+0000",
      "arrival_date_time": "2025-07-09T19:48:00+0000",
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
          { "ts": "2025-07-09T18:40:00+0000", "lat": 46.50, "lon": 19.80, "fl": 360, "ff": null, "ee": null, "am": null },
          { "ts": "2025-07-09T19:20:00+0000", "lat": 43.90, "lon": 22.40, "fl": 360, "ff": null, "ee": null, "am": null },
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
