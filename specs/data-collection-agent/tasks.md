# Data Collection Agent — Tasks

**Status:** Draft for review (revised after review — do not implement until approved)
**Date:** 2026-06-24
**Spec:** `specs/data-collection-agent/spec.md` (Q1–Q4 incorporated)
**Plan:** `specs/data-collection-agent/plan.md` (Option A)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` v2.0.0

## Confirmed decisions (acceptance checks reference these + spec ACs)

- **Option A:** deterministic Python service, **no model-calling Agent loop**.
- **Structure:** OpenAI Agents SDK *conventions* for layout, but this agent is plain
  Python; **n8n triggers it**, **Supabase** is the data store.
- **confirm-count = 3**; **PENDING timeout strictly > 3× the sensor's configured
  interval** (buffer so an on-time 3rd confirming reading always resolves first — G3).
- **σ-baseline window = intersection of (last 100 readings) AND (last 24 hours)** —
  i.e. the most recent ≤100 readings that also fall within 24h — using **OK/trustworthy
  readings only** (G1).
- **Liveness owns OFFLINE** (single source of truth). Gap-fill sets only the
  reading-status NO_DATA, never the sensor-status (G2).
- **Liveness & ordering use the sensor's own timestamp**, not ingest time (G4).
- **CLOCK_DRIFT:** when |sensor-timestamp − ingest-time| exceeds a per-type configurable
  tolerance, set a `clock_drift` flag + log it, but **still process using the sensor's
  timestamp** (G4). *(Modeled as a co-existing flag, not a terminal reading-status —
  see note under T202.)*
- **Duplicate-conflict** (same sensor+timestamp, different value): **first-received
  value wins**; the discarded duplicate is logged as a conflict with **both** values,
  reason `"duplicate timestamp, conflicting value, first-received kept"`. No averaging,
  no confidence selection.
- **Late-arrival:** recompute bounded to the **3× interval lookback**, logged as a
  correction (`old status → new status`, reason `"late-arrival recompute"`), **never a
  silent overwrite**.
- **Per-type physical bounds, exact cadence, and clock-drift tolerance stay
  `TODO`-marked config** — not blockers; logic is buildable, only constants change.

## Conventions

- Each task is < 1 hour and **independently verifiable**; acceptance checks are concrete
  (tied to an FR/AC or a decision above), never "works correctly".
- **[DB-DEP]** = needs live Supabase to fully verify; built/verified against an in-memory
  fake now, live verification deferred (no Supabase instance locally — stated honestly).
- Constitution gates: never crash → always return status (FR-6); raw append-only + every
  decision logged with reason (FR-7); fully deterministic (no LLM).

---

## Phase 1 — Sensor configuration & registry (config, not code)

- **T101 — Define `SensorProfile` shape.** *(already implemented — amend for new field)*
  Fields: `sensor_type`, `unit`, `cadence_s`, `offline_after_n` (=3), `phys_min`/`phys_max`
  (**TODO**), `zscore_threshold` (=3.0), `baseline_max_n` (=100), `baseline_max_age_h`
  (=24), `confirm_count` (=3), `pending_timeout_mult` (=3), `interp_cap` (=2),
  **`clock_drift_tolerance_s` (=TODO per type — G4)**.
  **Acceptance:** a profile constructs with all fields incl. `clock_drift_tolerance_s`;
  constants match the decisions (offline_after_n=3, confirm_count=3, pending_timeout_mult=3,
  interp_cap=2, baseline 100/24). *(Amends the already-built profile to add the new field.)*

- **T102 — Seed the seven sensor types as config.**
  Profiles for accelerometer, strain gauge, crack sensor, load cell, temperature,
  tiltmeter, displacement/LVDT (`iot-sensor-ingestion` list). `phys_min/max`, `cadence_s`,
  and `clock_drift_tolerance_s` are `TODO`-marked placeholders.
  **Acceptance:** all 7 types present; each has every T101 field; TODO bounds/cadence/
  drift-tolerance clearly flagged (a reviewer sees they're unset, per the config-TODO decision).

- **T103 — Profile lookup + unknown-type signal.**
  `get_profile(sensor_type)` returns the profile or a structured **"unknown type"** signal
  — **not** an exception (feeds the CORRUPT path, spec edge-case rule).
  **Acceptance:** known type → profile; unknown type → unknown-signal, **no raise**
  (supports AC-7 unknown-type handling). Adding a new type = adding one config entry, no
  logic change (spec: "without changing the validation logic").

- **T104 — Expected-sensor registry (NEW — B1).**
  A registry of which sensors are **expected to report** (per bridge/municipality),
  independent of any incoming reading. The orchestrator iterates this registry, so a
  sensor that sends **nothing** still gets evaluated and can be flagged OFFLINE — silence
  is never an absent row (spec headline: "silence must never be mistaken for safety").
  Registry is configuration/data (addable without logic change), `TODO`-seedable.
  **Acceptance:** registry lists expected sensors with their `sensor_type`; a sensor in
  the registry but **absent from the batch** yields an evaluated result (→ OFFLINE via
  T301), **not** a missing row. Directly enables FR-1/AC-1 "never-seen → OFFLINE" and
  T901's "one result per expected sensor". Lookup of an expected sensor with no profile
  surfaces the unknown-type signal (T103), never a crash.

---

## Phase 2 — Supabase schema [DB-DEP]

- **T201 — `raw_readings` table, append-only.**
  Columns: time (sensor timestamp), ingest_time, sensor_id, sensor_type, value (nullable),
  unit, raw_payload.
  **Acceptance:** schema/migration written; **UPDATE and DELETE are revoked** for the
  service role (append-only is a DB guarantee, not a convention — Const. II); both the
  sensor `time` and `ingest_time` are stored so clock-drift (G4) is computable. [DB-DEP:
  live enforcement verified when a Supabase instance exists.]

- **T202 — `validated_readings` table (reading-status + flags).**
  Columns: time (sensor ts), sensor_id, value (nullable), reading_status
  (`OK|INTERPOLATED|SPIKE|CORRUPT|NO_DATA|PENDING` — **six terminal values, unchanged**),
  `is_interpolated`, **`clock_drift`** (bool flag), source_raw_ids, cycle_id, superseded_by.
  **Acceptance:** all six reading-status values representable; `clock_drift` co-exists with
  any reading_status (a reading can be `OK` **and** `clock_drift=true` — G4 "still
  process"); row links to raw source ids; `superseded_by` supports the late-arrival
  correction chain (T801).
  > **Modeling note (G4):** CLOCK_DRIFT is a **flag**, not a terminal reading-status,
  > because the reading is still processed and keeps its normal status. If you intended a
  > terminal status that *replaces* OK, this is the line to change.

- **T203 — `sensor_status` table (device health).**
  Columns: sensor_id, status (`LIVE|OFFLINE`), missed_count, last_seen (sensor ts),
  updated_at.
  **Acceptance:** distinct from validated_readings; can hold OFFLINE **simultaneously**
  with a NO_DATA reading row (Q4 co-existence — AC-4); OFFLINE is written **only** by the
  liveness path (G2 — single owner).

- **T204 — `decision_log` table (audit).**
  Columns: time, sensor_id, decision
  (`LIVENESS|RANGE|SPIKE|GAP|PENDING|CORRECTION|PARSE|CLOCK_DRIFT|DUPLICATE_CONFLICT`),
  old_status, new_status, raw_value, raw_payload, reason. For DUPLICATE_CONFLICT the
  reason records **both** values (G4 dup rule); for CLOCK_DRIFT the gap and tolerance.
  **Acceptance:** can record timestamp + causing input + human-readable reason for every
  decision type, incl. `old_status → new_status` for corrections, both values for a
  duplicate conflict, and the drift gap for clock-drift (FR-7, Const. VI).

---

## Phase 3 — Liveness check (FR-1, owns OFFLINE) + test

- **T301 — `check_liveness(state, now, profile)`.**
  Counts consecutive missed reports against `cadence_s` using the **sensor's own
  timestamp** (G4); **3 missed → OFFLINE**; per-type; **no global wall-clock rule**.
  Liveness is the **sole writer of sensor-status OFFLINE/LIVE** (G2). Operates over the
  expected-sensor registry (T104) so a fully-silent sensor is evaluated.
  **Acceptance:** pure function (clock injected); threshold read from profile, not
  hardcoded; missed-count derived from sensor timestamps; no other check sets OFFLINE.

- **T302 — Test liveness (AC-1).**
  **Acceptance:** live within cadence → LIVE; 1–2 missed → still LIVE; **3 missed → OFFLINE
  within one cycle**; a registry sensor that sent **nothing** → OFFLINE (via T104). A
  fast-cadence and a slow-cadence sensor both flip at exactly 3 missed (per-type scaling,
  not a flat 5-min rule). = **AC-1**.

---

## Phase 4 — Range check (FR-2) + test

- **T401 — `check_range(value, profile)`.**
  CORRUPT if `value < phys_min` or `> phys_max`; reason names value + violated bound +
  unit. Unknown profile → CORRUPT. None/NaN/non-numeric → CORRUPT (no crash).
  **Acceptance:** pure; reason is human-readable and names the bound + unit.

- **T402 — Test range (AC-2).**
  **Acceptance:** in-range → pass; below min / above max → **CORRUPT with logged reason and
  not passed downstream**; exact boundary → pass; None/NaN → CORRUPT; unknown type →
  CORRUPT. = **AC-2**. (Uses a fixture profile with concrete bounds since real bounds are TODO.)

---

## Phase 5 — Spike/PENDING detection + σ-baseline (FR-3) + test

- **T501 — `compute_baseline(history, now, profile)`.**
  Baseline = **the most recent ≤`baseline_max_n` (100) readings that ALSO fall within
  `baseline_max_age_h` (24h)** — the **intersection** of both caps (G5), built from
  **OK/trustworthy readings only** (exclude SPIKE, CORRUPT, PENDING, NO_DATA, and
  interpolated values — G1). Return mean/σ. <2 qualifying samples or zero-variance →
  "insufficient baseline" signal (no divide-by-zero).
  **Acceptance:** (i) >100 OK readings within 24h → exactly 100 kept; (ii) <100 readings
  but spanning >24h → only the within-24h subset kept (both caps applied as an
  intersection, asserted separately); (iii) a window polluted with SPIKE/CORRUPT/
  interpolated values excludes them from mean/σ; (iv) insufficient/zero-variance handled
  without error. = σ-baseline decision + G1 + G5.

- **T502 — `check_spike(value, baseline, profile)`.**
  `> ±3σ` → spike **candidate** → written `PENDING`; else NORMAL. Insufficient baseline →
  NORMAL (cannot judge).
  **Acceptance:** a >3σ value yields candidate→PENDING; ≤3σ yields NORMAL; insufficient
  baseline yields NORMAL, not a false spike.

- **T503 — Test single-point spike (AC-3a).**
  **Acceptance:** a >3σ reading whose next **3** readings return to baseline → finalised
  **SPIKE**, withheld from downstream. = **AC-3** (unconfirmed half).

- **T504 — Test confirmed shift (AC-3b).**
  **Acceptance:** a >3σ change **sustained across the next 3 readings** → released as `OK`
  real signal (not suppressed). = **AC-3** (confirmed half), confirm-count=3.

---

## Phase 6 — Gap-fill / interpolation (FR-4, sets reading-status only) + test

- **T601 — `fill_gaps(timeline, profile)`.**
  1–2 consecutive missing → linear interpolation, marked `INTERPOLATED`. 3+ → `NO_DATA`,
  no interpolation (**cap=2**). Gap-fill sets **only the reading-status** (INTERPOLATED /
  NO_DATA) and **never touches sensor-status** — OFFLINE is liveness's job (G2).
  **Acceptance:** pure; interpolation linear (midpoint exact); cap=2 enforced; function
  returns no sensor-status mutation (asserted — G2 single owner).

- **T602 — Test short gap (AC-4a).**
  **Acceptance:** 1 and 2 missing → value = linear interpolation of neighbours,
  `is_interpolated=true`, status `INTERPOLATED`. Sensor remains **LIVE** (set by liveness,
  since <3 missed). = **AC-4** (short half).

- **T603 — Test long gap + co-existence (AC-4b, G2).**
  **Acceptance:** 3+ missing → reading-status **NO_DATA** (value null, not interpolated)
  from gap-fill, **and** sensor-status **OFFLINE** from **liveness** (same 3-missed
  condition, single owner). Assert both axes co-emitted AND that the OFFLINE write
  originates from the liveness path, not gap-fill. = **AC-4** + Q4 + G2.

---

## Phase 7 — PENDING resolution + OFFLINE interaction (FR-5) + test

- **T701 — `resolve_pending(pending, state, now, profile)`.**
  Resolves on the first of: (a) 3-reading window fills → `OK`/`SPIKE` per sustain; (b)
  sensor **OFFLINE** → `SPIKE (unconfirmed)`; (c) elapsed time **strictly > 3× cadence**
  (with buffer so an on-time 3rd reading always resolves first — **no exact-tie reachable**,
  G3) → `SPIKE (unconfirmed)`. Returns resolution + reason.
  **Acceptance:** pure; all three triggers reachable; an on-time 3rd confirming reading at
  ≈3× cadence resolves via (a), **never** races (c) (assert the strict-`>` + buffer); never
  returns "still pending" once a terminal trigger fires.

- **T702 — Test PENDING normal fill (AC-5 path a).**
  **Acceptance:** 3 confirming readings arrive on schedule → resolves `OK` if sustained,
  `SPIKE` if not, **before** any timeout (G3 buffer verified at the boundary).

- **T703 — Test PENDING safety-net (AC-5 paths b & c).**
  **Acceptance:** (b) spike then sensor hits 3 missed → OFFLINE → PENDING finalised **SPIKE
  (unconfirmed)**; (c) spike then elapsed **> 3× cadence** with <3 confirming → **SPIKE
  (unconfirmed)**. A PENDING is **never left unresolved**. = **AC-5**.

---

## Phase 8 — Late-arrival handling + bounded recompute + test

- **T801 — `handle_late_arrival(reading, processed_window, now, profile)`.**
  Uses the **sensor's own timestamp** (G4) to place the reading. If within the **3×
  interval lookback** of now: recompute affected derived results, write **new** validated
  rows, set prior row `superseded_by`, log a **CORRECTION** (`old_status → new_status`,
  reason `"late-arrival recompute"`). Outside the window: keep raw-only, log "outside
  recompute window". **Raw is never overwritten.**
  **Acceptance:** within-window late reading produces a correction chain + log entry; raw
  row count only ever grows (no UPDATE/DELETE on raw).

- **T802 — Test late-arrival (decision check).**
  **Acceptance:** (a) reading 2× cadence old → recomputed, decision_log has CORRECTION with
  reason "late-arrival recompute" and old→new status; (b) reading 4× cadence old → raw-only,
  logged "outside recompute window"; (c) in **both** cases the original raw reading is
  unchanged (no silent overwrite). = late-arrival decision.

---

## Phase 9 — Orchestration (wire Phases 3–8) + Supabase writes + audit

- **T901 — `process_cycle(readings, registry, states, profiles, now)`.**
  Order: safe-parse → clock-drift annotate (T905) → dedup(sensor+ts, first-wins) → sort by
  **sensor timestamp** → **iterate the expected-sensor registry (T104)** → liveness
  (owns OFFLINE) → range → spike/PENDING → gap-fill (NO_DATA only) → resolve-pending →
  late-arrival → emit per-sensor `sensor_status` + `reading_status` (+`clock_drift` flag).
  **Acceptance:** returns **one result per expected sensor** (from registry, incl. silent
  ones); precedence correct (CORRUPT not interpolated; OFFLINE from liveness co-emitted
  with NO_DATA from gap-fill); deterministic given injected clock.

- **T902 — `safe_parse` + per-sensor isolation (FR-6).**
  Missing field/wrong type/bad ts/non-numeric → `CORRUPT` + reason, never raises. One
  sensor erroring internally → that sensor gets error status + logged reason; others still
  processed; cycle never aborts.
  **Acceptance:** 4 malformed shapes → CORRUPT+reason, no exception; injected failure in one
  sensor doesn't abort the cycle. = **AC-7** + FR-6.

- **T903 — Persist cycle to Supabase + decision log [DB-DEP].**
  Append raw on receipt (before validation, storing sensor time + ingest_time); write
  validated rows + sensor_status; write a decision_log row for every reject/flag/interp/
  status-change/correction/clock-drift/dup-conflict. OK flow recorded by validated rows
  (not spammed to log).
  **Acceptance (fake store now):** a cycle with 1 CORRUPT + 1 interpolation + 1 correction
  + 1 clock-drift + 1 dup-conflict produces exactly the expected validated + log rows, each
  with reason; every derived row links to raw source ids (FR-7, Const. II/VI). [DB-DEP:
  live Supabase deferred.]

- **T904 — Dedup (first-wins + conflict log) + out-of-order (G4).**
  Out-of-order readings sorted by **sensor timestamp**. Same sensor+timestamp: **identical**
  value → silently deduped (raw duplicates preserved); **different** value → keep the
  **first-received**, discard the second, log `DUPLICATE_CONFLICT` recording **both** values,
  reason `"duplicate timestamp, conflicting value, first-received kept"`. No averaging.
  **Acceptance:** identical dup → one logical reading, raw retained; conflicting dup → first
  kept, second discarded + DUPLICATE_CONFLICT logged with both values + exact reason string;
  out-of-order sorted by sensor ts. = AC-7 (dup/order) + dup-conflict decision.

- **T905 — Clock-drift detection (NEW — G4).**
  Compute |sensor-timestamp − ingest-time|; if it exceeds the profile's
  `clock_drift_tolerance_s`, set the reading's `clock_drift` flag and log a `CLOCK_DRIFT`
  decision (gap + tolerance in the reason). The reading is **still processed using its
  sensor timestamp**; its reading-status is unaffected.
  **Acceptance:** gap > tolerance → `clock_drift=true` + CLOCK_DRIFT log entry, **and** the
  reading still flows through the normal checks (e.g. an in-range drifted reading is still
  `OK`, just flagged); gap ≤ tolerance → no flag, no log. = G4.

---

## Phase 10 — n8n trigger wiring (MQTT → batch → invoke)

- **T1001 — Service invocation entrypoint.**
  A single callable/HTTP entry n8n can hit with a batch of readings for a cycle; returns a
  structured per-cycle summary.
  **Acceptance:** given a JSON batch, returns per-sensor statuses; malformed batch →
  structured error, never a stack trace (FR-6).

- **T1002 — n8n workflow definition (glue only).**
  n8n: subscribe to MQTT (Mosquitto), batch messages per processing cycle, invoke T1001,
  retry the **trigger** on failure. No validation logic in n8n.
  **Acceptance:** workflow doc/export exists; MQTT topic → batch → invoke path described;
  explicitly contains **no** validation logic (Const. III modularity — n8n is glue). [DB/MQTT
  live verification deferred — no broker locally.]

---

## Phase 11 — End-to-end test (every AC in spec.md)

- **T1101 — Simulated multi-sensor stream harness.**
  Scripted streams via injected clock: normal, offline (3 missed), silent-from-registry,
  corrupt, single spike, sustained shift, short gap, long gap, late-arrival (in & out of
  window), unknown type, identical duplicate, conflicting duplicate, out-of-order,
  clock-drift.
  **Acceptance:** deterministic and replayable; covers every scenario in spec + the
  reviewed decisions.

- **T1102 — E2E asserting AC-1…AC-7.**
  **Acceptance:** drive multiple cycles; assert each AC manifests in validated_readings +
  sensor_status + decision_log:
  AC-1 offline at 3 missed (incl. silent-registry sensor) · AC-2 corrupt rejected+logged ·
  AC-3 spike vs confirmed shift · AC-4 short interp / long NO_DATA + OFFLINE(from liveness) ·
  AC-5 PENDING safety-net · AC-6 normal `OK` · AC-7 malformed/dup-conflict/out-of-order/
  unknown/clock-drift never crash or silently drop. = **all spec ACs**.

- **T1103 — Constitution V four-scenario test.**
  **Acceptance:** explicit normal / missing / corrupt / offline tests pass, plus
  never-crash and raw-append-only assertions (Principle V + II).

---

## Phase 12 — README (module docs)

- **T1201 — Module README.**
  Inputs (reading payload shape), outputs (the two status axes + values + the `clock_drift`
  / `is_interpolated` flags), the pipeline order, the four checks, PENDING/late-arrival/
  clock-drift/dup-conflict rules, and explicit out-of-scope (danger scoring, FFT, alerts).
  **Acceptance:** README present; documents inputs, outputs, and the status model; matches
  the implemented contract.

- **T1202 — "Add a new sensor type via config only" guide.**
  Step-by-step: add a `SensorProfile` entry (+ registry entry + seed row), fill bounds/
  cadence/drift-tolerance, **no check-code change**.
  **Acceptance:** following the guide for a hypothetical 8th type requires only config
  edits — validates the "config, not code" decision (spec edge-case rule).

---

## Dependency Order

```
P1 (config + registry) ─► P2 (schema) ─► P3,P4,P5,P6,P7,P8 (checks; parallel after P1/P2)
                                              └─► P9 (orchestration; uses registry T104,
                                                     clock-drift T905, dup-conflict T904)
                                                     └─► P10 (n8n)
                                                     └─► P11 (E2E) ─► P12 (README)
