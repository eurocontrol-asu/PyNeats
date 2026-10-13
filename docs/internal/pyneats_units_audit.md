# PyNEATS unit audit against the AO upload schema

Reviewed revision: `f7502fe6344e5e085df1042ac817f02a05bd100d` (`origin/main`, 2026-10-13),
on branch `docs/units-audit`. Every `file:line` reference below points to that revision,
before the comment patch was applied. The patch moves lines in the files it touches.

## 1. Outcome

- **Two known interface differences.** `tas` (knots in the AO JSON, m/s in PyNEATS) and
  `calorific_value` (MJ/kg in the AO JSON, J/kg in PyNEATS) are handled by the NEATS
  application before PyNEATS is called. The task owner confirmed this. The application source
  was not available, so the conversions were not seen in code. PyNEATS consumes both values
  in the units it expects: m/s and J/kg. No PyNEATS code converts either value again, and none
  contradicts the confirmed conventions.
- **Most AO fields map consistently.** Latitude and longitude, flight level, take-off mass,
  per-point aircraft mass and hydrogen content carry the same unit and convention at the
  PyNEATS boundary as in the AO schema. Flight level becomes metres of ISA pressure altitude.
  Hydrogen content is a weight percentage.
- **Additional discrepancies were found in the inspected scope.** The ones on the AO input
  path are listed in Section 7:
  - Non-UTC offsets in trajectory timestamps are silently discarded rather than applied.
  - Some schema-valid timestamp forms, and a bare single-flight object, abort the run.
  - Fuel flow derived from `am` is shifted by one sample.
  - Partially null optional columns are not filled.

  Inside PyNEATS, away from the AO fields, the audit found unit errors with large numerical
  effects (Section 7):
  - The default local aCCF H2O formula receives potential vorticity in SI units, but its
    coefficients are defined for PVU. The H2O term loses all sensitivity to the weather, and
    H2O ATR is underestimated 1.6–3.3 times per flight.
  - The small-emitter output `contrails_ef_J` contains an AGWP in W m-2 yr, not joules.
  - OpenAirClim is told the NOx species is NO, while the NOx PyNEATS supplies is
    NO2-equivalent. Method D O3 and CH4 are then about 53 % too high.
  - The shipped OpenAirClim configuration pins the metric start year to 2025.
- **Most conventions the AO schema leaves undefined are defined in EU law** (Section 6.0).
  Implementing Regulation (EU) 2024/2493 added Annex IIIa to the MRR (2018/2066). Its
  definitions settle the following, and PyNEATS already follows each of them:
  - `ff` is whole-aircraft fuel flow, kg/s (§1(33));
  - `ee` is the overall propulsion efficiency (§1(34) and Commission guidance v2.1);
  - `load_factor` is payload mass ÷ maximum payload mass (§1(32));
  - `hydrogen_per_carbon_ratio` is atomic (§1(36));
  - `takeoff_mass` is the mass at the beginning of the take-off run (§1(29));
  - `calorific_value` is the net (lower) calorific value (§1(38));
  - `hydrogen_content` is a mass percentage (Commission guidance, Table 3).
- **Still open**, and no public source settles them (Section 6.0):
  - the numeric scale of `aromatic_content`, `sulphur` and `naphthalene`. Their basis is set
    by law (aromatics and naphthalene by volume, sulphur by mass), but not whether to send
    25 or 0.25;
  - `ee` is a "percentage" in the law but a 0–1 fraction in the schema;
  - EOBT versus AOBT: ICAO Item 13 is the EOBT, while PyNEATS labels the value AOBT;
  - who chooses the NWP run for `nwp_date_time`;
  - the MRR defines `tas` in m/s, while the AO schema uses knots. The upstream conversion
    is right for uploads that follow the schema.
- **Computational behaviour is unchanged.** The patch adds and corrects comments and
  docstrings only. An AST comparison confirms that no code changed (Section 11).

## 2. Scope, material and method

**Reference schema.** `ao_data_json_schema_supporting_arrays (4).json`, supplied as
`/data/rdcodina/pyneats/ao_data_json_schema_supporting_arrays (4) (1).json`. At top level it
accepts either one flight object or an array of flight objects. Paths below are relative to
`flight_information`.

**Unavailable material.**
- The companion schema `ao_data_json_schema.json` was not supplied and is not in the
  repository. It is not published either: the Commission guidance (v2.1, §3.3) places the
  data-reporting templates on the NEATS User Group SharePoint, which requires a login. The two
  schemas have **not** been compared.
- `scripts/schemas/flight_schema.json` is PyNEATS's own input schema. It is not the companion
  schema.
- The NEATS application source was not available on this machine or in the
  `eurocontrol-asu` GitHub organisation. Every statement about application preprocessing
  therefore rests on the task owner's confirmation and is not verified in code.
- The `climaccf` package is not a declared dependency and is not installed. CLIMaCCF
  behaviour was checked against a read-only clone of `github.com/dlr-pa/climaccf` (HEAD
  `0184719`, 2025-06-20) and against the Dietmüller et al. 2023 and Matthes et al. 2023 GMD
  papers.
- No BADA data files were read. pyBADA was inspected as source code only.

**Dependency versions (from `uv.lock`).** pycontrails 0.60.2, pyBADA 0.1.12,
openairclim 0.13.0, xarray 2024.10.0. Findings that rest on a library interface quote paths
relative to `site-packages`.

**Method.**
- Five parallel tracers followed every AO field from the JSON boundary through parsing,
  interpolation, performance, emissions, climate functions and metrics to the outputs:
  - the input boundary, time and position;
  - fuel properties;
  - performance;
  - emissions, climate and outputs;
  - runners and weather.
- They established units from arithmetic, constants, downstream library interfaces, tests
  and golden data. A variable name or a plausible magnitude was not accepted as evidence.
- Tracer findings were merged.
- Two independent skeptics checked every finding. One asked whether the behaviour is real.
  The other asked whether something else already accounts for it.
- A completeness critic then commissioned six gap investigations, and their findings were
  verified in turn.
- The highest-impact claims were checked again by hand: PV units, `contrails_ef_J`, the
  mass-derived fuel flow, the OpenAirClim `t_0`, BADA4 `VStall` and BADA3 `MPL`.
- No pipeline or BADA calculation was run. Numerical consequences quoted below come from
  arithmetic on the committed golden outputs (`tests/data/golden/*_output.json`).

**Evidence tags.** *Demonstrated* means shown by computation, a library interface, tests or
golden data. *Stated* means written in a comment, docstring or document only.

**I/O variants covered.**
- JSON file input (`FleetRunnerParams.trajectory_json_filepath`, `scripts/run_json.py`).
- DataFrame input (`FleetRunnerParams.trajectory_dataframe`, `FlightRunner(source=df)`).
- Large emitter (Method C: CoCiP plus local aCCF or CLIMaCCF) and small emitter (Method D:
  OpenAirClim).
- Performance-only runner.
- Flights with and without a trajectory, and every combination of provided `ff`, `ee` and
  `am`.

## 3. Audit table: AO input fields

