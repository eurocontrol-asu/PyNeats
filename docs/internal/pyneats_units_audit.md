# PyNEATS unit audit against the AO upload schema

Reviewed revision: `f7502fe6344e5e085df1042ac817f02a05bd100d` (`origin/main`, 2026-10-13),
on branch `docs/units-audit`. Every `file:line` reference below points to that revision,
before the comment patch was applied. The patch moves lines in the files it touches.

## Follow-up status

The findings below are the audit as written. Each fix updates this table and adds a status
note under its item. Items not listed here are open. Rows and items added after the audit
cite line numbers on `dev` before the fix they describe.

| Item | Status | Branch / PR | Date |
| --- | --- | --- | --- |
| D2 (trajectory `ts` offsets) | Fixed | #70 | 2026-10-20 |
| One flight that cannot be converted no longer stops the run (D2 follow-up) | Fixed | #71 | 2026-10-20 |
| D1 (bare single-flight object) | Open; now a clear `TypeError` on the `FleetRunner` JSON path | #71 | 2026-10-20 |
| I4 (BADA3 maximum payload) | Fixed; changes BADA3 fuel and CO2 | #73 | 2026-10-21 |
| Fuel reserve and number of mass iterations misstated in the user docs (Section 9) | Fixed (docs only) | #74 | 2026-10-21 |
| Performance input decision tree and data-sources table in the user docs (Section 9) | Fixed (docs only) | #75 | 2026-10-21 |
| A13 (mixed fuel-flow provenance) | Documented in the user docs; the design choice stays open | #75 | 2026-10-21 |
| I9 (`segment_duration` not recomputed after the speed filter) | Recorded in #75; fixed on `fix/airspeed-trust` (see the I1, I9 and I14 row below) | #75 | 2026-10-21 |
| I10 (a failed attempt leaked columns into the BADA3 retry) | Fixed; fuel-burn rejections go through the BADA3 retry and the altitude fallback (maintainer decision); no change on the NEATS_FINAL sample | `fix/performance-retry-isolation` | 2026-10-21 |
| A10 (airport fuel file units) and the missing `q_fuel` magnitude check | Fixed: a supplied `q_fuel` outside 35–50 MJ/kg is rejected (flight fails; a wrong airport file stops the run); no change on valid inputs | #77 | 2026-10-22 |
| I11 (fleet step cache shared between runners in one process) | Fixed; no change for a single run | #78 | 2026-10-22 |
| D3 (fuel flow derived from `am` one point late) | Fixed; changes fuel, emissions, contrail and climate results only for flights with `am` and no `ff` | `fix/mass-derived-fuel-flow` | 2026-10-22 |
| A11/A12 (fuel energy reference of the BADA fuel flow) | Fixed: reference = BADA4 LHV 43.217 MJ/kg for BADA4 and BADA3 (maintainer decision); docs corrected; fuel and CO2 +0.21 % on the sample | `fix/fuel-energy-reference` | 2026-10-22 |
| I12 (FlightRunner and FleetRunner give different contrail results for the same flight) | Open; recorded; contrail-based values get rtol 5e-3 in the FlightRunner golden test | `fix/fuel-energy-reference` | 2026-10-22 |
| D4 (partially empty AO columns) | Fixed: empty values skipped when resampling (straight line between valid neighbours; maintainer decision); no change on the NM sample | `fix/partial-null-columns` | 2026-10-22 |
| I13 (a non-finite BADA fuel flow made the mass NaN for the rest of the flight) | Fixed: treated as a BADA failure at that point (previous point's values; maintainer decision); fleet fuel +0.005 %, 5 flights change | `fix/bada-nonfinite-fuel-flow` | 2026-10-23 |
| I1 (BADA4 speed filter never runs), I9 (`segment_duration` not recomputed after the speed filter) and I14 (TAS compared with a CAS stall speed) | Fixed by replacing the low-speed filter with an airspeed trust step: no row removed and no output column added; untrusted TAS (not finite, CAS below the stall CAS at MTOW, take-off configuration, CAS above the BADA VMO (400 kt without one), Mach ≥ 1) interpolated in time, and before the first and after the last trusted row given the CAS of that row; decided and filled on the unsmoothed TAS, re-smoothed only within the smoothing window of an untrusted row; BADA4 stall call fixed; flight fails (no retry) above 80 % untrusted time, except when the AO provides fuel flow, engine efficiency and aircraft mass (maintainer decisions). NM sample 2025-07-09, with I13 and the VMO limit: fleet fuel −0.77 % against `dev` (BADA4 −1.10 %, BADA3 +1.26 %), CO2 = 3.159 × fuel on all 4,303 flights, no new failure; golden outputs regenerated | `fix/airspeed-trust` | 2026-10-23 |
| Golden test totals (`assert_climate_payload_equal`): a NaN actual value passed, because every comparison with NaN is False | Fixed: NaN and inf must match exactly; no golden file changed. Still open: per-point columns are compared with `atol=inf`, and CI runs no golden test (`requires_weather`) | `test/golden-nan-check` | 2026-10-28 |
| OpenAirClim temp folder (`tmp_base_dir_path`) never created: with a missing folder every small-emitter flight failed at the last step | Fixed: the small-emitter runners create the folder at start-up and stop there, naming the path, if it cannot be written to; the model also creates it before each run. No change in results | `fix/openairclim-tmp-dir` | 2026-10-28 |
| O4 (OpenAirClim metric window pinned to 2025; every flight dated 2026 failed) | Fixed: every flight is emitted in one reference year, `OPEN_AIRCLIM_REFERENCE_YEAR` = 2025 in `neats_default_parameters.py` (inventory year, `metrics.t_0`, `time.range`, result key); the same flight gives the same result whatever its date (maintainer and method-owner decision). Flights dated 2025: results bit-identical | `fix/openairclim-reference-year` | 2026-10-28 |
| O14 (PMO merged into CH4 with the CH4 efficacy and factors) | Fixed: PMO is computed apart (Method C: `ATR_20_PMO` = 0.29 x `ATR_20_CH4`, no x1.29 on CH4; Method D: `AGWP_{H}_PMO` stored apart) with its own efficacy (1.0, RSTS value confirmed by the method owner), RF backward factor (0.492, CH4 value) and Dahlmann factors, then added into the `CH4` entry before the guardrail; output keys unchanged (maintainer and method-owner decision, Option A). A species without an efficacy, RF backward or conversion factor now raises instead of using 1.0. Golden outputs not yet regenerated | `fix/pmo-separate-efficacy` | 2026-10-28 |
| A1 (no fuel check when the AO provides fuel flow, engine efficiency and aircraft mass; a fuel flow in kg/h was accepted) | Fixed: the fuel-burn guardrail (total fuel <= 1.2 x (MTOW - OEW)) also runs on that path; its rejection is final (no BADA3 retry, no altitude fallback) and its message says the AO fuel flow must be in kg/s (maintainer decision). Valid inputs unchanged | `fix/ao-fuel-flow-check` | 2026-10-28 |
| O1 (local aCCF H2O: potential vorticity in SI, regression in PVU) | Fixed: `LocalACCFModel.h2o_raw_formula` converts PV from SI to PVU (`PVU_PER_SI` = 1e6 in `physics.py`) before the regression, as CLIMaCCF does; the weather layer still supplies SI, which the ClimAccf backend needs (maintainer and method-owner decision). Measured on the NM sample 2025-07-09 (4,683 flights with climate results, against `dev` d239aa2): H2O CO2eq × 2.17, total CO2eq +2.18 % (H20), +1.86 % (H50), +1.56 % (H100); fuel, CO2 and the other species bit-identical. H2O now agrees with CLIMaCCF within 0.33 % on the 5 golden flights. Golden outputs regenerated: only H2O values change (`ATR_20_H2O`, H2O EAGWP and CO2eq) | `fix/accf-h2o-pv-units` | 2026-10-28 |
| A13 (mixed fuel-flow provenance) | Fixed: when the AO provides `ff` without `am`, the mass decreases with the AO fuel flow, from the AO TOM or from min(MTOW, OEW + payload_factor x MPL + 1.15 x AO trip fuel) (no iteration); the fuel-burn guardrail runs on the AO fuel flow before that, and its rejection is final (maintainer and method-owner decision). Fuel and CO2 unchanged; mass profile, computed `ee` and contrails change for these flights; flights with `am` or without `ff` unchanged; golden outputs regenerated (contrail EF −0.12 % to +0.07 %) | `fix/mass-from-ao-fuel-flow` | 2026-10-28 |
| A3 (`load_factor` not range-checked: 1.5 or 80 gave more fuel without a warning, −0.5 a take-off mass below OEW) | Fixed: 0–1 kept unchanged (0 = ferry flight); above 1 set to 1.0 with a warning naming the flight and the value, not divided by 100 (DLR TC_LF_GT_ONE; in `neats_json_to_flights` for JSON input and in the parser for DataFrame input); negative fails the flight at parsing (no retry; other flights go on), as an out-of-range `q_fuel` does (maintainer decision). `None` and NaN unchanged. Valid inputs unchanged; no golden result changes | `fix/load-factor-range` | 2026-10-29 |
| A6 PR 1 (`takeoff_mass` dropped without notice when the AO provides `am`; the warning meant for it could not be reached) | Fixed: one WARNING per flight, naming the flight and both masses, when `am` overrides a `takeoff_mass` that differs from the first `am` by more than max(1000 kg, 2 %), on every path where `am` wins (the early exit with `ff`, `ee` and `am` included; once across the BADA3 retry and the altitude fallback, and once for a flight with a list `engine_uid`); smaller differences and a missing or non-finite `takeoff_mass` stay at DEBUG or silent; the output attr `takeoff_weight` still shows the AO value; the unreachable warning in `_single_pass_performance` is now a DEBUG line, its safety net kept (maintainer decision: warning only). No number changes; no golden result changes. Still open: range check against OEW/MTOW (PR 2) | `fix/takeoff-mass-ignored-warning` | 2026-10-29 |
| A6 PR 2 (`takeoff_mass` never range-checked: 10,000 kg on an A330 or 999,999 kg on a B737-800 gave a result without a word) | Fixed: a finite `takeoff_mass` below OEW or above 1.05 x MTOW of the BADA model of the first attempt (of the BADA3 retry when the BADA4 model does not load) fails the flight with a non-retryable error (no BADA3 retry, no altitude fallback) naming the flight, the value, the bound and the BADA model; checked before the early exit with `ff`, `ee` and `am`, so it applies with or without `am`; a missing, NaN or non-numeric `takeoff_mass` is not checked (maintainer decision: 5 % margin, so the golden UAE62Y B77W at +2.0 % above the BADA4 MTOW stays valid). In-range values: no number changes, the A6 PR 1 warning unchanged. Golden: `ACA812__tc_mass_below_oew` and `RYR46YN__tc_tom_exceeds_mtow` become error records; the two DLR strict xfails are removed. Still open: `aircraft_mass` above MTOW (`tc_mass_exceeds_mtow`) | `fix/takeoff-mass-range` | 2026-10-30 |
| C.16 (CO2 AGWP coefficients C(H) and seconds per year differ between the code and the MRV specification, Section 9) | Fixed: the code uses the specification values, C(H) = 24.16 / 47.57 / 74.36 e-15 W m-2 yr kg-1 (was 24.12 / 47.50 / 74.24 e-15 from commit `bf3aa7b`) and s_yr = 31,536,000 s = 365 d (was 31,556,952 s = 365.2425 d); the specification is unchanged (maintainer and method-owner decision, 2026-10-28: "use the DOC values"). CO2 CO2eq unchanged (= total CO2); CO2 EAGWP x new/old C(H); non-CO2 CO2eq x old/new C(H) (0.99834 H20, 0.99853 H50, 0.99839 H100); Method C contrail EAGWP x 1.000664 (31,556,952 / 31,536,000), Method D contrail EAGWP unchanged. NM sample 2025-07-09, computed from the per-species results of `fix/accf-h2o-pv-units` (Method C, 4,683 flights): total CO2eq −0.125 % (H20), −0.092 % (H50), −0.085 % (H100); Method D, from the results of the #69 branch commit `4edb866` (4,683 flights): −0.124 %, −0.086 %, −0.065 %. Golden outputs regenerated: only these climate values change | `fix/doc-climate-constants` | 2026-10-30 |

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
    coefficients are defined for PVU. The H2O term lost all sensitivity to the weather, and
    H2O ATR was underestimated 1.6–3.3 times per golden flight (fixed, see O1 point 6).
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
| `aircraft_properties.load_factor` | "unitless", [0, 1]; basis not stated | attr `payload_factor`, fraction | ZFW = OEW + pf × MPL in kg, or pf × (MTOW − OEW) when MPL is unavailable, which was always the case for BADA3 before the I4 fix | rename only. Default 1.0. Not clipped | **Consistent**: defined by MRR Annex IIIa §1(32) as a fraction of maximum payload mass; default 1 per §5(2)(b) (A3) | `neats_io.py:113`; `bada_model.py:963-980`; `neats_default_parameters.py:141-143` *(demonstrated)*; `flight_schema.json:78-81` "payload / max-payload ratio" *(stated)* |
| `fuel_properties.hydrogen_content` | "percentage of hydrogen mass content", 0.01 resolution | wt.% (for example 13.79) | wt.%. Scales `ei_h2o` = 1.23 × (wt.% / 13.8) kg/kg | none | **Consistent** | `neats_io.py:115`; `core/neats_fuel.py:81-82,106`; pycontrails `core/fuel.py:53` (JetA 13.8); golden inputs 13.79 *(demonstrated)*. PyNEATS docs that say "fraction" are in Section 9 |
| `fuel_properties.hydrogen_per_carbon_ratio` | "unitless"; atomic or mass basis not stated | attr `h_c_ratio`, treated as an **atomic (molar)** H/C ratio | converted to wt.% H = 100 · r·1.008 / (12.011 + r·1.008); used only when `hydrogen_content` is absent | conversion in `NEATSFuel.__init__` | **Consistent**: MRR Annex IIIa §1(36) defines it as the number of H atoms per C atom (A4) | `neats_fuel.py:83-87`; range check: atomic [1.9061, 2.1857] maps exactly to [13.79, 15.50] wt.% (`tests/test_cases_pipeline.py:1492-1516`, mapping recomputed by the auditor) |
| `fuel_properties.aromatic_content` | "unitless"; scale and basis not stated | attr `aromatic_content`, stored | not used in any calculation | none | **Not consumed**. Volume basis per MRR §5(4) default; JSON scale undefined (A5) | `neats_io.py:117`; `neats_fuel.py:94-96`; default 0.25 commented as 25 % (`neats_default_parameters.py:300-302`) *(stated)* |
| `fuel_properties.calorific_value` | MJ/kg of fuel | attr `q_fuel`, **J/kg** (lower heating value) | J/kg in pycontrails `Fuel.q_fuel` and in the BADA fuel-flow correction ratio | × 1e6 in the **NEATS application** (owner-confirmed, not inspected). PyNEATS performs no conversion | **Known difference handled upstream** | `neats_io.py:118`; `neats_fuel.py:92`; `neats_default_parameters.py` (`REFERENCE_Q_FUEL` 43.217e6 since A12, was 43.13e6; `DEFAULT_Q_FUEL` 42.8e6); `bada_model.py:765-771,841,875`; golden inputs 4.1944e7 *(demonstrated)* |
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
| Airport fuel-property file (`airport_fuel_path`) | Not defined by AO upload schema | `float()` only. `q_fuel` assumed J/kg; `h_c_ratio` used as atomic | J/kg, wt.% after `NEATSFuel` | **none**. PyNEATS reads the file directly, so the application's × 1e6 does not apply to it | **Checked**: 35–50 MJ/kg in J/kg enforced at load (A10, fixed) | `neats_parser.py:35-41,44-120,284-296`; `tests/test_airport_qfuel.py` (J/kg) |
| Default branch: no `calorific_value` | Not defined by AO upload schema | `DEFAULT_Q_FUEL` = 42.8e6 J/kg | the BADA fuel flow is multiplied by 43.217/42.8 = 1.0097 (43.13/42.8 = 1.0077 before A12) | correction ratio in `BADAPerformanceModel` | **Resolved**: the correction always applies and the spec now says so (A11) | `neats_fuel.py:92`; `bada_model.py:565-571,764-772,841,875`; `docs/explanation/mrv-specification.md:220` *(stated)* |
| `REFERENCE_Q_FUEL` against BADA4 LHV | Not defined by AO upload schema | 43.217e6 J/kg, the BADA4 4.2.1 LHV (was 43.13e6, pycontrails JetA) | — | checked against every mapped BADA4 file by a test | **Resolved** (A12) | `neats_default_parameters.py:315-317`; pyBADA `bada4.py:1855-1874`; pyBADA dummy BADA4 files: 43.217e6 and 43.71e6 J/kg |
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
- **No magnitude check.** PyNEATS did not check the size of `q_fuel`. On the BADA path,
  42.8 (MJ/kg) failed through the 100 kg/s fuel-flow outlier check with a message that does
  not name the fuel value. When `ff`, `ee` and `am` are all provided, BADA is skipped and the
  value reached SAC/CoCiP silently. *Fixed (see A10): a supplied `q_fuel` outside 35–50 MJ/kg
  now fails the flight at parsing, on every path.*

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
| `load_factor` | "the weight of passengers, cargo and baggage, including mail and hand luggage, expressed as fraction of the maximum payload mass"; maximum payload "can be retrieved by the applied fuel burn module"; default 1 | §1(31), §1(32), §5(2)(b); SAD and RSTS "fraction of the maximum payload mass, e.g., as defined in BADA" | matches (ZFW = OEW + pf·MPL) | none for the definition. §1(3) also uses "load factor" in the aerodynamic (g-load) sense, so the template should name the payload meaning explicitly. For BADA3, PyNEATS used MTOW − OEW instead of MPL (I4, fixed) |
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
   - when `ff`, `ee` and `am` are all present, every check was skipped (`bada_model.py:471-477`;
     the guardrail runs there since the A1 fix, see point 6).
4. Possibly. The application might normalise `ff`, but nothing confirms it.
5. **Clarify the AO template**: "total fuel flow of the aircraft, all engines, kg·s⁻¹". No
   conversion is needed if AOs send the total. Optionally, apply the existing fuel-burn
   guardrail on the early-exit path as well, so a kg/h value fails loudly.
6. **Resolution (2026-10-28).** The fuel-burn guardrail now runs on the early-exit path too
   (`_check_total_fuel_burn`), and its rejection there is final. Golden flight EAF2143 (A320)
   with its AO fuel flow x3600: before, accepted with 13,531,792 kg of fuel; now rejected
   ("... exceeds useful payload capacity 38000 kg x 1.2 = 45600 kg (fuel flow provided by the
   aircraft operator: it must be in kg/s ...)"). As given: unchanged (3,759 kg). A per-engine
   fuel flow (x0.5) or g/s (x0.001) is still not caught: both are underestimates.

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
   fuel change. For BADA3 aircraft the basis was MTOW − OEW rather than MPL until the I4 fix.
4. Possibly. The application might convert a seat load factor.
5. **Clarify the AO template**: "payload mass ÷ maximum payload, fraction 0–1; not a seat load
   factor".
   - *Range fixed on `fix/load-factor-range` (maintainer decision, 2026-10-29; see the
     follow-up status table). `NeatsTrajectoryParser` checks `payload_factor` on every input
     path (AO JSON, `FlightRunner` and `FleetRunner` DataFrame input): 0–1 is kept unchanged
     (0 is a ferry or positioning flight); above 1 is set to 1.0 with the warning
     "Flight <id>: payload_factor (AO load_factor) <value> is above 1; using 1.0"
     (`clamp_payload_factor`, also applied in `neats_json_to_flights`, as the DLR test
     TC_LF_GT_ONE expects); a negative value fails the flight at parsing with
     "payload_factor (AO load_factor) = <value> is negative. ...", which is final (parsing
     has no retry) and, in a fleet, an error record while the other flights go on. A value
     that is not a number (e.g. "full") also fails at parsing; a numeric string (e.g. "0.8")
     is stored as a float. `None` gives the default 1.0 and NaN (or `pd.NA`, stored as NaN)
     the default with a warning in the performance step, as before. A value of 80 (a
     percentage) is set to 1.0, not divided by 100. The two TC_LF_GT_ONE tests no longer
     xfail. Golden results unchanged: the only golden flight with a value above 1
     (`ACA812__tc_lf_gt_one`, 1.5) also has `takeoff_mass`, so its factor is not used; its
     stored `payload_factor` attribute (1.5) is not compared by the golden tests.*

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

**A6. `takeoff_mass`: point of application and precedence.** *Definition settled (§6.0): mass at the beginning of the take-off run, MRR §1(29). PyNEATS's point of application does not guarantee that event (see below).* *Warning when `am` overrides a different `takeoff_mass` added in A6 PR 1; range check against OEW and 1.05 x MTOW added in A6 PR 2 (see the follow-up status table).*
1. `takeoff_weight` → `_choose_mass_strategy` / `_single_pass_performance`
   (`bada_model.py:786-808,849`).
2. The unit is kg and consistent. It is applied at the first **retained** trajectory point:
   - after resampling to 1 min;
   - for BADA3 aircraft, after the speed filter (`dev`; no row is removed on
     `fix/airspeed-trust`);
   - on the altitude-fallback path, at the first point at or above FL20.
   It is ignored, with only a debug log, when an `am` column exists, and nothing checks it
   against `am[0]`. It is not clipped to MTOW. (A6 PR 2: a value below OEW or above
   1.05 x MTOW now fails the flight.)
3. Ground or taxi points before rotation are charged against it. On the FL20 fallback, the
   climb fuel below FL20 is never subtracted. Conflicting `am` and `takeoff_mass` pass without
   notice.
4. Possibly, if the application trims the trajectory to the take-off point.
5. **Clarify the AO template**: mass at brake release or at the first trajectory point.
   Optionally log at warning level when `am` overrides `takeoff_mass` (done in A6 PR 1, see the status table).

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

**A10. Airport fuel file units.** *Fixed in #77 (see the follow-up status table).*
1. `_load_airport_fuel_props` (`neats_parser.py`) → fallback in the parser (step 5.5).
2. Values are passed through `float()` only. The tests use `q_fuel` in J/kg. `h_c_ratio` is
   treated as atomic. There is no `hydrogen_content` column.
3. A `q_fuel` column in MJ/kg would enter 1e6 times too small, because the application's
   conversion does not apply to this file. A mass-based `h_c_ratio` would make `ei_h2o` about
   10 times too low.
4. No. PyNEATS reads the file itself.
5. **Follow-up (2026-10-22).**
   - The file used by NEATS (`Airport_Fuel_2025.csv`, 145 airports) was read: `q_fuel` is in
     J/kg (121 airports, 42.8–43.4 MJ/kg), `h_c_ratio` is empty, and the other columns are
     stored but not used. On `dev` (53bda5f) the file is applied correctly by all six runner
     paths (fleet large/small/performance-only from JSON, fleet from a DataFrame, single-flight
     large/small): operator value first, then the airport file, then 42.8 MJ/kg. End to end,
     fuel changes by 42.8/q as expected (within 0.04 %, the iterative take-off mass).
   - Reproduced: with the same file in MJ/kg, every flight using it failed with "BADA fuel
     flow is unrealistic".
   - **Fix.** A supplied `q_fuel` must lie within `Q_FUEL_MIN`–`Q_FUEL_MAX` (35e6–50e6 J/kg,
     `check_q_fuel` in `neats_fuel.py`). The airport file is checked when it is loaded, outside
     the block that turns a missing or unreadable file into a warning, and again when
     `FleetRunnerParams` is validated, because fleet steps are built lazily in the workers. A
     wrong file stops the run, naming the airports. A flight with an out-of-range value fails
     at parsing, naming the source (AO value or airport file and airport). `NEATSFuel` refuses
     such a value. A missing or unreadable file is still only a warning (unchanged).
   - The range only catches unit errors (MJ/kg is 1e6 times off); it does not judge whether a
     value is realistic for a fuel. Valid inputs give the same results.
   - **Maintainer decision (2026-10-22): keep 35–50 MJ/kg.** The DLR test cases define a
     narrower valid range, [42.6397, 44.5] MJ/kg (`TC_QFUEL_OUT_OF_RANGE`,
     `tests/test_cases_pipeline.py`, 45.5 MJ/kg expected to fail). It was not adopted, so that
     test stays a known DLR failure (strict xfail). The same applies to the hydrogen
     ([13.79, 15.5] wt.%) and H/C ([1.9061, 2.1857]) range cases.

**A11. `q_fuel` correction on the default branch.** *Resolved on branch `fix/fuel-energy-reference` (see A12 and the follow-up status table).*
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
6. **Resolution (2026-10-22), A11 and A12.**
   - **Verification.** pyBADA 0.1.12 computes BADA4 fuel flow as energy flow / `AC.LHV`
     (`bada4.py:1855-1873`). All 86 BADA4 models reachable through the PyNEATS mapping
     tables declare LHV = 43.217e6 J/kg (all jets, BADA 4.2), in both BADA folders used
     (`NEATS_TEST/mbg3P31p/4.2.1` and `NEATS_CLEAN/.../pyBADA/4.2.1`). The two pistons in
     BADA 4.2.1 (SR20, SR22: 43.71e6) are not mapped and not used.
   - **Maintainer decision (Philippe Very and Ramon Dalmau).** Keep the rescaling of the BADA
     fuel flow to the actual fuel, `ff = ff_BADA × REFERENCE_Q_FUEL / q_fuel`, always applied
     (default q_fuel 42.8e6, so ×1.0097). `REFERENCE_Q_FUEL` = 43.217e6 J/kg, the BADA4 LHV,
     for BADA4 and for BADA3 (which declares no LHV). `mrv-specification.md` now states this
     instead of "no correction if not provided". A test checks that every mapped BADA4 model
     declares this LHV (`tests/test_fuel_energy_reference.py`).
   - **Effect** (fleet before/after on the 4,959 NEATS_FINAL sample flights, `dev` db7d6e1):
     fuel and CO2 +0.21 % (BADA4 +0.21 %, BADA3 +0.21 %), NOx +0.41 %; per flight −0.6 % to
     +1.3 % (median +0.21 %; the iterative take-off mass stops within 1 %). Same failing
     flights, no change of BADA family.

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
- *Documented in `input-prioritization.md` and `mrv-specification.md` (#75, see the
  follow-up status table).*
- *Resolved on `fix/mass-from-ao-fuel-flow` (decision of the maintainer and the method owner,
  2026-10-28), only for flights with `ff` and no `am`: the mass starts at the AO TOM, or at
  min(MTOW, OEW + payload_factor x MPL + 1.15 x Σ AO ff x dt) without one, and decreases
  with the AO fuel flow, so mass(t₀) − mass(t_end) = Σ fuel_burn. A segment with an empty AO
  `ff` counts as 0 kg, as in Σ fuel_burn; a mass ending below OEW is logged as a warning, not
  clipped. BADA still computes thrust, and its fuel flow for a computed `ee` (unchanged rule),
  at that mass. The fuel-burn guardrail runs on the AO `ff` before the mass is integrated, so a
  kg/h fuel flow fails with the kg/s message (final, as for A1) instead of a negative mass
  inside BADA. Fuel and CO2 are unchanged; on the golden `fleet_5_flights_fuel_flow_col`
  flights the mass decrease was the BADA fuel (e.g. EAF2143: 3,785 kg against an AO fuel of
  3,872 kg) and now equals the AO fuel. Flights with `am` (with any other column), or without
  `ff`, are unchanged. Golden outputs regenerated: only the 10 records with `ff` and no `am`
  change (`fuel_flow_col` 5/5, `mixed_columns` EAF2143, aggregated `tc_perf_no_am`,
  `_no_am_ee`, `_no_am_tas`, `_no_am_ee_tas`); in them fuel, CO2 and the gaseous and nvPM
  emissions are identical, and the contrail EF changes by −0.12 % to +0.07 %.*

## 7. New discrepancies

### On the AO input path

**D1. Bare single-flight object rejected.**
*Still open. On the `FleetRunner` JSON path and in `scripts/run_json.py`, a file whose top
level is an object or a string now raises `TypeError("expected a sequence of flight objects")`
instead of an `AttributeError` (`fix/isolate-invalid-flights`). Accepting a bare object is not
decided.*
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
*Fixed on branch `fix/d2-timestamp-utc` (see the follow-up status table). The UTC offset
is now applied. Fractional seconds are truncated. A lowercase `t` or `z` and a space
separator are accepted. A `ts` without offset is read as UTC (maintainer decision). An
invalid `ts` raises an error naming the flight and point. On the `FleetRunner` JSON path and
in `scripts/run_json.py`, such a flight (or any flight object that cannot be converted) becomes
a `Failed at parsing` error record and the other flights go on (`fix/isolate-invalid-flights`);
a direct call to `neats_json_to_flights` without a `failures` list still raises. If every
flight fails, the run returns only error records. No effect on existing data: on 148 NEATS JSON files on
the NEATS server (85,128 flights, 10,995,586 points, all `+0000`, `Z` or `+00:00`) the output
is identical.*
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

**D3. Fuel flow derived from `am` is misaligned in time.** *Fixed on branch `fix/mass-derived-fuel-flow` (see the follow-up status table).*
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
6. **Fix (2026-10-22).** `ff[i] = (m[i] − m[i+1]) / Δt[i]` (`np.diff(mass, append=nan)`), so
   each point carries the burn of its own segment and Σ fuel_burn = m[0] − m[−1]. Measured
   on the 5 golden `aircraft_mass_col` flights (`dev` 6f35319, BADA4, uniform 60 s grid): the
   old total was 0.03–0.67 % low, and single points were off by up to 107–287 % in the
   descent (top of descent and descent level changes), which reaches the per-point NOx/CO/HC/nvPM indices and the CoCiP
   fuel per metre. The uneven-grid case after the speed filter also needs `segment_duration`
   recomputed (I9, low-speed filter work).

**D4. Partially null optional columns are not filled.** *Fixed on branch `fix/partial-null-columns` (see the follow-up status table).*
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
6. **Resolution (2026-10-22).**
   - **Measured on `dev` 8d437f5** (golden flight EAF2143, AO fuel flow thinned to one point
     about every 5 min, one value emptied at 19:12): the 15 one-minute samples between the
     neighbouring AO points (19:03–19:17) had no fuel flow and counted as zero: total fuel
     3,505 kg instead of 3,988 kg (−12.1 %); an empty mass value: about −15 %. With dense AO
     data (about 25 s) one empty value usually falls between minute marks and changes nothing.
     An AO column empty at every point, in a DataFrame given directly to `FlightRunner` or the
     parser, was kept as all-NaN, so the flight got no fuel at all (the JSON path and
     FleetRunner's `split_df_into_flights` already dropped it).
   - **Maintainer decision (Ramon Dalmau, 2026-10-22):** skip empty values,
     as if that point had not been sent. `pycontrails_interpolation.py` interpolates each
     optional column (fuel flow, mass, efficiency, TAS) on its valid points only; before the
     first and after the last valid value the nearest valid value is used; a column with no
     valid value is left out, so it is computed as when not provided. Gaps are filled by a
     straight line, not by BADA (no mixing of AO and BADA values within a column). On the
     example above the total becomes 4,051 kg (+1.6 % against the complete data: the line
     cannot know the dip at 19:12).
   - **Effect.** NM sample (4,959 flights, no AO performance columns): bit-identical. Golden
     test data: 57 flight records change, exactly those whose inputs carry empty AO values
     (written as JSON `NaN`, near the end of the flight). 47 regain their last minute of fuel
     (fuel and CO2 +0.0002 % to +0.96 %); 10 change only efficiency- or TAS-dependent results
     (`engine_efficiency_col`, and cases where fuel flow is not provided).
   - **Limits.** An empty mass value at the start or end is held constant, so the derived fuel
     flow there is 0 (before: empty; same total). A mass given at a single waypoint therefore
     gives a flight with no fuel, as before. No rule rejects a flight with many empty values.

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
6. **Resolution (2026-10-28, Ramon and Philippe).** Convert inside `LocalACCFModel`, not in the
   weather layer. `h2o_raw_formula` now applies the regression to |PV| in PVU:
   4.05e-16 + 1.48e-16·|PV_SI|·`PVU_PER_SI`, with `PVU_PER_SI` = 1e6 in `core/physics.py`.
   `compute_h2o` and the ClimAccf backend still receive PV in SI, as before.
   - **Tests.** `tests/test_accf_h2o_pv_units.py`: 2e-6 SI (2 PVU) gives 4.05e-16 + 2.96e-16;
     the result depends on PV (10 PVU gives 4.65 times the constant term); the sign of PV is
     ignored; `compute_h2o` gives the regression in PVU / scale × fuel burn. These tests fail on
     `dev` d239aa2.
   - **Effect, measured against `dev` d239aa2** (NM sample 2025-07-09, Method C, 4,959 flights,
     4,683 with climate results in both runs, the same 276 failures): H2O CO2eq × 2.1736 at every
     horizon (per flight × 1.02 to × 4.41, median × 1.93); total CO2eq +2.18 % (H20), +1.86 %
     (H50), +1.56 % (H100). Fuel, CO2, CH4, O3 and contrails are bit-identical.
   - **Cross-check with CLIMaCCF** (dlr-pa/climaccf 0184719, run through the pycontrails ACCF
     model outside the PyNEATS environment): fuel-weighted H2O aCCF on the 5 golden flights
     agrees within 0.33 % (before the fix: × 1.6 to × 3.3 apart). CLIMaCCF converts PV with
     `self.pvu = ds['pv'].values * 1e6` (`climaccf/accf.py:55`) and applies the same regression
     (`accf.py:168`).
   - **Golden outputs regenerated** with `scripts/create_golden_outputs.py` on this branch. All
     11 `*_output.json` files change, because every golden flight uses Method C; no input file
     changes. Only `ATR_20_H2O` and the H2O EAGWP and CO2eq values change; fuel, CO2, the other
     species and contrails are identical. H2O CO2eq is × 1.59 to × 3.29 per flight (it now
     depends on PV); for example EAF2143 (default case) 765.7 → 2,511.2 kg at H20.
   - **Still open.** No automated LocalACCF-against-CLIMaCCF regression test is added, because
     `climaccf` is not installed in the PyNEATS environment.

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
6. **Resolution (2026-10-28, Ramon and Philippe).** One reference year for every flight,
   `OPEN_AIRCLIM_REFERENCE_YEAR` = 2025 in `neats_default_parameters.py`
   (`OpenAirClimParams.reference_year`). The inventory year, `metrics.t_0`, `time.range` and the
   result key `AGWP_{H}_{year}` all use it. The base inventory covers 2025, so it fits unchanged.
   A flight dated 2026 now runs and gives the same values as the same flight dated 2025; flights
   dated 2025 are bit-identical to before.

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
  *Fixed on branch `fix/pmo-separate-efficacy` (see the follow-up status table). PMO now has
  its own efficacy (1.0, the RSTS value, confirmed by the method owner on 2026-10-28), RF
  backward factor (0.492, the CH4 value, because PMO is derived from the CH4 aCCF) and Dahlmann
  factors, and is added into the `CH4` entry. With these values the merged CH4+PMO is 0.55 %
  (Method C) and 0.86 % (Method D) smaller in magnitude than before on the NM sample of
  2025-07-09; the +0.9 % above is the same difference seen from the merged value.*
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
| `docs/reference/input-format.md:43`; `scripts/schemas/flight_schema.json:94-96` | `hydrogen_content` is a "mass fraction (0–1)" | wt.% (13.79). A caller sending 0.138 gets `ei_h2o` 100 times too low | fixed (input-format.md earlier; schema text `docs/fix-stale-docs`) |
| `scripts/schemas/flight_schema.json:106-109` | `calorific_value` in MJ/kg | J/kg (golden inputs validated by this schema hold 4.1944e7) | fixed (`docs/fix-stale-docs`) |
| `docs/explanation/mrv-specification.md:233-238` | H/C is a "molecular mass ratio"; formula without × 100 | atomic ratio; × 100 to give wt.% | fixed (`docs/fix-stale-docs`) |
| `docs/explanation/mrv-specification.md:220` | no BADA correction when `q_fuel` is not provided | correction always applied (A11) | **Aligned** (A11/A12): the spec now states the always-applied correction with the BADA4 LHV |
| `docs/explanation/mrv-specification.md:264,277,302` | EAGWP and AGWP in W m-2 | W m-2 yr | fixed (`docs/fix-stale-docs`) |
| `docs/explanation/mrv-specification.md:281` | s_yr = 31,536,000 s | 31,556,952 s (`physics.py:58`); contrail EAGWP differs by 0.066 % | **Aligned** (C.16): the code now uses the spec value 31,536,000 s (`fix/doc-climate-constants`) |
| `docs/explanation/mrv-specification.md:293-295` | C(H) = 24.16 / 47.57 / 74.36 e-15 | 24.12 / 47.50 / 74.24 e-15 (commit `bf3aa7b`, newer); CO2eq differs by about 0.15–0.17 % | **Aligned** (C.16): the spec is the reference; the code now uses 24.16 / 47.57 / 74.36 e-15 (`fix/doc-climate-constants`) |
| `docs/reference/output-format.md` | per-segment `flight_results`; `climaccf_version`; error-record keys; "fleet totals" | `runner.results` holds flight-level entries; the keys differ; `total_*` are per-flight; no units are given | fixed (`docs/fix-stale-docs`) |
| `docs/reference/input-format.md:85-113` | minimal example at FL 4 and FL 10 | rejected by the 550 hPa guard | use cruise levels |
| `docs/howto/usage.md:85-90,112,168-169`; `docs/reference/example-scripts.md:11` | `ZarrPaths(met_path=…)`, `DWDFactory(...).build()`, "fuel flow & thrust" | `met_store`/`rad_store`, `__call__(asofdate, hour)`, no thrust output | fixed (`docs/fix-stale-docs`) |
| `examples/README.md:140` | `engine_efficiency` = "engine thermal efficiency" | overall propulsion efficiency | fixed (`docs/fix-stale-docs`) |
| `scripts/schemas/flight_schema.json:102-116`; `docs/reference/input-format.md` | aromatics and naphthalene as "mass fraction" | volume basis per MRR Annex IIIa §5(4) and ReFuelEU (the pre-NEATS SAD draft said mass); scale undefined | schema text states the basis (`docs/fix-stale-docs`); align with the law once the scale is decided |
| `scripts/schemas/flight_schema.json:38,43`; `docs/reference/output-format.md:50`; `report.py` | departure = "AOBT", arrival = "AIBT" | AO schema: Item 13 = EOBT; arrival event undefined | relabelled in the schema text and output-format.md (`docs/fix-stale-docs`) |
| `docs/internal/performance_use_cases_analysis.md` | TAS always recomputed; early exit on FF+EE; FF never derived from mass | TAS kept when provided; early exit needs FF+EE+AM; FF derived from AM | mark superseded |
| `scripts/parquet_to_neats_json.py` | treats `altitude` as feet and stamps `+0000` without converting | basis (barometric or geometric) and time zone unverified | document expected input |
| `tests/test_performance_fallback.py:4,74,80`; `tests/test_guardrails.py:133,142,151` | FL15; 500 hPa | FL20; 550 hPa | update test docstrings |
| `docs/explanation/input-prioritization.md:60`; `docs/explanation/mrv-specification.md:203` | initial-mass fuel reserve ≈ 3 % of trip fuel | 15 % (`DEFAULT_FUEL_RESERVE_FRACTION = 0.15`, `neats_default_parameters.py:148`; `bada_model.py:1058`). Found after this audit, during the I4 review | fixed (#74) |
| `docs/explanation/input-prioritization.md:70`; `docs/explanation/mrv-specification.md:214` | the mass estimate runs steps 2–4 "twice" | when neither an `aircraft_mass` column nor a `takeoff_weight` attribute is given, steps 2–4 run at least twice and at most four times per estimate: one constant-mass BADA pass, then up to three passes from the updated TOW, stopping when the TOW changes by ≤ 1 % of the previous TOW (`max_mass_estimation_iter = 4`, `max_rel_mass_diff = 0.01`, `bada_model.py:1065-1117`); the last pass is kept. Measured on the 4,303 flights computed from the NEATS_FINAL sample: 2,769 stop after two passes, 1,415 after three, 119 after four, 3 of which stop at the cap with a change of 1.0–1.4 % (1.04, 1.17 and 1.39 %) | fixed (#74) |
| `docs/explanation/input-prioritization.md:23-44`; `docs/explanation/mrv-specification.md:187-193` | the decision tree and rules 1–5 are exclusive cases checked in order: fuel flow + η skips the performance step; fuel flow only uses BADA only for η; with aircraft mass, BADA computes the fuel flow | each quantity has its own source. The BADA thrust and fuel-flow calculation is skipped only when fuel flow, η and aircraft mass are all given (`bada_model.py:741-745`); the BADA adapter is still resolved and, for BADA3 runs, the low-speed filter still removes rows on that path (`bada_model.py:483-495`). Otherwise the mass is the AO mass, else the AO TOW, else the iterative estimate, whatever fuel flow or η were given (`bada_model.py:850-874`); with aircraft mass and no fuel flow, the fuel flow is derived from the mass decrease (`bada_model.py:762-812`); the BADA mapping is needed for every flight. Checked by running one golden flight (EAF2143) with six input combinations (fuel flow + η + mass, fuel flow + η, fuel flow, mass, TOW, none) and with an aircraft type missing from the BADA mapping. A retry bug (a BADA3 retry after a BADA4 guardrail rejection reused the BADA4 columns and could take this exit) is fixed separately (I10) | fixed (#75) |
| `docs/explanation/input-prioritization.md:17` | modelled take-off weight = OEW + load_factor × (MTOW − OEW) | that is only the constant first-pass mass; the take-off weight used is min(MTOW, OEW + load_factor × MPL + 1.15 × trip fuel) from the iteration (MPL = MTOW − OEW when BADA gives no positive MPL). On the 4,303 computed NEATS_FINAL sample flights the first-pass mass equals MTOW on all, the take-off weight on 243 | fixed (#75) |
| `docs/explanation/input-prioritization.md:83,85` | unmapped types fall back to fleet-statistics proxies; the engine UID defaults to the MRR conservative value | the fleet statistics were used to build the mapping tables; a type absent from them makes the flight fail. Without a declared engine, the engine UID is the MRR conservative engine where the type has one (`MRR_conservative_mapping.csv`), otherwise the engine of the mapping row | fixed (#75) |
| `docs/explanation/input-prioritization.md:96-97` | "Fuel flow only: η derived from BADA"; "Mass evolution: full BADA performance chain" | with fuel flow only, the mass and TOW are also estimated from the load factor; with mass evolution, the fuel flow is derived from the mass decrease (star ranking left unchanged) | fixed (#75) |
| `docs/explanation/mrv-specification.md:119,172` | missing points of optional AO variables are filled by interpolation; the performance model estimates values "not available at a point" | since D4 was fixed, empty values are skipped when resampling: each resampled point is interpolated between the nearest points with a value (`pycontrails_interpolation.py:120-130`); the #75 text described the earlier behaviour | fixed (#75), then updated for D4 and D3 (`docs/fix-stale-docs`) |
| `docs/explanation/mrv-specification.md:181` | without AO TAS, TAS is set to 0 below 840 hPa | the wind is set to 0 where it is missing (`weather_provider.py:382-383`), so TAS equals the smoothed ground speed | fixed (#75) |

## 10. Incidental observations outside the unit scope

These affect how the audited fields are consumed but are not unit issues. They are reported
for a separate decision and were not fixed.

- **I1. BADA4 speed filter never runs.** `BADA4Adapter.v_stall_cas` calls
  `VStall(mass=, config=)`, but the pyBADA 0.1.12 BADA4 signature is
  `VStall(mass, HLid, LG, nz=1.0, **kwargs)` (`bada_adapters.py:175-180`; pyBADA
  `bada4.py:2349`). The `TypeError` is swallowed (`bada_model.py:463-469`), so taxi and
  low-speed points stay in for BADA4 aircraft. The unit tests mock `VStall`.
  *Fixed on branch `fix/airspeed-trust` (see the follow-up status table).* On `dev`
  5aba2f9 the call is `bada_adapters.py:193` and the swallow `bada_model.py:508-514`;
  measured on the NM sample 2025-07-09, the `TypeError` was raised on every BADA4 call
  (3,263 of 3,263) and 3,253 of 3,253 BADA4 flights ran unfiltered. `BADA4Adapter` now has
  its own `v_stall_cas`: (HLid, LG) = `getAeroConfig(config)`, then
  `VStall(mass, HLid, LG, nz=1, theta=1, delta=1)`, the CAS at ISA sea level (B738 at MTOW
  in TO: 146.8 kt, against 128.1 kt in BADA3). The low-speed filter itself is replaced by
  the airspeed trust step (I9, I14), and an error in that step now fails the flight with no
  retry instead of being swallowed (maintainer decision). The unit tests check the call
  signature, and the stall speeds of three BADA4 models with the real files.
- **I2. Naphthalene key mismatch.** `neats_io` emits `naphthalene`, `Flight4D` allows
  `naphtalene`, and `NEATSFuel.from_attrs` reads `naphthalene`. The AO value and the airport
  value both fail to reach the fuel object.
- **I3. Zero values replaced.** `NEATSFuel.from_attrs` uses `or` between alternative keys, so
  an explicit `sulphur_content` of 0.0 becomes the default 0.003 on the fuel object.
- **I4. BADA3 MPL hidden.** `BADA3Adapter.MPL` returns `None` with the comment "BADA3 has no
  MPL attribute". pyBADA 0.1.12 `Bada3Aircraft` does set MPL (OPF maximum payload × 1000 kg,
  `bada3.py:396-405`). BADA3 flights therefore estimate ZFW with pf × (MTOW − OEW), which is
  heavier than pf × MPL. The comment was corrected; the behaviour was not changed.
  *Fixed on branch `fix/bada3-max-payload` (see the follow-up status table).
  `BADA3Adapter.MPL` now returns the OPF maximum payload, as `BADA4Adapter.MPL` already did.
  The MTOW − OEW fallback stays for a BADA file without a usable MPL, and now also covers a
  zero, negative or NaN value: all 264 BADA 3.16 OPF files give one, but `U2____.OPF` (also
  used by pyBADA for G850, GFLY, M17 and M55) gives 0. None of these types is in the NEATS
  BADA mapping. In BADA 4.2.1, only SR20 and SR22 have no MPL. Before the fix, with the
  default payload factor 1.0, ZFW = MTOW, so every BADA3 flight took off at MTOW (1,050 of
  1,050 BADA3 flights in the NEATS_FINAL sample). Measured on those 1,050 flights with the
  BADA 3.16 files: BADA3 fuel −4.5 % (7,313 t → 6,983 t), CO2 −4.5 %; per flight median
  −5.7 %, 5th percentile −10.4 %, minimum −21 % (business jets with a small OPF payload: GLF5
  15 %, GLEX 8 % of MTOW − OEW); 42 flights still take off at MTOW; take-off mass median
  −8.2 t. BADA4 flights are not affected. Only the BADA3 path changes, including BADA4 types
  that fall back to BADA3. The fuel-burn guardrail still uses MTOW − OEW on purpose (payload
  and fuel together).*
- **I5. Parser `timezone` parameter has no effect.** pycontrails stores time as naive UTC
  (`vector.py:2162-2167`). The docstrings were corrected.
- **I6. Outputs not strict JSON.** `scripts/run_json.py` writes no output. Golden JSON
  contains bare `NaN` and `Infinity` tokens (28,945 and 318 in `fleet_5_flights_output.json`).
- **I7. `fleet_to_flights` docstring.** It said fuel is rebuilt from the Fleet columns; it is
  rebuilt from attrs (corrected).
- **I8. Humidity-scaling adapter fallbacks.** The fallback branches rebuild `Flight` without
  its fuel (`weather_provider.py:139-147`). They are unreachable with stock pycontrails.
- **I9. `segment_duration` not recomputed after the speed filter.** Recorded after this audit
  (2026-10-21); fixed on `fix/airspeed-trust` (see below). `segment_duration`, `rocd` and
  `acceleration` are forward differences computed in `_compute_kinematics`
  (`bada_model.py:680-700`) before `filter_low_speed_points` (`bada_model.py:488-495`), and
  are not recomputed on the rows kept:
  - a removed row's own segment adds no fuel;
  - when trailing rows are removed, the last kept row keeps a finite duration that points to
    the first removed row. On the computed-TAS path the last row always has NaN TAS, so it is
    always removed when the filter runs and this always happens;
  - pycontrails `Emissions` recomputes durations from the timestamps, so CO2 differs from
    3.159 × fuel;
  - the take-off weight (given or estimated) applies at the first kept row (A6), and the trip
    fuel of the mass estimate covers the kept rows only.

  Today only BADA3 runs are affected, because the BADA4 filter never runs (I1). Measured on
  the 1,050 BADA3 flights of the NEATS_FINAL sample (production v1.0.0 code): 3,173 rows
  removed (639 leading, 1,947 trailing, 587 interior), carrying 1.36 % of flight time;
  CO2 / (3.159 × fuel) from 0.961 to 1.360 (median 0.995) per flight, 0.17 % below at fleet
  level.

  *Fixed on branch `fix/airspeed-trust` (see the follow-up status table).* On `dev`
  5aba2f9 (NM sample 2025-07-09) the BADA3 filter deleted 34.7 h of flight from the fuel and
  43.0 h from CO2, and 998 of the 1,050 BADA3 flights had CO2 / (3.159 × fuel) more than
  0.1 % from 1 (0.9635 to 1.3857). The filter is replaced by an airspeed trust step
  (`steps/performance/airspeed_trust.py`, maintainer decisions of 2026-10-23):
  - **no row is removed**, so `segment_duration` and `rocd` stay valid, PyNEATS and
    pycontrails `Emissions` use the same durations, and the take-off weight applies at the
    first row;
  - a row is untrusted when its TAS is not finite, its CAS is below the BADA stall CAS at
    MTOW (configuration `airspeed_stall_config`, default "TO") or above the aircraft's
    maximum operating speed VMO, or its Mach number is 1 or more (I14 for the CAS
    comparison). VMO is read from the BADA model of the attempt (pyBADA `VMO`, kt CAS, in
    the BADA4 XML and the BADA3 OPF), with no margin; 400 kt applies when the model has
    none. Every one of the 132 BADA codes of the NM sample (43 BADA4, 89 BADA3) has a VMO,
    from 250 to 370 kt (maintainer decision of 2026-10-23, replacing a fixed 400 kt; see
    "Too-fast limits" below);
  - an untrusted TAS is replaced by linear interpolation in time between the nearest trusted
    rows, and `acceleration` is recomputed from the TAS used;
  - before the first and after the last trusted row, an untrusted row takes the CAS of that
    trusted row, converted back to TAS with its own pressure altitude and temperature
    deviation (pyBADA, as in the trust test; maintainer decision D2). A descent after the
    last cruise row therefore keeps a constant CAS and its TAS falls with the altitude.
    Holding the TAS instead (first version of the branch) kept THY6RA at its cruise TAS of
    455 kt from FL370 down to FL28, a CAS of up to 429 kt;
  - when PyNEATS computes the TAS, trust is decided and the gaps are filled on the
    unsmoothed 1-min TAS (pycontrails `segment_true_airspeed(smooth=False)`, same winds).
    Reason: the smoothed TAS spreads slow minutes over their trusted neighbours (STW1125 at
    FL310: about 500 kt before a raw gap and 457 kt after it, but smoothed anchors of about
    250 kt, so a fill from them gave about 240 kt);
  - the filled series is smoothed with the Savitzky-Golay filter pycontrails applies to the
    ground speed (window 7, polyorder 1), and only the rows whose smoothing window holds an
    untrusted row take that value: the untrusted rows, the rows up to 3 points from them,
    and the first or last 3 rows when one of the first or last 7 is untrusted. Every other
    row keeps the TAS from the smoothed ground speed bit for bit, so a flight whose only
    untrusted row is its last one is unchanged on every other row. Next to a slow stretch
    the re-smoothed trusted neighbours move by more than 100 kt (the smoothed ground speed
    had pulled them towards it).
    Smoothing the whole flight in TAS instead (first version of the branch) also moved
    trusted rows far from any gap, by up to 56 kt at turns in 50-65 kt winds, on 81 % of
    the flights (fleet fuel effect on 265 sample flights: 0.014 %);
  - untrusted rows before the first and after the last trusted row keep the held CAS of the
    end rule also after the smoothing: the Savitzky-Golay edge fit would otherwise
    extrapolate the climb or descent across them, back below the stall CAS or above VMO
    (TVS25M: a 162 kt fill at FL1 smoothed to 93 kt);
  - the last row of a computed TAS (NaN, no forward segment) takes the TAS of the row
    before it; its duration is NaN, so it adds no fuel;
  - no column is added: the output schema is unchanged, and `true_airspeed` in the
    outputs is the TAS used (maintainer decision: no schema change);
  - the step runs before every path, including the early exit with AO fuel flow, efficiency
    and mass, and with the stall speed and VMO of the adapter of each attempt (BADA4, then
    BADA3 on a retry);
  - the flight fails (non-retryable: no BADA3 retry, no altitude fallback) when more than
    80 % of its time is untrusted, when no row is trusted, or when the step raises. The
    80 % and no-trusted-row rules do not fail a flight whose AO data has fuel flow, engine
    efficiency and aircraft mass (the early exit, where the BADA fuel flow is not used;
    maintainer decision D4): its TAS is still replaced, or kept as is when no row is
    trusted.

  Measured on the NM sample 2025-07-09 (4,959 flights; the 4,303 computed on `dev` 5aba2f9
  are computed on the branch, which includes I13; default TO threshold):
  - fleet fuel −0.62 % against `dev` (49,591.5 t → 49,283.7 t; BADA4 −0.94 %, BADA3
    +1.34 %, mostly deleted time coming back), CO2 −0.60 %; CO2 = 3.159 × fuel on all 4,303
    flights (`dev`: 3,305 within 0.1 %); no flight fails or recovers; 10 flights move from
    BADA3 to BADA4 (the 6 with Mach ≥ 1 and 4 of the I13 flights);
  - 16,527 rows untrusted on 3,710 flights, last row excluded (275 h, 2.1 % of the time on
    the median flight, at most 62 % on NACHO20, so the 80 % rule fails no flight); 4,016
    rows in end runs and 4,040 in start runs;
  - the 397 `dev`-BADA4 flights whose only untrusted row is the last one keep TAS, fuel burn
    and mass bit for bit on every other row;
  - CAS end rule against the earlier TAS hold: fleet fuel +0.016 %, 51 flights change by
    more than 1 %. THY6RA (end run from FL370 to FL28) keeps a CAS of 248 kt, its TAS falls
    from 455 kt to 264 kt, and its fuel goes from 5,267 kg to 4,151 kg (`dev`: 5,221 kg);
    TOM902P −4.0 %. End-run rows below FL100 with a CAS above 250 kt: 130 on 21 flights,
    against 254 on 45; rows with a CAS above 400 kt or Mach ≥ 1 after the step: 3 on 1
    flight (CKK216, interpolated cruise rows at Mach 1.0004-1.0007), against 19 on 7;
  - the CAS end rule copies a wrong anchor too: SWR177 row 0 (FL0) now gets a TAS of
    342 kt (CAS 334 kt), from its first trusted row at FL320 (unsmoothed 545 kt, itself a
    timestamp artefact after raw rows at 2,234-8,369 kt). Three flights still start above
    400 kt TAS at FL1-18 (PGT156P, THY093, TKJ2AJ; CAS 390-399 kt, within the limits);
  - 513 rows on 488 flights are still below the stall CAS after the step, 501 of them
    trusted on the unsmoothed TAS and pulled below by the smoothing.

  These measurements are for the first version of the branch, with a fixed 400 kt CAS
  limit. With the VMO limit (final version, measured the same way):
  - fleet fuel −0.77 % against `dev` (49,591.5 t → 49,212.1 t; BADA4 −1.10 %, BADA3
    +1.26 %), CO2 −0.74 %; CO2 = 3.159 × fuel on all 4,303 flights; no flight fails or
    recovers; the same 10 flights move from BADA3 to BADA4;
  - VMO makes 3,773 more rows untrusted on 1,489 flights, a median of 11 kt above VMO,
    mostly one-minute spikes; it only lowers speeds (air distance −0.28 % on 360 of the
    flights concerned that were checked);
  - flights with a take-off point (first 5 min, below FL10) above 300 kt CAS: 21, against
    46 with the 400 kt limit and 43 on `dev`; TOM902P −19 % against the 400 kt version;
  - after the step, 26 rows on 10 flights are slightly above VMO (at most 14 kt): the
    interpolation is done in TAS while the altitude changes, and the last row copies the
    TAS of the row before it. No row has Mach ≥ 1.

  *Too-fast limits (maintainer decision of 2026-10-23).* With 400 kt, "catch-up" minutes
  after a frozen position (the aircraft "jumps" to catch up with the time) passed the
  limit and became the first or last trusted row, and the end rule copied their CAS onto
  the take-off or landing rows: 86 flights took off with more than 250 kt CAS below FL10
  (26 above 300 kt; ETD75F 374 kt, QTR75N 372 kt, EZY68GP 369 kt, RYR6RJ 369 kt at
  FL0-30), and 10 flights held more than 300 kt CAS in their end run; TOM902P held 372 kt
  CAS down to FL13 (+17.9 % fuel against `dev`). A typical VMO is 330-350 kt, so the CAS
  limit is now the BADA VMO. Estimated on the rows of the 400 kt run (unsmoothed TAS, the
  basis of the trust test, last row excluded), VMO untrusts 3,773 more rows on 1,489
  flights (63 h; median 11 kt above VMO); no flight goes above 80 % untrusted time (at
  most 62 %, NACHO20). Each of the four take-off cases above loses its catch-up anchor:
  the first trusted row is now at FL80 (ETD75F, 269 kt), FL34 (QTR75N, 202 kt), FL52
  (EZY68GP, 240 kt) and FL44 (RYR6RJ, 242 kt). TOM902P's 372 kt row at FL89 is
  untrusted, so its end run starts at FL117 with 157 kt CAS. SWR177's first trusted row
  moves from row 4 (334 kt CAS at FL320, above its VMO of 330 kt) to row 5 (208 kt at
  FL320), so row 0 (FL0) gets 208 kt CAS instead of 334 kt; that anchor is still part of
  the timestamp artefact. VMO also untrusts 784 level rows at FL245 and above on 150
  flights (median Mach 0.907, mostly B777 and A350 models), which are probably real
  cruise with a wind error.

  The Mach limit stays at 1 and is not the BADA MMO: the TAS is the ground speed minus a
  modelled wind (a 10 kt wind error at FL370 is about Mach 0.017), and some BADA models
  stand for a faster type (business jets mapped to a GLEX model). MMO with no margin
  would untrust 15,628 level cruise rows at FL245 and above on about 2,000 flights
  (median 0.018 above MMO) and fail one flight on the 80 % rule; with a 0.08 margin,
  1,205 rows, but the margin is a tuned number.

  Known limits, not changed: a catch-up minute between 250 kt and VMO stays trusted and an
  end run copies its CAS. The anchor row of an end run can be re-smoothed while the end
  run keeps its unsmoothed CAS, so the CAS can step at the boundary (median 22 kt at
  flight starts, 7 kt at flight ends, up to about 100 kt) and `acceleration` has a one-row spike there.

  A measurement-only prototype (trust and fill on the smoothed TAS, no too-fast rule, TO
  threshold) gave fleet fuel −0.37 %. The golden outputs are regenerated with the final
  code.
- **I10. A failed attempt leaked columns into the BADA3 retry.** Found after this audit
  (2026-10-21), while checking the user docs. *Fixed on branch
  `fix/performance-retry-isolation` (see the follow-up status table).*
  - **Defect.** `run()` passed the same preprocessed DataFrame to the first attempt and to the
    BADA3 retry (`bada_model.py:350-391`), and `_run_with_altitude_fallback` did the same for
    its two attempts (`bada_model.py:429-451`). `run_by_bada_version` writes into that
    DataFrame: `fuel_flow` derived from `am` before the BADA calculation, then
    `aircraft_mass`, `thrust`, `fuel_flow`, `phase`, `thrust_segment`, `fuel_burn` and `fuel`
    (`_finalize_columns`) before the fuel-burn guardrail (`_build_result`). The DataFrame is
    shared whenever the low-speed filter removes nothing, which is always the case for BADA4
    (I1). The BADA3 retry therefore took the columns of the failed BADA4 attempt as AO data.
  - **Effects** (reproduced on golden flight EAF2143, BADA4 fuel or AO fuel flow × 15 to
    trigger the guardrail, limit 45,600 kg):

    | AO data | First failure | Before the fix | With the fix |
    | --- | --- | --- | --- |
    | fuel flow + η | guardrail on BADA4 | BADA3 retry took the early exit ("all provided"): accepted with 55,674 kg, no guardrail, no `bada_version` | BADA3 retry rejected on the same AO fuel, then the altitude fallback; rejected if every attempt is |
    | η only | guardrail on BADA4 | early exit: accepted with the rejected BADA4 fuel (49 t), no `bada_version` | clean BADA3 retry, accepted with 3,552 kg |
    | none | guardrail on BADA4 | BADA3 retry reused the BADA4 fuel flow and mass: rejected again, no altitude fallback | clean BADA3 retry, accepted with 3,552 kg; otherwise the altitude fallback |
    | mass + η | BADA4 fails before its result (e.g. first point) | early exit on the fuel flow derived from the mass, BADA skipped | clean BADA3 retry, with the guardrail |
    | any, type without a BADA4 code | guardrail on BADA3 | altitude fallback | altitude fallback (unchanged) |

  - **Fix.** Each attempt works on its own copy (`df = df.copy()` at the start of
    `run_by_bada_version`).
  - **Maintainer decision (2026-10-21): a fuel-burn rejection goes through the whole fallback
    chain.** Before, the guardrail error carried `retryable=False`. `run()` ignored the flag
    before the BADA3 retry, but that retry reused the rejected BADA4 columns, so it never gave
    a plausible result; `run()` then honoured the flag before the altitude fallback, except
    for types without a BADA4 code and for BADA4 types whose BADA3 retry failed for another
    reason (those errors carry the default flag). The maintainers considered making the
    rejection final and decided to keep the fallbacks: the guardrail error is now retryable,
    so a rejected flight is retried with BADA3, then with the altitude fallback (points below
    FL20 removed), and fails only if every attempt is rejected. `run()` and
    `_run_with_altitude_fallback` now also honour `retryable=False` before their BADA3
    retries. On this path only two internal consistency errors carry that flag (a BADA file
    without MTOW or OEW when the take-off mass is estimated, and a missing initial mass), and
    neither occurs with the BADA files in use.
  - **Known, not changed (existed before).** For a type without a BADA4 code, the altitude
    fallback runs the same BADA3 calculation twice (its "BADA4" attempt resolves to BADA3).
    When the altitude filter cannot run (no point below FL20, or more than 80 % below it),
    such a flight's error record reads "already performed with BADA3" and the actual reason
    (for example the fuel-burn rejection) is only in the exception cause, which the fleet
    runner does not record. Candidates for the AO-input / error-reporting work.
  - **Effect on results.** No flight of the NEATS_FINAL sample reaches the guardrail, so its
    results do not change (fleet before/after on the 4,959 sample flights).

- **I11. The fleet step cache was shared between runners in one process.** Found
  2026-10-22, while checking the airport fuel file (A10). *Fixed in #78 (see the follow-up
  status table).*
  - **Defect.** `FleetRunner` builds its steps (parser, performance, emissions, ...) lazily
    and caches them per process (`_STEP_CACHE` in `runners/fleet.py`), keyed by
    (interface, name) only. The first runner's step was reused by any later runner in the
    same process, whatever its parameters. This happens when one process runs several
    runners (a notebook, a script running two configurations, the test suite) and the steps
    run in that process or in reused workers: `njobs=1`, `prefer="threads"`,
    `shutdown_executor_between_steps=False`, or the default `njobs=-1` when only one CPU is
    usable (joblib then runs everything in the calling process, e.g. a 1-core batch job or
    container). With the defaults on several CPUs, each step gets fresh workers and was not
    affected. A single runner per process was never affected.
  - **Effect before the fix** (reproduced on `dev` 53bda5f, `njobs=1`, real sample
    flights): a runner with the airport fuel file run after one without it ignored the file;
    in the opposite order, the second runner applied a file it was not given. The same holds
    for every step parameter (`bada_path`, emission or climate parameters).
  - **Fix.** Each `make_step_func` callable gets a unique token, stored with the cached step.
    Another token rebuilds the step and replaces the entry. Within one runner the token
    travels with the pickled callable, so each worker still builds each step once. At most
    one step per (interface, name) is kept, as before. Two runners used at the same time in
    one process (threads) rebuild their steps when they alternate; each still gets its own
    step, and the builds are cheap. The weather dataset cache is keyed by
    path, time window and chunks, and was not affected.

- **I12. FlightRunner and FleetRunner give different contrail results for the same flight.**
  Found 2026-10-22 while regenerating the golden files for A11/A12. *Open.*
  - **Observation.** `test_flight_runner_golden` runs each golden flight through FlightRunner
    and compares it with golden outputs produced by FleetRunner (CoCiP on the whole fleet).
    For FDX5067 (`aircraft_mass_col`), fuel flow, engine efficiency, aircraft mass,
    temperature and humidity are identical at every waypoint in both runs, yet the
    contrails formed at waypoints 48–49 end at 2 h 45 / 2 h 44 with FlightRunner and at
    2 h 51 / 2 h 56 with FleetRunner. The flight's `contrails_ef_J` and its contrail
    EAGWP/CO2eq differ by 1.03e-3 (test rtol 1e-3). On `dev` db7d6e1 the same contrails live
    equally long in both runs (difference 1.8e-6); the +0.2 % fuel of A12 is enough to tip
    them.
  - **Likely cause (not verified).** CoCiP run on a fleet evolves all contrails on one common
    time grid, while a single-flight run aligns the grid to that flight, and contrail
    termination depends on the grid.
  - **Handling.** In `tests/test_pipeline.py::test_flight_runner_golden` only the
    contrail-based values (`contrails_ef_J` and the `Contrails` climate metrics) are compared
    at rtol 5e-3; everything else stays at 1e-3, and the FleetRunner golden tests are
    unchanged. To investigate: whether the two runners should give identical contrails.

- **I13. A non-finite BADA fuel flow made the mass NaN for the rest of the flight.** Found
  2026-10-23 during the low-speed filter work. *Fixed on branch `fix/bada-nonfinite-fuel-flow`
  (see the follow-up status table).*
  - **Defect.** `_single_pass_performance` (`bada_model.py:895-1026` on `dev` 5aba2f9)
    treats a point as a BADA failure when BADA raises or when the fuel flow is above
    `ff_outlier_threshold` or negative (`:971`); the point then takes the previous point's
    values, and more than `max_consecutive_failures` (5) failures in a row, or a failure at
    the first point, fail the attempt. A NaN fuel flow passes both comparisons, so it was
    accepted: it became the "previous" value (`:976`), and with a take-off mass the
    integrated mass (`:1018`) was NaN from that point on. The fuel of every later point was
    then NaN and dropped out of the sums (trip fuel, guardrail and totals skip NaN). BADA4
    gives a NaN fuel flow, without raising, wherever the TAS is NaN: at a frozen raw position
    (zero-length segment) and at the last point of the computed-TAS path. BADA3 runs did not
    reach it on `dev`, because the speed filter drops NaN-TAS rows.
  - **Effect before the fix** (NM sample 2025-07-09, 4,959 flights, `dev` 5aba2f9): 3 BADA4
    flights (VLG1254, IBE09LA, IBS15XJ) had NaN fuel on their last 21 rows each (63 rows);
    4 flights (RYR4WR, RYR6EF, EZY87KM, VLG90AB) fell back to BADA3 through exceptions on the
    NaN mass.
  - **Fix.** A fuel flow that is not finite is a BADA failure at that point, like an
    outlier, so the existing rule applies (previous point's values; the attempt fails after
    more than 5 in a row or at the first point).
  - **Effect** (fleet before/after on the same 4,959 flights, measured with this rule):
    same 4,303 flights computed, no NaN fuel row left; fleet fuel +0.005 % (+2.5 t), CO2
    +0.005 %; 5 flights change: VLG1254 +36.8 %, IBE09LA +10.1 %, RYR4WR +16.5 % and VLG90AB
    +7.5 % (both now BADA4), IBS15XJ −2.1 % (now BADA3: its 8 NaN-TAS rows at a frozen
    raw position exceed the 5-failure limit). RYR6EF and EZY87KM stay BADA3 (other BADA4
    failures). The last point of a BADA4 flight now carries the previous point's fuel flow
    instead of NaN; its fuel burn stays empty (no next point), so totals do not change
    there.

- **I14. The low-speed filter compared a TAS with a CAS stall speed.** Found 2026-10-23
  during the low-speed filter work. *Fixed on branch `fix/airspeed-trust` (see the
  follow-up status table).*
  - **Defect.** `filter_low_speed_points` (`speed_filter.py:61` on `dev` 5aba2f9) kept a row
    when `true_airspeed >= v_stall`, where `v_stall` is the BADA stall speed in CAS (pyBADA
    `VStall`). TAS and CAS coincide only near sea level: at the stall speed of a jet
    (about 66 m/s), TAS / CAS is 1.16 at 10,000 ft and 1.62 at 30,000 ft. A row slower than
    the stall speed in CAS was kept at altitude.
  - **Effect before the fix** (NM sample 2025-07-09, `dev` 5aba2f9; BADA3 only, because of
    I1): comparing CAS with CAS would have marked 572 more rows on 338 of the 1,050 BADA3
    flights as slow, and none fewer. Example: PGT023 (A21N) at FL362-390 with a derived TAS
    of 98-124 m/s, a CAS of 49.5-65.8 m/s, below the stall CAS of 66.3 m/s.
  - **Fix.** The airspeed trust step (I9) converts each TAS to CAS (and Mach) with pyBADA at
    the pressure altitude and the temperature deviation of the row, as the BADA adapters do,
    and compares CAS with the stall CAS. The upper limit is also a CAS: the BADA maximum
    operating speed VMO of the aircraft (400 kt when the BADA model has none). The Mach
    limit is 1, not the BADA MMO (see I9).

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
  and 1.1/10 % → 1.2/20 %; `REFERENCE_Q_FUEL` was then the pycontrails JetA value, not a
  BADA value; it is the BADA4 LHV since A12), `core/physics.py` (year length and C(H) against the spec; conversion-factor
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