```
- Config + registry (P1) and schema (P2) precede all logic that reads them.
- The six check phases (P3–P8) are independent of each other; each needs only P1/P2.
- T905 (clock-drift) and T104 (registry) are consumed by T901; T904 dup-conflict is part
  of the orchestration pre-checks.
- P9 requires all checks; P11 requires P9 (+P10 for the trigger path).

## Coverage (tasks ↔ acceptance criteria / decisions)

| AC / Decision | Tasks |
|---------------|-------|
| AC-1 offline (3 missed, per-type, silent-registry) | T104, T301/T302, T1102, T1103 |
| AC-2 corrupt rejected+logged | T401/T402, T903, T1102 |
| AC-3 spike vs confirmed shift (count=3) | T501–T504, T1102 |
| AC-4 short interp / long NO_DATA + OFFLINE | T601–T603, T1102 |
| AC-5 PENDING safety-net (>3× timeout) | T701–T703, T1102 |
| AC-6 normal pass-through | T901, T1102 |
| AC-7 edge cases never crash/drop | T902, T904, T905, T103, T1102 |
| B1 expected-sensor registry | T104, T301, T901 |
| G1 baseline = OK-only | T501 |
| G2 liveness owns OFFLINE | T301, T601, T603 |
| G3 timeout strictly > 3× cadence | T701, T702 |
| G4 sensor-ts ordering + CLOCK_DRIFT | T201, T202, T301, T801, T904, T905 |
| dup-conflict first-wins + logged | T204, T904 |
| σ-baseline 100∩24h | T501 |
| Late-arrival correction (no overwrite) | T801, T802 |
| Const. II append-only/traceable | T201, T903, T801 |
| Const. VI auditability | T204, T903 |
| Const. V four scenarios | T1103 |

## Open (non-blocking) — carried config TODOs

- Per-type physical bounds, exact cadence, and `clock_drift_tolerance_s` (structural
  engineer) — `TODO` in T101/T102. Constants only; no task logic depends on the numbers.
- **Already-built `SensorProfile` (T101) needs the `clock_drift_tolerance_s` field added**
  during implementation continuation.
- **[DB-DEP] / MQTT-live:** P2 schema enforcement, T903 persistence, and T1002 n8n path
  need live Supabase + a broker to verify end-to-end; built against fakes now, live
  verification deferred (none available locally — flagged, not faked).