| JSON field | JSON unit or convention | PyNEATS boundary unit | Internal or output unit, if different | Existing conversion and layer | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| *(top level)* object or array | `anyOf`: one `NeatsData` object or an array of them | list of flight objects only | — | none. A bare object is iterated by its keys and raises `AttributeError` | **New discrepancy** (D1) | `steps/parsing/neats_io.py:45-46`; `runners/fleet.py:561-566`; `scripts/run_json.py:238-240` *(demonstrated, snippet)* |
| `departure_date_time` | UTC, ISO 8601; "as indicated in Item 13 of the flight plan" | attr `aobt`: string copied verbatim | — | none. Never parsed or normalised; used only in flight keys and outputs | **Ambiguous / unverified** (A7): Item 13 is the EOBT (ICAO Doc 4444); the MRR does not choose; the PyNEATS label "AOBT" is unsupported | `neats_io.py:106`; `views.py:48-55`; golden output `aobt` equals the input string *(demonstrated)*; `flight_schema.json:38` and `output-format.md:50` say "AOBT" *(stated)* |
| `arrival_date_time` | UTC, ISO 8601 | mapped, then dropped | — | removed by the `allowed_attrs` filter, because it is not in the Flight4D attr lists | **Not consumed** | `neats_io.py:98,107,122`; `steps/parsing/views.py:35-55` *(demonstrated)* |
| `nwp_date_time` | UTC, ISO 8601, nullable; the NWP instance to use | not read | — | none. The NWP instance is whatever weather store or factory the caller supplies | **Not consumed** (open question, A8) | `grep -rn nwp` finds no code; `runners/fleet.py:578-584` *(demonstrated)* |
| `aircraft_properties.takeoff_mass` | kg, 0.1 kg resolution | attr `takeoff_weight`, kg | kg; pyBADA mass | rename only | **Consistent**: MRR Annex IIIa §1(29) defines it as kg "at beginning of the take-off run" (usage note in A6) | `neats_io.py:112`; `steps/performance/bada_model.py:786-808,849` *(demonstrated)* |
| `aircraft_properties.load_factor` | "unitless", [0, 1]; basis not stated | attr `payload_factor`, fraction | ZFW = OEW + pf × MPL in kg, or pf × (MTOW − OEW) when MPL is unavailable, which is always the case for BADA3 | rename only. Default 1.0. Not clipped | **Consistent**: defined by MRR Annex IIIa §1(32) as a fraction of maximum payload mass; default 1 per §5(2)(b) (A3) | `neats_io.py:113`; `bada_model.py:963-980`; `neats_default_parameters.py:141-143` *(demonstrated)*; `flight_schema.json:78-81` "payload / max-payload ratio" *(stated)* |
| `fuel_properties.hydrogen_content` | "percentage of hydrogen mass content", 0.01 resolution | wt.% (for example 13.79) | wt.%. Scales `ei_h2o` = 1.23 × (wt.% / 13.8) kg/kg | none | **Consistent** | `neats_io.py:115`; `core/neats_fuel.py:81-82,106`; pycontrails `core/fuel.py:53` (JetA 13.8); golden inputs 13.79 *(demonstrated)*. PyNEATS docs that say "fraction" are in Section 9 |
| `fuel_properties.hydrogen_per_carbon_ratio` | "unitless"; atomic or mass basis not stated | attr `h_c_ratio`, treated as an **atomic (molar)** H/C ratio | converted to wt.% H = 100 · r·1.008 / (12.011 + r·1.008); used only when `hydrogen_content` is absent | conversion in `NEATSFuel.__init__` | **Consistent**: MRR Annex IIIa §1(36) defines it as the number of H atoms per C atom (A4) | `neats_fuel.py:83-87`; range check: atomic [1.9061, 2.1857] maps exactly to [13.79, 15.50] wt.% (`tests/test_cases_pipeline.py:1492-1516`, mapping recomputed by the auditor) |
| `fuel_properties.aromatic_content` | "unitless"; scale and basis not stated | attr `aromatic_content`, stored | not used in any calculation | none | **Not consumed**. Volume basis per MRR §5(4) default; JSON scale undefined (A5) | `neats_io.py:117`; `neats_fuel.py:94-96`; default 0.25 commented as 25 % (`neats_default_parameters.py:300-302`) *(stated)* |
| `fuel_properties.calorific_value` | MJ/kg of fuel | attr `q_fuel`, **J/kg** (lower heating value) | J/kg in pycontrails `Fuel.q_fuel` and in the BADA fuel-flow correction ratio | × 1e6 in the **NEATS application** (owner-confirmed, not inspected). PyNEATS performs no conversion | **Known difference handled upstream** | `neats_io.py:118`; `neats_fuel.py:92`; `neats_default_parameters.py:315-320` (43.13e6, 42.8e6); `bada_model.py:765-771,841,875`; golden inputs 4.1944e7 *(demonstrated)* |
| `fuel_properties.sulphur` | "unitless"; scale and basis not stated | attr `sulphur_content`, stored | not used. `ei_so2` is always the JetA value of 1.2e-3 kg/kg | none | **Not consumed**. Mass basis per MRR §5(4) default; JSON scale undefined (A5) | `neats_io.py:119`; `neats_fuel.py:97-98,107-108`; pycontrails `emissions.py:770-771` *(demonstrated)* |
| `fuel_properties.naphthalene` | "unitless"; scale and basis not stated | dropped | — | key `naphthalene` in `neats_io` against `naphtalene` in `Flight4D.ATTRS_OPTIONAL`, so the value never reaches the fuel object (I2) | **Not consumed** | `neats_io.py:120,122`; `views.py:45`; `neats_fuel.py:195`; snippet *(demonstrated)* |
| `trajectory.trajectory_data[].ts` | UTC, ISO 8601 date-time | column `time`: naive string `%Y-%m-%d %H:%M:%S`, read as UTC | tz-naive UTC `datetime64[ns]`; durations in s (forward differences); resampled to 60 s by default | `strptime(...%z)` then `strftime` **discards the offset without applying it** | **New discrepancy** (D2), conditional on non-UTC offsets; UTC input is correct | `neats_io.py:61-68`; `neats_parser.py:233-242`; pycontrails `core/vector.py:292-304,2162-2167`; snippet *(demonstrated)* |
| `trajectory.trajectory_data[].lat` | decimal degrees, WGS 84 | column `latitude`, degrees | degrees | none | **Consistent** | `neats_io.py:73`; golden output equals input *(demonstrated)* |
| `trajectory.trajectory_data[].lon` | decimal degrees, WGS 84, [-180, 180] | column `longitude`, degrees | degrees; no wrapping | none | **Consistent** | `neats_io.py:74` *(demonstrated)* |
| `trajectory.trajectory_data[].fl` | flight level in hundreds of feet | column `altitude` in FL until the parser | m of **ISA pressure altitude** (FL × 30.48). pycontrails derives `level` (hPa) and `air_pressure` (Pa) from it | × 100 then `ft_to_m` (× 0.3048) in `NeatsTrajectoryParser` | **Consistent** | `neats_io.py:77`; `neats_parser.py:217-225`; pycontrails `core/vector.py:1503-1505,1544-1545`; golden `altitude[0]` = 121.92 m for FL 4 *(demonstrated)* |
| `trajectory.trajectory_data[].tas` | knots | column `true_airspeed`, **m/s** | m/s (BADA adapters, `overall_propulsion_efficiency`). Derived from ground speed and wind (m/s) when absent | × 1852/3600 in the **NEATS application** (owner-confirmed, not inspected). PyNEATS performs no conversion | **Known difference handled upstream**. The MRR (§1(4)) defines TAS in m/s; see §6.0 | `neats_io.py:82`; `bada_model.py:623-637,868,1050`; pycontrails `physics/jet.py:155-178` *(demonstrated)* |
| `trajectory.trajectory_data[].ff` | kg/s; whole-aircraft or per-engine not stated | column `fuel_flow`, kg/s, consumed as **whole aircraft** | `fuel_burn` = ff × segment duration, in kg per forward segment | none. Never scaled by engine count | **Consistent**: MRR Annex IIIa §1(33) defines whole-aircraft flow; some RSTS tables say "each engine" (A1) | `neats_io.py:79`; `bada_model.py:693,1071-1076`; pycontrails `emissions.py:183-195` (`fuel_flow / n_engine`), `cocip.py:929-931` (`fuel_flow / true_airspeed`) *(demonstrated)* |
| `trajectory.trajectory_data[].ee` | "unitless", [0, 1]; definition not stated | column `engine_efficiency`, fraction | consumed as **overall propulsion efficiency** F·TAS / (ff·q_fuel) in the SAC slope, proportional to 1/(1 − η). Computed values are clipped to [0, 0.5]; provided values are not clipped | none | **Consistent** in definition: MRR §1(34) and Commission guidance give overall propulsion efficiency; scale is "percentage" in law but [0, 1] in the schema (A2) | `neats_io.py:80`; `bada_model.py:1046-1063`; pycontrails `physics/jet.py:178,189`, `models/sac.py:206` *(demonstrated)* |
| `trajectory.trajectory_data[].am` | kg, 0.1 kg resolution | column `aircraft_mass`, kg | kg. When `ff` is absent, `ff` = −Δam/Δt in kg/s (D3) | none | **Consistent** (derived `ff` in D3) | `neats_io.py:81`; `bada_model.py:705-749,859-860` *(demonstrated)* |
| `flight_identification`, `departure_airport`, `arrival_airport` | identifiers | attrs `flight_id`, `departure_airport`, `arrival_airport` | — | none (upper-cased for the airport-fuel lookup) | **Not applicable** (no unit) | `neats_io.py:102-104` |
| `aircraft_properties.aircraft_type`, `aircraft_version`, `engine_uid` | identifiers; `engine_uid` may be a list of up to 4 | attrs `aircraft_type`, `aircraft_series` (renamed), `engine_uid` | FleetRunner splits a list into one copy per engine id and averages numeric results; FlightRunner rejects a list | rename only | **Not applicable** (no unit) | `neats_io.py:109-111`; `runners/fleet.py:612-640,385-390`; `neats_parser.py:298-303` |
| `confidential`, `ets_exemption` | flag, letter | not read | — | — | **Not consumed** (no unit) | `neats_io.py:99-123` |
| `trajectory.trj_data_source` | `Actual` or `Planned` | not read. `model_type` is the function argument, default `"NM"` | — | — | **Not consumed** (no unit) | `neats_io.py:22,105`; `runners/fleet.py:566` |

### Relevant mappings beyond the AO JSON path

| Mapping | Convention | PyNEATS boundary unit | Internal or output unit | Existing conversion and layer | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| DataFrame entry (`trajectory_dataframe`, `FlightRunner(source=df)`): `altitude`, `time` | Not defined by AO upload schema | `altitude` in **FL**, not metres. `time` as `datetime64` (naive means UTC; tz-aware is converted) or a string in `date_format` (default `%Y-%m-%d %H:%M:%S`) | as for the JSON path | the same parser conversions | **Ambiguous / unverified** (A9) | `neats_parser.py:141,217-258`; example comment `examples/fleet_computation_from_dataframe.py:172` *(stated)*; snippet: ISO strings become NaT and are dropped *(demonstrated)* |
| Airport fuel-property file (`airport_fuel_path`) | Not defined by AO upload schema | `float()` only. `q_fuel` assumed J/kg; `h_c_ratio` used as atomic | J/kg, wt.% after `NEATSFuel` | **none**. PyNEATS reads the file directly, so the application's × 1e6 does not apply to it | **Ambiguous / unverified** (A10) | `neats_parser.py:35-41,44-120,284-296`; `tests/test_airport_qfuel.py` (J/kg) |
| Default branch: no `calorific_value` | Not defined by AO upload schema | `DEFAULT_Q_FUEL` = 42.8e6 J/kg | the BADA fuel flow is still multiplied by 43.13/42.8 = 1.0077 | correction ratio in `BADAPerformanceModel` | **Ambiguous / unverified** (A11) | `neats_fuel.py:92`; `bada_model.py:565-571,764-772,841,875`; `docs/explanation/mrv-specification.md:220` *(stated)* |
| `REFERENCE_Q_FUEL` against BADA4 LHV | Not defined by AO upload schema | 43.13e6 J/kg (pycontrails JetA) | — | not read from BADA files, although BADA4 carries a per-aircraft LHV | **Ambiguous / unverified** (A12) | `neats_default_parameters.py:315-317`; pyBADA `bada4.py:1855-1874`; pyBADA dummy BADA4 files: 43.217e6 and 43.71e6 J/kg |
| Per-point nulls in `tas`, `ff`, `ee`, `am` | schema allows `null` per point | a column survives unless every value is null | NaN spreads through interpolation and is skipped by sums | none | **New discrepancy** (D4) | `neats_io.py:93-94`; `steps/interpolation/pycontrails_interpolation.py:108-112`; `bada_model.py:1071-1076`; snippet *(demonstrated)* |

## 4. Audit table: public outputs

The AO upload schema defines inputs only. It is not an output contract, so every row below
reads "Not defined by AO upload schema" and records the convention the code produces.
`runner.results` from `FleetRunner` carries only flight-level entries. Per-waypoint columns
appear in `FlightView.to_dict()` dumps (the golden files) and in in-memory `Flight` objects.

| Output field | JSON unit or convention | PyNEATS unit | Basis | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| `flight_information.fuel_burn_kg` | Not defined by AO upload schema | kg | flight total: nansum of per-segment `fuel_burn` | Consistent internally. Undercounts with partial nulls (D4) | `climate_metrics/gwp.py:359-379,434`; golden 3773.20 kg |
| `flight_information.co2_baseline_kg` | Not defined by AO upload schema | kg CO2 | flight total (`attrs['total_co2']`) | Consistent | `gwp.py:353,433`; golden 11919.55 = 3.159 × 3773.20 |
| `flight_information.contrails_ef_J` | Not defined by AO upload schema | **J** for Method C (sum of CoCiP `ef`). **W m-2 yr** for Method D (`AGWP_20_CONT`, no efficacy) | flight total | **New discrepancy** for Method D (O2) | `gwp.py:411,426`; openairclim `write_output.py:48-51` |
| `climate_metrics[species][H].EAGWP_Wm2yr` | Not defined by AO upload schema | W m-2 yr | flight total, efficacy-weighted; H = 20, 50, 100 yr | Consistent with code docstrings. The MRV spec label differs (Section 9) | `gwp.py:108-172,385-399`; golden recomputation ratio 1.0 |
| `climate_metrics[species][H].CO2eq_kg` | Not defined by AO upload schema | kg CO2-equivalent | flight total = EAGWP / C(H); for CO2 it equals `total_co2` | Consistent | `gwp.py:146-151,384`; `core/physics.py:62-67` |
| Low-altitude zero records | Not defined by AO upload schema | `fuel_burn_kg` and `co2_baseline_kg` are NaN; every species, CO2 included, is 0.0 | flight | Ambiguous (O9) | `runners/fleet.py:295-319`; `tests/test_zero_climate_result.py` |
| `fuel_flow` (column) | Not defined by AO upload schema | kg/s, whole aircraft | instantaneous rate per waypoint (AO value, −Δam/Δt, or BADA × q_ref/q) | Consistent (D3 for the derived branch) | `bada_model.py:693,741,875,1071-1074`; pycontrails `emissions.py:183-195` |
| `fuel_burn`, `fuel` (columns) | Not defined by AO upload schema | kg | per forward segment [tᵢ, tᵢ₊₁]; last value NaN | Consistent | `bada_model.py:693,1076-1079`; pycontrails `core/flight.py:1966-1969` |
| `aircraft_mass`, `thrust` (columns) | Not defined by AO upload schema | kg; N (whole aircraft) | instantaneous | Consistent | `bada_model.py:1066-1067`; `bada_adapters.py:279` |
| `true_airspeed`, `ground_speed`, `segment_duration`, `rocd`, `acceleration`, `delta_tau` (columns) | Not defined by AO upload schema | m/s, m/s, s, **ft/min**, m/s², K | per segment (forward) or per point | Consistent. `rocd` is the only non-SI kinematic column | `bada_model.py:622-674`; pycontrails `core/flight.py:617-717` |
| `engine_efficiency` (column) | Not defined by AO upload schema | dimensionless fraction | instantaneous; computed values clipped to [0, 0.5] | Consistent (definition question A2) | `bada_model.py:1056-1063` |
| `co2`, `h2o`, `so2`, `sulphates`, `oc`, `nox`, `co`, `hc`, `nvpm_mass` (columns) | Not defined by AO upload schema | kg | per segment = `fuel_burn` × EI | Consistent | pycontrails `emissions.py:760-777` |
| `nvpm_number` (column) | Not defined by AO upload schema | count (particles) | per segment | Consistent | pycontrails `emissions.py:777` |
| `nox_ei`, `co_ei`, `hc_ei`, `nvpm_ei_m`; `nvpm_ei_n` (columns) | Not defined by AO upload schema | kg/kg fuel; particles/kg fuel | emission index, not mass. NOx is NO2-equivalent by ICAO EDB convention | Consistent | pycontrails `emissions.py:263-295,324,476-479`; `models/apcemm/inputs.py:70` |
| `total_co2`, `total_h2o`, `total_so2`, `total_sulphates`, `total_oc` (attrs) | Not defined by AO upload schema | kg | flight total (nansum) | Consistent | pycontrails `emissions.py:780-788` |
| `total_nox`, `total_co`, `total_hc`, `total_nvpm_mass`; `total_nvpm_number` (attrs) | Not defined by AO upload schema | kg; count | flight sum **over waypoints inside the met domain only** (NaN EI elsewhere) | Ambiguous (O13) | golden EAF2143: 29 of 93 segments, 31.8 % of fuel, excluded |
| `ATR_20_O3`, `ATR_20_CH4`, `ATR_20_H2O` (columns) | Not defined by AO upload schema | K | per segment: pulse ATR over 20 yr, no efficacy; CH4 includes PMO (× 1.29) | `ATR_20_H2O`: **New discrepancy** (O1) | `climate_functions/local_accf.py:152-253,300-306` |
| `ef` (column, CoCiP) | Not defined by AO upload schema | J | contrail energy forcing per waypoint, summed over the contrail lifetime (energy, not forcing) | Consistent | pycontrails `contrail_properties.py:1485-1488`, `cocip.py:1434,1448` |
| `rf_sw_mean`, `rf_lw_mean`, `rf_net_mean`, `sdr_mean`, `rsr_mean`, `olr_mean` (columns) | Not defined by AO upload schema | W m-2 | local contrail RF and fluxes averaged over the contrail lifetime (forcing, not energy) | Consistent | pycontrails `cocip.py:1436-1446,2022-2093` |
| `AGWP_{20,50,100}_{CH4,O3,H2O,CONT}` (attrs, Method D) | Not defined by AO upload schema | W m-2 yr | flight total, one-year pulse, no efficacy; CH4 includes PMO | Consistent units. Window anchored to 2025 (O4) | `open_airclim.py:251-268`; openairclim `write_output.py:48-51` |
| `time` (`FlightView.to_dict`) | Not defined by AO upload schema | integer Unix seconds, truncated, from tz-naive UTC | instantaneous | Consistent; was undocumented (O11) | `core/views.py:229-232`; golden 1752085020 = first input `ts` |
| `contrail_age` (`FlightView.to_dict`) | Not defined by AO upload schema | integer **nanoseconds** | per waypoint | Consistent; was undocumented (O11) | pycontrails `utils/json.py:60` (NumpyEncoder) |
| Performance-only runner: `timestamps`, `true_airspeed`, `fuel_flow`, `aircraft_mass`, `engine_efficiency` | Not defined by AO upload schema | ISO 8601 **without offset** (naive UTC), m/s, kg/s, kg, fraction | per waypoint; one record per engine copy | Ambiguous (O12) | `runners/performance_runner.py:32,80-84,146-158` |

## 5. Known differences handled upstream

| Quantity | AO JSON unit | PyNEATS input unit | Conversion | Layer | Provenance | PyNEATS consumers checked |
| --- | --- | --- | --- | --- | --- | --- |
| `tas` → `true_airspeed` | knots | m/s | × 1852/3600 | NEATS application, before PyNEATS is called | **confirmed by the task owner**; application source not inspected | BADA adapters (`bada_model.py:868`), `overall_propulsion_efficiency` (`bada_model.py:1050`; pycontrails `jet.py:155-178`), the pycontrails Emissions/CoCiP interfaces. All treat the value as m/s. No knots handling exists in `src/` |
| `calorific_value` → `q_fuel` | MJ/kg of fuel | J/kg of fuel (LHV) | × 1e6 | NEATS application, before PyNEATS is called | **confirmed by the task owner**; application source not inspected | `NEATSFuel` (`neats_fuel.py:92`), the BADA correction ratio (`bada_model.py:841,875`), SAC/CoCiP through `Fuel.q_fuel` and the fleet column `q_fuel`. All treat it as J/kg. No × 1e6 exists in `src/` |

Direct callers of PyNEATS must supply m/s and J/kg themselves. This covers the FleetRunner
JSON path, `scripts/run_json.py` and DataFrame users. Two places get no upstream protection:

- **Airport fuel file.** PyNEATS reads `airport_fuel_path` directly, so a `q_fuel` column in
  MJ/kg would enter unconverted (A10).
- **No magnitude check.** PyNEATS does not check the size of `q_fuel`. On the BADA path,
  42.8 (MJ/kg) fails loudly through the 100 kg/s fuel-flow outlier check. When `ff`, `ee` and
  `am` are all provided, BADA is skipped and the value reaches SAC/CoCiP silently.

`scripts/schemas/flight_schema.json:106-109` labels `calorific_value` as MJ/kg. The golden
inputs it validates contain J/kg values, and the code expects J/kg (Section 9).

## 6. Ambiguities and unverified conventions on the AO input path

### 6.0 What the regulation and official documents settle

Investigated after the code audit. Each field the AO schema leaves undefined was traced to
its authoritative definition, and two independent checks then re-opened every cited source.
Sources were ranked in this order:
1. EU law: Implementing Regulation (EU) 2024/2493, which inserts Articles 56a and 56b and
   Annex IIIa into the MRR, Implementing Regulation (EU) 2018/2066. The English Annex IIIa is
   unchanged in the consolidated MRR of 27 May 2025. The later act 2025/842 and the
   corrigenda affect other language versions only.
2. Official Commission and NEATS documents:
   - the Commission DG CLIMA "MRV non-CO2 data collection Guidance", v2.1, February 2026;
   - the DLR/DWD "Reference set of technical specifications for the MRV" (RSTS,
     EC-CLIMA/2024/NP/0014, March 2025);
   - the pre-NEATS "System Architecture Description" (SAD, 10 January 2025). This is a draft
     input specification that the AO schema has since superseded.
3. Standards: ICAO Doc 4444, ICAO Annex 16 Vol. II, DEF STAN 91-091 / ASTM D1655.
4. Repository artefacts.

"§" below refers to MRR Annex IIIa.

| AO field | Authoritative definition | Source | PyNEATS | Remaining gap |
| --- | --- | --- | --- | --- |
| `ff` | "the mass of fuel in kilograms that passes through the aircraft fuel system and into the aircraft's engines per second": **whole aircraft, kg/s** | §1(33); SAD "total fuel mass flow rate"; RSTS Table 2.13 (CoCiP input) "total" | matches | RSTS Tables 2.5, 2.7, 2.8 and 2.10 say "fuel mass flow rate of each engine". The law never says "total" or "all engines" in so many words; the whole-aircraft reading is its plain meaning |
| `ee` | "the percentage of useful thrust generated by an aircraft engine relative to the energy input from fuel". The guidance calls it "aircraft overall propulsion efficiency"; the SAD and RSTS give "Overall propulsion efficiency", unitless, [0, 1] | §1(34), §1(35) ("by all-time stamps"); guidance §3.3; SAD II.11.2.7 | matches (F·TAS / (ff·LHV), pycontrails SAC) | The law says "percentage" while the schema, SAD and RSTS give [0, 1]; the schema's maximum of 1 rejects percentage input. Net or gross thrust is not stated. The guidance wording could also be read as one value per flight |
| `load_factor` | "the weight of passengers, cargo and baggage, including mail and hand luggage, expressed as fraction of the maximum payload mass"; maximum payload "can be retrieved by the applied fuel burn module"; default 1 | §1(31), §1(32), §5(2)(b); SAD and RSTS "fraction of the maximum payload mass, e.g., as defined in BADA" | matches (ZFW = OEW + pf·MPL) | none for the definition. §1(3) also uses "load factor" in the aerodynamic (g-load) sense, so the template should name the payload meaning explicitly. For BADA3, PyNEATS uses MTOW − OEW instead of MPL (I4) |
| `hydrogen_per_carbon_ratio` | "the number of hydrogen atoms (H) per carbon atom (C) per molecule of the fuel": **atomic (molar)** | §1(36); ReFuelEU Union Database field "Molar ratio of hydrogen to carbon" | matches | The SAD draft said "ratio of hydrogen mass to carbon mass"; the law prevails. `mrv-specification.md` still says "molecular mass ratio" (Section 9) |
| `hydrogen_content` | not in the law. NEATS default "Hydrogen Content 13.79 % mass"; RSTS and SAD "Percentage of hydrogen mass content" | guidance v2.1 §3.3 Table 3; RSTS Table 2.12 | matches (wt.%) | none. PyNEATS's own `input-format.md` and `flight_schema.json` say "fraction (0–1)" (Section 9) |
| `calorific_value` | "net calorific value of the fuel on board", which is the lower heating value (MRR Art. 3 NCV definition); MJ/kg in the schema, SAD and ReFuelEU; default 42.8 MJ/kg | §1(38); MRR Art. 3; guidance Table 3 | matches (J/kg after the application's × 1e6) | none |
| `takeoff_mass` | "the aircraft mass at beginning of the take-off run, including everything and everyone carried at that moment, in kilograms" | §1(29) | unit matches. PyNEATS applies it at the first retained trajectory point, which may be a taxi point (A6) | The SAD says "actual", while the guidance names the operational flight plan as the source |
| `am` | "the mass in kilogrammes of the aircraft along the trajectory, which equals to subtracting from the take-off mass the fuel burn" | §1(28) | matches | none |
| `aromatic_content`, `sulphur`, `naphthalene` | Basis: defaults "25 % volume", "0,3 % mass", "3,0 % volume" (the ASTM Jet A-1 limits); ReFuelEU reports "aromatics and naphthalenes by percentage volume and of sulphur by percentage mass". Sulphur and naphthalene are not defined in §1 and appear only as defaults. Not used by NEATS yet | §5(4); §1(37); ReFuelEU Reg. (EU) 2023/2405 Art. 10(d); guidance Table 3 footnote | not used. The defaults 0.25 / 0.003 / 0.03 are fractions on these bases | **Scale (25 or 0.25) is not defined** by any public source. The volume basis of the AO aromatics field is inferred from the defaults, and the SAD draft said "mass". The ReFuelEU Union Database uses a percent scale ("20.5 % is reported as 20.5") |
| `departure_date_time` | The law says only "day and time of departure … UTC" (§1(1)). The schema ties the field to flight-plan Item 13, which holds "the estimated off-block time (EOBT)", never an actual time | ICAO Doc 4444 App. 2, Item 13 | label mismatch: PyNEATS stores it as `aobt` and calls it "actual off-block time" (no numbers change) | EOBT or AOBT is not fixed in law. Item 13 carries only HHMM; the date comes from Item 18 DOF/ |
| `arrival_date_time` | "day and time of … arrival, UTC"; the event (landing, in-block, EOBT + EET) is undefined everywhere | §1(1) | dropped by PyNEATS | the AIBT label in `flight_schema.json` has no basis |
| `ts` | time stamp in seconds; interval "not exceeding 60 seconds"; UTC. The RSTS asks for "YYYY-MM-DDTHH:MM:SS" | §1(6), §1(7); RSTS Table 2.1 | matches for UTC input (D2 for offsets and fractional seconds) | none |
| `lat`, `lon`, `fl` | latitude and longitude "in decimal degree"; altitude "in pressure altitude"; the SAD gives the FL number in hundreds of feet | §1(5); SAD | matches | none |
| `tas` | "the speed of the aircraft relative to the air mass …, in meters per second (m/s)". The AO schema and RSTS §2.2.3 (operator-supplied data) say knots | §1(4); RSTS §2.2.3 | PyNEATS uses m/s (the legal unit); the application converts the schema's knots | Not a defect for uploads that follow the schema. An operator who follows the regulation's m/s instead would have TAS scaled by 0.514 without any error; a plausibility check upstream would catch it |
| `nwp_date_time` | The law requires a "common reference NWP model, provided by the Commission through NEATS" for enhanced weather data. Method C uses "current weather information" usable "for individual flight planning", i.e. forecast data. The guidance says "Weather data is always provided by NEATS as Secondary data". The RSTS says "flights are evaluated based on the latest weather forecast prior to departure" (ICON runs at 00/06/12/18 UTC, +61 h) | §1(25), §1(26), §4; Art. 56a(7)(b), 56b(7); guidance §2.3, §3.3; RSTS §2.4.5, §4.2 | not read; weather is chosen by the caller | No public source defines the field (run initialisation time or valid time; behaviour when null). The run rule rests on a single non-binding RSTS sentence. Art. 56a(4) also allows AO or third-party weather for basic weather data |
| NOx basis (internal, for O3) | ICAO Annex 16 Vol. II: NOx "calculated as if the nitric oxide were in the form of nitrogen dioxide", "EI(NOx) as NO2". OpenAirClim v0.13 response surfaces are per kg NO, and `nox = "NO2"` applies 30/46; v0.19.0 (2026-09-28) made NO2 the default | ICAO Annex 16 Vol. II Ch. 1, App. 3 §7.1.2; EASA EEDB introduction; openairclim `calc_response.py` | **mismatch** (O3): `nox = "NO"` | No MRV text prescribes the OpenAirClim setting. The method owner should confirm in writing |

Consequences for this audit:
- A1, A2, A3 and A4 are no longer open questions about the template. The regulation defines
  each one, and PyNEATS follows the definition. The remaining action is to align the AO
  template wording with the law: "whole aircraft", "overall propulsion efficiency as a
  fraction", "payload ÷ maximum payload, not seat load factor", "atomic H/C".
- A5 narrows to the numeric scale. A7 becomes a labelling correction (EOBT). A8 stays open
  for the NEATS application team.

Each entry gives:
1. the field and code path;
2. the expected and observed convention, with confidence;
3. the consequence or the open question;
4. whether the application might already handle it;
5. a recommendation. Recommendations are not implemented.

**A1. `ff`: whole aircraft or per engine.** *Resolved (§6.0): whole aircraft, MRR Annex IIIa §1(33). PyNEATS matches. The analysis below explains the consequences if an operator nevertheless sends per-engine values.*
1. `trajectory_data[].ff` → `neats_io.py:79` → `bada_model.py:693,1071-1076` → pycontrails
   Emissions and CoCiP.
2. The AO schema says only "kg·s⁻¹ at the data point". Every PyNEATS consumer treats the
   value as whole-aircraft (high confidence):
   - pycontrails divides by `n_engine` to get per-engine flow (`emissions.py:183-195`);
   - CoCiP uses `fuel_flow / true_airspeed` as fuel per metre (`cocip.py:929-931`);
   - the fuel-burn guardrail compares Σ ff·Δt with MTOW − OEW;
   - every internally produced `ff` is whole-aircraft: BADA, and −Δam/Δt.
3. A per-engine `ff` would make fuel burn, CO2, every emission mass and the CoCiP fuel per
   metre n_engine times too small (× 0.5 for a twin, × 0.25 for a quad). Thrust-setting EIs
   would be looked up at 1/n_engine of the real flow. No guard catches this:
   - the guardrail rejects only overestimates;
   - the 100 kg/s outlier check never inspects a provided `ff`;
   - when `ff`, `ee` and `am` are all present, every check is skipped (`bada_model.py:471-477`).
4. Possibly. The application might normalise `ff`, but nothing confirms it.
5. **Clarify the AO template**: "total fuel flow of the aircraft, all engines, kg·s⁻¹". No
   conversion is needed if AOs send the total. Optionally, apply the existing fuel-burn
   guardrail on the early-exit path as well, so a kg/h value fails loudly.

**A2. `ee`: which efficiency.** *Resolved (§6.0): overall propulsion efficiency, MRR §1(34) and Commission guidance §3.3. PyNEATS matches. Open: "percentage" in law against [0, 1] in the schema.*
1. `trajectory_data[].ee` → `neats_io.py:80` → `bada_model.py:1046-1048` (kept) → pycontrails
   `sac.slope_mixing_line` (`sac.py:206`).
2. The AO schema says "engine efficiency, unitless, [0, 1]". The consumer needs **overall
   propulsion efficiency** η = F·TAS / (ff·LHV), which is what PyNEATS computes when `ee` is
   absent (`jet.py:178`), clipped to [0, 0.5]. Confidence is high for the consumer side.
   `examples/README.md:140` calls the field "engine thermal efficiency".
3. The SAC slope scales with 1/(1 − η). A thermal efficiency of about 0.5 against an overall
   efficiency of about 0.35 raises G by a factor of 1.3. `ee` = 1.0 is schema-valid and makes
   G infinite. Provided values are never clipped.
4. Unknown.
5. **Clarify the AO template**: "overall propulsion efficiency = thrust × TAS / (fuel flow ×
   LHV), fraction, typically ≤ 0.5". Optionally clip provided values in PyNEATS to the
   [0, 0.5] range already used for computed values.

**A3. `load_factor`: basis.** *Resolved (§6.0): payload mass ÷ maximum payload mass, MRR §1(32). PyNEATS matches.*
1. `load_factor` → `payload_factor` (`neats_io.py:113`) → `_estimate_initial_mass_iterative`
   (`bada_model.py:963-980`).
2. The AO schema says "the load factor, unitless". PyNEATS uses it as a payload-mass fraction
   of the BADA maximum payload, ZFW = OEW + pf·MPL. The first-pass guess uses pf·(MTOW − OEW).
   `flight_schema.json:78-81` states "payload / max-payload ratio" (medium confidence that AOs
   will use the same reading). It is used only when neither `am` nor `takeoff_mass` is given.
   The default is 1.0, meaning full payload. Values above 1 are not clipped.
3. An AO sending a passenger load factor (for example 0.85) would get 0.85 × MPL of payload.
   That differs from the real payload of passengers, baggage and cargo, so initial mass and
   fuel change. For BADA3 aircraft the basis is MTOW − OEW rather than MPL (I4).
4. Possibly. The application might convert a seat load factor.
5. **Clarify the AO template**: "payload mass ÷ maximum payload, fraction 0–1; not a seat load
   factor".

**A4. `hydrogen_per_carbon_ratio`: atomic or mass basis.** *Resolved (§6.0): atomic, MRR §1(36). PyNEATS matches.*
1. `neats_io.py:116` → `neats_fuel.py:83-87`.
2. The AO schema says "unitless". PyNEATS assumes an atomic (molar) ratio. The DLR range
   [1.9061, 2.1857] equals [13.79, 15.50] wt.% exactly under that formula. Confidence that
   PyNEATS intends atomic is high; confidence that AOs will send atomic is unknown.
   `mrv-specification.md:233-238` calls it a "molecular mass ratio" and leaves out the × 100.
3. Only matters when `hydrogen_content` is absent. A mass ratio (about 0.16 for Jet A) would
   give about 1.3 wt.% H, so `ei_h2o` would be about 10 times too low. That affects H2O
   emissions, CoCiP SAC, the OpenAirClim H2O inventory and the nvPM SAF correction. There is
   no range check (test case `TC_HC_RATIO_OUT_OF_RANGE` is a strict xfail).
4. Possibly.
5. **Clarify the AO template**: "atomic (molar) H/C ratio, about 1.9–2.2 for Jet A". Correct
   the MRV spec formula (Section 9).

**A5. `aromatic_content`, `sulphur`, `naphthalene`: scale and basis.** *Partly resolved (§6.0): basis from the MRR §5(4) defaults and ReFuelEU (aromatics and naphthalene by volume, sulphur by mass). The JSON scale is still undefined.*
1. `neats_io.py:117-120` → `neats_fuel.py:94-102`.
2. The AO schema says "unitless" with no scale and no mass/volume basis. The PyNEATS defaults
   are fractions (0.25, 0.003 commented as "0.3 %", 0.03). The airport test fixture looks like
   percentages (19.1, 0.07, 0.36). `flight_schema.json` says "mass fraction". None of these
   values enters a calculation. Naphthalene never reaches the fuel object (I2).
3. No numerical effect today. Any future use (for example sulphur-scaled `ei_so2`) would face
   an undefined scale. The SO2 and sulphate outputs use the fixed Jet A-1 EI (600 ppm S basis)
   whatever sulphur is supplied.
4. Possibly.
5. **Clarify the AO template** (fraction, % or ppm; mass or volume) before any use. Document
   that SO2 and sulphate outputs are fixed Jet A-1 values.

**A6. `takeoff_mass`: point of application and precedence.** *Definition settled (§6.0): mass at the beginning of the take-off run, MRR §1(29). PyNEATS's point of application does not guarantee that event (see below).*
1. `takeoff_weight` → `_choose_mass_strategy` / `_single_pass_performance`
   (`bada_model.py:786-808,849`).
2. The unit is kg and consistent. It is applied at the first **retained** trajectory point:
   - after resampling to 1 min;
   - for BADA3 aircraft, after the speed filter;
   - on the altitude-fallback path, at the first point at or above FL20.
   It is ignored, with only a debug log, when an `am` column exists, and nothing checks it
   against `am[0]`. It is not clipped to MTOW.
3. Ground or taxi points before rotation are charged against it. On the FL20 fallback, the
   climb fuel below FL20 is never subtracted. Conflicting `am` and `takeoff_mass` pass without
   notice.
4. Possibly, if the application trims the trajectory to the take-off point.
5. **Clarify the AO template**: mass at brake release or at the first trajectory point.
   Optionally log at warning level when `am` overrides `takeoff_mass`.

**A7. `departure_date_time`: EOBT or AOBT.** *Partly resolved (§6.0): Item 13 holds the EOBT (ICAO Doc 4444). The MRR does not choose. The PyNEATS "AOBT" label is unsupported.*
1. `neats_io.py:106` → attr `aobt` → `report.py:114-135`.
2. The AO schema says "Item 13 of the flight plan in UTC", which is the EOBT. PyNEATS docs
   (`flight_schema.json:38`, `output-format.md:50`) label it "actual off-block time (AOBT)".
   The string is copied verbatim and never parsed.
3. No numerical effect. The output label may describe the wrong quantity. Flight keys compare
   raw strings, so the same instant written as `Z` and as `+0000` gives two different keys.
4. Unknown.
5. **Clarify the AO template** and PyNEATS output docs. If the field stays, normalise it to a
   UTC ISO string at the boundary.

**A8. `nwp_date_time`: who selects the NWP instance.** *Still open (§6.0): weather comes from the common NEATS NWP model. The RSTS rule is "latest weather forecast prior to departure". The field itself is not defined publicly.*
1. Not read anywhere in PyNEATS. Weather comes from `zarr_paths` (`fleet.py:578-584`) or
   `DWDFactory(...)(asofdate, hour)` (`weather_factory.py:259-296`).
2. The AO schema requires each flight to be computed with the named NWP instance.
3. A fleet that mixes flights requesting different NWP instances runs on one store. Flights
   outside the store's time range get NaN meteorology, and NaN wind is set to 0
   (`weather_provider.py:382-383`). `DWDFactory` builds its window with `strftime` and no time
   zone conversion, so `asofdate` must be naive UTC or UTC-aware.
4. Likely. The application may group flights by `nwp_date_time`.
5. **Confirm with the application owners.** At minimum, the `FleetRunnerParams` docstring now
   states that the field is not read.

**A9. DataFrame entry contract.**
1. `split_df_into_flights` / `FlightRunner(source=df)` → `NeatsTrajectoryParser`.
2. `altitude` must be a flight level and `time` must match `date_format`. Until this patch the
   user-facing entry points did not say so.
3. Altitude supplied in metres becomes 30.48 times too high. Time strings in ISO form (with
   `T`, an offset or fractions) become NaT. Those rows are dropped silently, and the flight
   fails only if every row is dropped.
4. Not applicable (direct library use).
5. Documented in the patch. Optionally rename the column or check its range.

**A10. Airport fuel file units.**
1. `_load_airport_fuel_props` (`neats_parser.py:44-120`) → fallback (`neats_parser.py:284-296`).
2. Values are passed through `float()` only. The tests use `q_fuel` in J/kg. `h_c_ratio` is
   treated as atomic. There is no `hydrogen_content` column. The file's own units are
   unverified, and no production file is in the repository.
3. A `q_fuel` column in MJ/kg would enter 1e6 times too small, because the application's
   conversion does not apply to this file. A mass-based `h_c_ratio` would make `ei_h2o` about
   10 times too low.
4. No. PyNEATS reads the file itself.
5. **Confirm units with the file owner.** The patch documents the assumed units in the loader
   docstring. Optionally add a magnitude guard for `q_fuel`.

**A11. `q_fuel` correction on the default branch.**
1. `bada_model.py:565-571,764-772,841,875`.
2. `mrv-specification.md:220` says no correction is applied when the AO gives no `q_fuel`. The
   code always applies the ratio 43.13/42.8, because `NEATSFuel` always carries a `q_fuel`
   (default 42.8e6 J/kg). The `else reference_q_fuel` branch cannot be reached.
3. BADA fuel flow, fuel burn, CO2 and every fuel-proportional quantity are +0.77 % for flights
   without `calorific_value`. The iterative take-off mass shifts as well.
4. No.
5. **Decide in PyNEATS**: apply the correction only to a supplied `q_fuel`, or amend the spec.

**A12. `REFERENCE_Q_FUEL` against BADA4 LHV.**
1. `neats_default_parameters.py:315-317` → `bada_model.py:841`.
2. A constant 43.13e6 J/kg (the pycontrails JetA value) stands in for the LHV that BADA fuel
   flow corresponds to. BADA4 files carry their own LHV; pyBADA's dummy files have 43.217e6
   and 43.71e6 J/kg. BADA3 has none.
3. The correction is off by LHV_file / 43.13e6, which is +0.2 % to +1.35 % on the dummy files.
   Licensed files were not checked.
4. No.
5. **Check against BADA4 files**. Consider reading the adapter's LHV for BADA4.

**A13. Mixed fuel-flow provenance (documented in part).**
- When `ff` is provided without `am`:
  - output `fuel_flow` and `fuel_burn` come from the AO;
  - `aircraft_mass` and the iterative take-off mass are integrated from BADA fuel flow
    (`bada_model.py:927,990-994,1018-1022,1067`);
  - so mass(t₀) − mass(t_end) ≠ Σ fuel_burn.
- A computed `ee` always uses BADA fuel flow. That is documented design
  (`mrv-specification.md:190`; `input-prioritization.md:44`).
- Units agree throughout. The issue is provenance, not scale.
- **Recommendation**: document this, or integrate mass from the provided `ff`. The decision
  belongs to the method owner.

## 7. New discrepancies

### On the AO input path

**D1. Bare single-flight object rejected.**
1. Top-level JSON → `neats_json_to_flights` (`neats_io.py:45-46`) → `FleetRunner._load_trajectories`
   (`fleet.py:561-566`) and `scripts/run_json.py:238-240`.
2. Expected: the AO schema's `anyOf` allows one object. Observed: iterating a dict yields its
   keys, so `'str'.get` raises `AttributeError` and aborts the whole run (high confidence,
   snippet). The list-only contract is stated in the function's type and docstring and in
   `input-format.md:3-11`.
3. A single-object upload fails completely. There is no numerical effect.
4. Likely, if the application always wraps uploads in a list.
5. **Convert in PyNEATS** (wrap a `Mapping` in a list at the file-reading entry points), or
   document that the array form is required.

**D2. Trajectory timestamp offsets discarded; some valid forms rejected.**
1. `ts` → `neats_io.py:61-68` → `neats_parser.py:233-242`.
2. Expected: every RFC 3339 `date-time` maps to the same instant in UTC. Observed:
   - `strptime('%Y-%m-%dT%H:%M:%S%z')` followed by `strftime('%Y-%m-%d %H:%M:%S')` **drops**
     the offset without applying it. `2025-11-02T12:02:00+02:00` becomes 12:02 UTC instead of
     10:02 UTC.
   - Fractional seconds and a lowercase `z` are schema-valid but raise `ValueError`.
   - Nothing catches the error, so it aborts the batch before per-flight error handling.
   - `Z`, `+0000` and `+00:00` are handled correctly. Every `ts` in the tests uses `+0000`.
   High confidence (snippets).
3. A non-zero offset shifts every waypoint by the offset. Meteorology and radiation are then
   sampled at the wrong time, and CoCiP day or night can flip. A schema-valid fractional
   second aborts every flight in the batch. Schema-conformant UTC input is unaffected.
4. Possibly, if the application normalises `ts` to whole seconds with `Z` or `+0000`.
5. **Convert in PyNEATS**: parse with `pd.to_datetime(..., utc=True, format='ISO8601')` or
   `datetime.fromisoformat(...).astimezone(timezone.utc)`. Also **clarify the AO template**:
   UTC only, whole seconds.

**D3. Fuel flow derived from `am` is misaligned in time.**
1. `am` → `_derive_fuel_flow_from_mass_if_needed` (`bada_model.py:705-749`). It runs when `am`
   is present and `ff` is absent.
2. Expected (docstring and comment): ff[i] = −(m[i+1] − m[i]) / Δt[i]. Observed:
   `np.diff(mass, prepend=mass[0])` gives m[i] − m[i−1], divided by the **forward**
   Δt[i] = t[i+1] − t[i]. So ff[0] = 0, the last value is NaN, and every rate sits one sample
   late. High confidence. Units are consistent (kg/s, whole aircraft).
3. On a uniform 60 s grid, rates lag by one sample, and Σ fuel_burn = m[0] − m[n−2], so the
   last segment's burn is lost. Where spacing is non-uniform (rows removed by the speed
   filter, or a non-default `interpolation_time`), each rate is off by Δt[i−1]/Δt[i]. This
   affects `fuel_flow`, `fuel_burn`, emissions and the guardrail total. It does not affect
   `engine_efficiency`, which uses BADA fuel flow.
4. No.
5. **Convert in PyNEATS**: use `-np.diff(mass, append=np.nan) / segment_duration`, computed
   before the speed filter or with `segment_duration` recomputed after it. Regenerate golden
   files that use `am` without `ff`.

**D4. Partially null optional columns are not filled.**
1. `tas`, `ff`, `ee`, `am` → `neats_io.py:93-94` → `pycontrails_interpolation.py:108-112` →
   `bada_model.py:1046,1071-1076`.
2. Expected: the schema allows `null` per point, and such points should be filled with values
   in the same convention, or the flight rejected. Observed: a column survives unless every
   value is null. `np.interp` spreads NaN to resampled samples between neighbours. A provided
   column is used wholesale, with no per-point BADA fill. NaN `ee` gives NaN SAC slope at
   those points. High confidence.
3. Fuel, CO2 and emission totals (nansum) undercount the affected segments, and the guardrail
   weakens by the same amount. On a 60 s input grid, only the null point itself is affected.
   With 5 min input spacing, about 9 resampled samples are affected per null.
4. Possibly, if the application never sends partial nulls.
5. **Convert in PyNEATS**: fill NaN points of provided columns from the BADA result, or reject
   partial columns.

### Elsewhere in the inspected PyNEATS path (not AO fields)

**O1. Local aCCF H2O: potential vorticity in SI, coefficients in PVU.** This is the most
consequential finding.
1. DWD `pv` → pycontrails `PotentialVorticity` (`weather_factory.py:242`) → `LocalACCFModel.compute_h2o`
   (`local_accf.py:239-240`) → `h2o_raw_formula` (`local_accf.py:228-231`):
   4.05e-16 + 1.48e-16·|pv|. This is the **default** large-emitter non-CO2 model
   (`neats_default_parameters.py:115`).
2. Expected: the CLIMaCCF reference implementation applies this regression to PV in PVU
   (`climaccf/accf.py`: `self.pvu = ds['pv'].values * 1e6`, present since 2022). Matthes et
   al. 2023, Annex A says "PV given in standard PV units [10⁻⁶ K kg⁻¹ m² s⁻¹]". Observed: the
   column is in SI, K m² kg⁻¹ s⁻¹ (pycontrails units; golden |pv| about 1e-7 to 1.3e-5), and is
   used unconverted. High confidence: golden ATR_20_H2O / fuel_burn × 3 equals 4.05e-16 on
   every valid sample, which means the weather has no effect.
3. The missing factor is 1e6 on `pv`. The per-sample H2O aCCF is too small by
   1 + 0.365·|PV_PVU|: about 1.9 times at the golden median and up to about 5.9 times.
   Fuel-weighted per flight, ATR_20_H2O, H2O EAGWP and CO2eq are underestimated 1.59–3.26
   times. EAF2143 H2O CO2eq_20 would rise from about 764 kg to about 2,500 kg. The ClimAccf
   backend does not have this error, because CLIMaCCF converts internally, so the two
   backends disagree.
4. No. PV comes from PyNEATS's own weather path.
5. **Convert in PyNEATS**: multiply by 1e6 inside `compute_h2o`. Do **not** convert in the
   weather layer, because the ClimAccf backend needs SI. Regenerate golden outputs, and add a
   LocalACCF-against-CLIMaCCF regression test.

**O2. Method D `contrails_ef_J` holds an AGWP, not joules.**
1. `gwp.py:426`: `total_ef_J = float(flight.attrs.get("AGWP_20_CONT", 0.0))`, small emitter only.
2. Expected: contrail energy forcing in J, as in Method C (`gwp.py:411`). Observed: the raw
   OpenAirClim 20-yr contrail AGWP in W m-2 yr, with no efficacy and always horizon 20. High
   confidence.
3. A different physical quantity sits under a J-named key. It cannot be converted to energy
   forcing by a fixed factor. Summing or comparing `contrails_ef_J` across Methods C and D
   mixes units. CO2eq is not affected.
4. No.
5. **Change in PyNEATS**: emit null for Method D, or use a separately named field.

**O3. OpenAirClim told the NOx species is NO.**
1. pycontrails NOx mass (`emissions.py:263-273,773`) → inventory `NOx` in kg
   (`open_airclim.py:131,181`) → `src/pyneats/resources/openairclim.toml:10`
   `nox = "NO"` → openairclim `calc_response.py:106-133` (`corr_nox` = 1.0).
2. Expected: the inventory mass is NO2-equivalent. This is the ICAO EDB convention, the
   pycontrails APCEMM interface documents `nox_ei` as kg(NO2)/kg (`models/apcemm/inputs.py:70`),
   and the CLIMaCCF literature uses it. The TOML should then read `"NO2"`, so that openairclim
   applies 30/46 to its per-kg-NO response surfaces (`resp_RF_O3.nc` title "NO Emission → O3
   RF"). Observed: `"NO"`, carried over verbatim from the upstream openairclim demo
   `example.toml`. Medium-high confidence: the NO2 basis is a documented convention, not
   demonstrated by computation.
3. Method D O3 RF and AGWP are exactly 46/30 = 1.533 times too high. CH4 and PMO are about
   1.533 times too high. H2O, CO2 and contrails are unaffected. The local aCCF path is
   consistent: K/kg(NO2) times an NO2-basis EI.
4. Unlikely. The application could pass its own `base_toml_path`.
5. **Change in PyNEATS**: set `nox = "NO2"` (or force it in `_create_worker_toml`) after
   confirming the EDB basis with the method owner. Do not convert `nox_ei`, because that would
   break the aCCF path.

**O4. OpenAirClim metric window pinned to 2025.**
1. Year of the first waypoint → `_create_worker_toml` (`open_airclim.py:94`) sets
   `time.range = [Y, Y+101]`. The bundled TOML keeps `metrics.t_0 = [2025]`
   (`openairclim.toml:98`), and the harvest reads `AGWP_{h}_2025` (`open_airclim.py:251`).
2. Expected: AGWP integrated from the emission year. Observed:
   - Y > 2025: openairclim `_check_metrics` raises `ValueError` (`read_config.py:681-690`),
     and the flight becomes an error record. This covers every 2026 flight.
   - Y ≠ 2025 with the default base inventory: `calc_cont.check_cont_input` also raises.
   - Y < 2025 without a base inventory: silently wrong windows.
   High confidence for the failure. All golden flights are from 2025.
3. With the shipped configuration, Method D works only for flights dated 2025, unless the
   deployment overrides the TOML.
4. Possibly, if the application overrides the TOML. Not visible.
5. **Decide in PyNEATS** (method owner): anchor every flight to the 2025 pulse convention
   consistently (inventory year, base inventory, CO2 coefficients), or set `t_0` and the
   inventory year per flight.

**O5. DWD `sdr` is TOA, and is scaled by 3600 twice on the ClimAccf path.**
1. `weather_factory.py:247` maps DWD `sdr` to `surface_solar_downward_radiation`. `build_cache`
   multiplies by `sdr_accumulate_dt_s` (default 3600) and labels the result J m-2
   (`weather_factory.py:405-411`). `make_accf_surface_view` relabels it W m-2 without
   converting (`climaccf.py:88-93`), and pycontrails ACCF multiplies by 3600 again
   (`models/accf.py:405-423`).
2. Expected: surface downward solar radiation, accumulated once in J m-2. Observed:
   - The store history (`swflx_dn`, "solar incoming radiation at TOA") shows it is **TOA**
     incoming solar.
   - With the default cache settings it is scaled by 3600 twice.
   - The live path and the example cache (dt = None) are scaled once.
   High confidence in the inconsistency.
3. Only the non-default `accf` backend is affected. Whether CLIMaCCF's consumed aCCFs (O3, CH4,
   H2O) read `ssrd` is unverified. CoCiP is not affected: it computes its own TOA insolation.
4. No.
5. **Change in PyNEATS**: keep one stored convention with a matching units attribute, make the
   adapter convert rather than relabel, and stop calling TOA flux "surface".

**O6. DWD `rhi` relabelled from % to 1 without dividing by 100.**
1. `weather_factory.py:522-523`; `_standardize_vars` at `weather_factory.py:588-603`.
2. Expected: values in % are divided by 100 when relabelled to a fraction. Observed: only the
   label changes. `clc`, two lines away, is divided by 100. The source units of the DWD files
   are unverified.
3. If the source is in %, RH is 100 times too large for its only consumer, the non-default
   pycontrails ACCF.
4. No.
5. **Change in PyNEATS**: divide by 100 when the source attribute is `%`.

**O7. OLR renamed to ECMWF `ttr` without a sign change.**
1. `climaccf.py:74-87`.
2. Expected: ECMWF defines ttr = −OLR (pycontrails `datalib/ecmwf/variables.py:174-188`).
   Observed: a rename only, so values stay positive.
3. Non-default backend only. The effect inside CLIMaCCF is unverified.
4. No.
5. Negate on rename, unless the CLIMaCCF source shows it expects positive OLR.

**O8. Weather factory relabels units without converting.** Ambiguity rather than a
demonstrated error.
- `_standardize_vars` overwrites `attrs['units']` with the pycontrails unit after a warning,
  without arithmetic (`weather_factory.py:572-608`).
- The module docstring claimed "automatic unit conversions" (corrected in the patch). The
  only real conversions are:
  - `level` from Pa to hPa (a heuristic on the first element);
  - `clc` divided by 100;
  - SDR multiplied by dt in `build_cache`.
- Any source variable in non-pycontrails units would be mislabelled silently. Source units of
  the DWD files were not available.
- **Recommendation**: raise on mismatch, or convert.

## 8. Further ambiguities in outputs and methodology

- **O9. Low-altitude zero results.** A flight rejected for never reaching 550 hPa reports
  NaN fuel and CO2 baselines but 0.0 EAGWP and CO2eq for every species, **CO2 included**
  (`fleet.py:295-319`). This is intentional and pinned by tests
  (`tests/test_zero_climate_result.py`). Summing `CO2eq_kg` across flights undercounts
  CO2. **Document** the semantics in `output-format.md`, or reconsider zeroing CO2.
- **O10. Method C silent species drop.** A conversion exception or a missing ATR column drops
  a species without an error record (`gwp.py:216-217,239-240`). Partial overrides of the
  k-factor, efficacy or `rf_backward` tables fall back to a scale of 1.0 (`gwp.py:155-165`).
  An H2O entry missing from `k_atr` would be off by a factor of 31. This is reachable only with
  non-default parameters.
- **O11. `FlightView.to_dict` encodings.** `time` is integer Unix seconds, truncated rather
  than rounded as the old comment said. `contrail_age` is integer **nanoseconds**. Both are
  now documented in the docstring. They apply to golden-file dumps, not to `runner.results`.
- **O12. Performance-only output.**
  - `true_airspeed` is in m/s, not the AO's knots.
  - `timestamps` carry no offset (naive UTC); the docstring example showed `+00:00` and was
    corrected.
  - Multi-engine copies are not merged.
  - **Document**, or emit `Z`.
- **O13. Totals limited to the met domain.** `total_nox`, `total_co`, `total_hc` and
  `total_nvpm_*` sum only waypoints inside the met domain (default 550–140 hPa). EIs are NaN
  elsewhere. `total_co2` and `total_h2o` cover every segment. For EAF2143, 31.8 % of the
  flight's fuel lies outside the domain. The OpenAirClim NOx inventory fills those NaN with 0,
  while CO2 and H2O stay complete, so one inventory mixes two bases. **Document** the basis,
  or decide on fallback EIs.
- **O14. PMO merged into CH4.** PMO takes CH4 efficacy and conversion factors in both methods
  (`open_airclim.py:264-266`; `local_accf.py:221-222`). `EFFICACY['PMO']` and the PMO
  conversion-factor columns are unused. The effect is about +0.9 % on the combined CH4+PMO
  EAGWP in Method D. **Clarify** with the specification owner.
- **O15. ClimAccf `unit_K_per_kg_fuel=True`.** CLIMaCCF would substitute its own fleet-mean
  NOx EI (0.013), or apply no conversion when `merged=False`. The default is False. **Reject**
  True in `ACCFParams`, or document it (done in the patch).
- **O16. RF-backward coupling.** `RF_BACKWARD_FACTOR` is approximately
  1/`ACCF_SCALE_*['V1.0']`. That is documented intent (`physics.py:92-97`;
  `mrv-specification.md:310`) with at most 0.16 % rounding mismatch. It is not a discrepancy,
  and the coupling is now stated in a comment.

## 9. Documentation and schema inconsistencies (reported, not edited)

The patch corrected wrong unit statements in **code comments and docstrings**: the items
marked "corrected" below and those listed in Section 11. Markdown documents and JSON schemas
were left unchanged on purpose, because the scope excludes schema changes and fixes to
discrepancies:

| Location | Statement | Code or demonstrated convention | Action |
| --- | --- | --- | --- |
| `docs/reference/input-format.md:43`; `scripts/schemas/flight_schema.json:94-96` | `hydrogen_content` is a "mass fraction (0–1)" | wt.% (13.79). A caller sending 0.138 gets `ei_h2o` 100 times too low | fix docs |
| `scripts/schemas/flight_schema.json:106-109` | `calorific_value` in MJ/kg | J/kg (golden inputs validated by this schema hold 4.1944e7) | fix schema text: PyNEATS input is J/kg after the application's × 1e6 |
| `docs/explanation/mrv-specification.md:233-238` | H/C is a "molecular mass ratio"; formula without × 100 | atomic ratio; × 100 to give wt.% | fix spec |
| `docs/explanation/mrv-specification.md:220` | no BADA correction when `q_fuel` is not provided | correction always applied (A11) | decide, then align |
| `docs/explanation/mrv-specification.md:264,277,302` | EAGWP and AGWP in W m-2 | W m-2 yr | fix spec |
| `docs/explanation/mrv-specification.md:272` | s_yr = 31,536,000 s | 31,556,952 s (`physics.py:58`); contrail EAGWP differs by 0.066 % | decide which year length, then align |
| `docs/explanation/mrv-specification.md:284-286` | C(H) = 24.16 / 47.57 / 74.36 e-15 | 24.12 / 47.50 / 74.24 e-15 (commit `bf3aa7b`, newer); CO2eq differs by about 0.15–0.17 % | update spec |
| `docs/reference/output-format.md` | per-segment `flight_results`; `climaccf_version`; error-record keys; "fleet totals" | `runner.results` holds flight-level entries; the keys differ; `total_*` are per-flight; no units are given | rewrite with a units table |
| `docs/reference/input-format.md:85-113` | minimal example at FL 4 and FL 10 | rejected by the 550 hPa guard | use cruise levels |
| `docs/howto/usage.md:85-90,112,168-169`; `docs/reference/example-scripts.md:11` | `ZarrPaths(met_path=…)`, `DWDFactory(...).build()`, "fuel flow & thrust" | `met_store`/`rad_store`, `__call__(asofdate, hour)`, no thrust output | fix docs |
| `examples/README.md:140` | `engine_efficiency` = "engine thermal efficiency" | overall propulsion efficiency | fix docs |
| `scripts/schemas/flight_schema.json:102-116`; `docs/reference/input-format.md` | aromatics and naphthalene as "mass fraction" | volume basis per MRR Annex IIIa §5(4) and ReFuelEU (the pre-NEATS SAD draft said mass); scale undefined | align with the law once the scale is decided |
| `scripts/schemas/flight_schema.json:38,43`; `docs/reference/output-format.md:50`; `report.py` | departure = "AOBT", arrival = "AIBT" | AO schema: Item 13 = EOBT; arrival event undefined | relabel neutrally ("departure time as supplied") |
| `docs/internal/performance_use_cases_analysis.md` | TAS always recomputed; early exit on FF+EE; FF never derived from mass | TAS kept when provided; early exit needs FF+EE+AM; FF derived from AM | mark superseded |
| `scripts/parquet_to_neats_json.py` | treats `altitude` as feet and stamps `+0000` without converting | basis (barometric or geometric) and time zone unverified | document expected input |
| `tests/test_performance_fallback.py:4,74,80`; `tests/test_guardrails.py:133,142,151` | FL15; 500 hPa | FL20; 550 hPa | update test docstrings |

## 10. Incidental observations outside the unit scope

These affect how the audited fields are consumed but are not unit issues. They are reported
for a separate decision and were not fixed.

- **I1. BADA4 speed filter never runs.** `BADA4Adapter.v_stall_cas` calls
  `VStall(mass=, config=)`, but the pyBADA 0.1.12 BADA4 signature is
  `VStall(mass, HLid, LG, nz=1.0, **kwargs)` (`bada_adapters.py:175-180`; pyBADA
  `bada4.py:2349`). The `TypeError` is swallowed (`bada_model.py:463-469`), so taxi and
  low-speed points stay in for BADA4 aircraft. The unit tests mock `VStall`.
- **I2. Naphthalene key mismatch.** `neats_io` emits `naphthalene`, `Flight4D` allows
  `naphtalene`, and `NEATSFuel.from_attrs` reads `naphthalene`. The AO value and the airport
  value both fail to reach the fuel object.
- **I3. Zero values replaced.** `NEATSFuel.from_attrs` uses `or` between alternative keys, so
  an explicit `sulphur_content` of 0.0 becomes the default 0.003 on the fuel object.
- **I4. BADA3 MPL hidden.** `BADA3Adapter.MPL` returns `None` with the comment "BADA3 has no
  MPL attribute". pyBADA 0.1.12 `Bada3Aircraft` does set MPL (OPF maximum payload × 1000 kg,
  `bada3.py:396-405`). BADA3 flights therefore estimate ZFW with pf × (MTOW − OEW), which is
  heavier than pf × MPL. The comment was corrected; the behaviour was not changed.
- **I5. Parser `timezone` parameter has no effect.** pycontrails stores time as naive UTC
  (`vector.py:2162-2167`). The docstrings were corrected.
- **I6. Outputs not strict JSON.** `scripts/run_json.py` writes no output. Golden JSON
  contains bare `NaN` and `Infinity` tokens (28,945 and 318 in `fleet_5_flights_output.json`).
- **I7. `fleet_to_flights` docstring.** It said fuel is rebuilt from the Fleet columns; it is
  rebuilt from attrs (corrected).
- **I8. Humidity-scaling adapter fallbacks.** The fallback branches rebuild `Flight` without
  its fuel (`weather_provider.py:139-147`). They are unreachable with stock pycontrails.

## 11. Patch summary and checks performed

**Files modified.** Comments and docstrings were added or corrected in 27 source files (+826/−178 lines). New
file: `docs/internal/pyneats_units_audit.md` (this report).

- Input boundary and parsing: `steps/parsing/neats_io.py` (a field-by-field unit mapping in
  the `neats_json_to_flights` docstring, the two upstream-conversion comments, the `ts`
  offset behaviour), `neats_parser.py` (FL → m pressure altitude; UTC parsing; corrected the
  no-op `timezone` docstring; airport-file units), `views.py` (units of every Flight4D
  column and attr), `params.py` (corrected 500 hPa → 550 hPa ≈ FL160).
- Fuel and constants: `core/neats_fuel.py` (wt.%, atomic H/C, J/kg template, fixed JetA
  EIs), `core/neats_default_parameters.py` (units of every constant; corrected FL15 → FL20
  and 1.1/10 % → 1.2/20 %; `REFERENCE_Q_FUEL` is the pycontrails JetA value, not a BADA
  value), `core/physics.py` (year length and C(H) against the spec; conversion-factor
  direction and unverified absolute units), `core/fleet_utils.py` (fuel rebuilt from attrs),
  `core/views.py` (`to_dict` time and timedelta encodings), `core/compute_parameters.py`.
- Performance: `steps/performance/bada_model.py` (parameter units and meaning; TAS template;
  q_fuel correction; the mass-derived fuel-flow comment now describes the actual backward
  difference; fuel-flow provenance), `bada_adapters.py` (adapter units; the BADA4 `VStall`
  signature; the corrected BADA3 MPL comment), `speed_filter.py`, `altitude_filter.py`,
  `steps/interpolation/pycontrails_interpolation.py`.
- Climate and outputs: `steps/climate_functions/local_accf.py` (input-column units; the PV
  SI-versus-PVU note; NOx as NO2), `climaccf.py`, `open_airclim.py` (inventory units, NOx
  species, `t_0`), `climate_functions/views.py`, `steps/climate_metrics/gwp.py` (output
  units; the Method D `contrails_ef_J` note), `climate_metrics/report.py`,
  `climate_metrics/views.py`, `steps/emissions/views.py` (per-segment masses, EIs, totals
  basis).
- Runners and weather: `runners/fleet.py` (`FleetRunnerParams` input units, the
  `runner.results` shape with units), `runners/flight.py` (the `source` DataFrame
  contract), `runners/performance_runner.py` (output units; corrected the timestamp
  example), `steps/weather/weather_factory.py` (corrected the "automatic unit conversions"
  claim; the `rhi`, `sdr`, `pv` and time-window notes).

The two upstream conversions are documented with the requested template at the JSON
boundary (`neats_io.py`), at the `q_fuel` definition (`NEATSFuel`) and where TAS enters
the performance model (`bada_model.py`). The runner entry points reference them in their
docstrings.

**Checks performed.**

- **AST equivalence.** For every modified `.py` file, the AST of the working copy with
  docstrings removed was compared with that of `HEAD`: 27 of 27 files are identical. The
  checker was first tested on purpose-made edits: it passes a docstring or comment change
  and flags a one-token code change. This is the evidence that computational behaviour is
  unchanged.
- **`uv run ruff check src/ tests/`**: all checks passed (baseline: passed).
- **`uv run ruff format --check src/ tests/`**: 84 files already formatted (baseline: same).
- **`uv run mypy src/pyneats/`**: no issues in 65 source files (baseline: same).
- **`make test-unit`** (tests without BADA or weather data): 150 passed, 1 skipped,
  4 xfailed, 103 deselected. The deselected tests need BADA or weather data, which is not
  available here, so they were not run.
- **`git diff`** was read in full. Repeated template blocks were trimmed, and one unrelated
  docstring fix was reverted to keep the patch to units.

**Regulatory research (Section 6.0).** One researcher per question, each followed by two
independent verifiers. One verifier checked source fidelity by re-opening every cited source;
the other checked applicability and looked for contradicting sources. No finding was refuted.
Their corrections (citation pages, a missed guidance table, a superseded SAD draft, the
OpenAirClim v0.19.0 change) are incorporated above. After the research, the code comments
for `ff`, `ee`, `load_factor`, `hydrogen_per_carbon_ratio`, `takeoff_mass`, the
aromatics/sulphur/naphthalene basis and the EOBT label were updated to cite MRR Annex IIIa,
and the checks above were re-run. Not searched: PyNeats GitHub issues and PRs (`gh` is not
installed here), and the NEATS User Group SharePoint (login required).

**Not done.** No pipeline, BADA, CoCiP or OpenAirClim calculation was run. No new tests were
added. Numerical equivalence is established by the AST comparison (no code changed). It is not
established by running tests.
