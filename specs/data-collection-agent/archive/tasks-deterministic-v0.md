# Tasks: Data Collection Agent

**Feature:** `001-data-collection-agent`
**Created:** 2026-06-20
**Status:** Draft — awaiting review before implementation
**Plan:** `specs/001-data-collection-agent/plan.md`
**Spec:** `specs/001-data-collection-agent/spec.md`
**Constitution:** v1.0.0

## Conventions

- **[P]** = parallelizable (no dependency on an unfinished sibling in the same batch).
- Each task is sized for < 1 hour, has one clear **Done** condition, and is ordered
  so earlier tasks unblock later ones.
- "Test passes" means the named unit test is green; pure-function checks use
  fixtures (FixedClock, FakeStore, profile fixtures) — no live DB/MQTT.
- Status enum everywhere: `OK | OFFLINE | CORRUPT | SPIKE | NO_DATA`.

---

## Phase 0 — Project Scaffolding (prerequisite)

- **T001 — Create package skeleton.**
  Create `src/agents/data_collection/` with empty `__init__.py` files and the
  subfolders `checks/`, `config/` plus the placeholder module files from plan §2.
  **Done:** `python -c "import agents.data_collection"` succeeds; folder tree
  matches plan §2.

- **T002 — [P] Add dev dependencies & test runner.**
  Add `pytest`, `paho-mqtt`, DB driver (`psycopg`/SQLAlchemy), and a scheduler lib
  to project deps; configure `pytest` discovery.
  **Done:** `pytest` runs and collects 0 tests without error.

- **T003 — [P] Define core dataclasses in `models.py`.**
  `RawReading`, `ValidationResult` (frozen, per plan §7), `ValidationLogEntry`,
  `CycleSummary`. No logic, just typed structures + the status `Literal`.
  **Done:** import succeeds; a `ValidationResult` can be constructed; field types
  match the §7 contract.

---

## Phase 1 — Data Model Setup (TimescaleDB)

- **T101 — Migration: `raw_readings` hypertable.**
  Columns per plan §3 (`time, sensor_id, sensor_type, value, unit, payload_raw,
  ingest_time`); create hypertable on `time`.
  **Done:** migration applies; `\d raw_readings` shows columns; `SELECT
  create_hypertable` succeeded.

- **T102 — Enforce raw append-only.**
  `REVOKE UPDATE, DELETE ON raw_readings` from the agent's DB role.
  **Done:** an `UPDATE`/`DELETE` as the agent role fails with a permission error
  (this is the test); `INSERT`/`SELECT` succeed. (Constitution II.)

- **T103 — [P] Migration: `validated_readings` hypertable.**
  Columns per §3 (`time, sensor_id, value, status, is_interpolated,
  source_raw_ids, cycle_id`); hypertable on `time`.
  **Done:** migration applies; columns + hypertable confirmed.

- **T104 — [P] Migration: `validation_log` hypertable.**
  Columns per §3 (`time, sensor_id, decision, status_emitted, raw_value,
  raw_payload, reason`); hypertable on `time`; append-only REVOKE as T102.
  **Done:** migration applies; append-only enforced.

- **T105 — `store.py` persistence boundary.**
  Implement `read_recent(sensor_id, window)`, `write_result(...)`,
  `write_log(...)`, plus a `FakeStore` in-memory double for tests.
  **Done:** round-trip unit test — write a result + log, read them back via
  FakeStore; real-DB version behind same interface.

---

## Phase 2 — Per-Sensor-Type Range Configuration

- **T201 — `SensorProfile` structure + defaults file.**
  Define `SensorProfile` (plan §4 fields) in `config/sensor_profiles.py` with one
  entry per type: `accelerometer, strain_gauge, tiltmeter, crack_sensor,
  temperature, humidity, load_cell, scour_sensor, anemometer`. Ranges/windows are
  `TODO`-marked placeholders (per Open Q-B default).
  **Done:** all 9 types present; each has phys_min/max, report_interval_s,
  offline_after_s, zscore_threshold, baseline_window_n, confirm_window_n,
  max_interp_gap; placeholders clearly flagged.

- **T202 — Migration: `sensor_profiles` table + seed.**
  DB table mirroring the struct; seed from the defaults file.
  **Done:** migration applies; `SELECT * FROM sensor_profiles` returns 9 rows.

- **T203 — `ProfileProvider` lookup.**
  `get(sensor_type) -> SensorProfile`; unknown type returns a structured "unknown
  type" signal (NOT an exception — feeds CORRUPT path later).
  **Done:** test: known type returns profile; unknown type returns the unknown
  signal, no raise.

---

## Phase 3 — Liveness Check (OFFLINE)

- **T301 — `check_liveness(last_seen, now, profile)` pure function.**
  Returns OFFLINE verdict when `now - last_seen > offline_after_s`, else live.
  **Done:** function is pure (no I/O, clock passed in).

- **T302 — Test liveness.**
  Cases: fresh reading → live; exactly-at-threshold boundary; stale beyond
  threshold → OFFLINE (AC-1); never-seen sensor → OFFLINE (US-2 blind-spot).
  **Done:** test green; covers boundary + missing-sensor case.

---

## Phase 4 — Range Check (CORRUPT)

- **T401 — `check_range(value, profile)` pure function.**
  CORRUPT if `value < phys_min` or `> phys_max`, with a reason string naming the
  value, bound, and unit. Unknown-type profile → CORRUPT.
  **Done:** function pure; reason string is human-readable (Principle I/VI).

- **T402 — Test range check.**
  In-range → pass; below min → CORRUPT; above max → CORRUPT; at exact boundary →
  pass; non-numeric/None value → CORRUPT (not a crash).
  **Done:** test green; AC-2 covered; reason asserted.

---

## Phase 5 — Outlier / Spike Detection (SPIKE vs real)

- **T501 — `zscore(value, history, profile)` helper.**
  Compute deviation in σ from the baseline window mean; handle <2 samples and
  zero-variance windows gracefully (return a defined "insufficient baseline"
  signal, no divide-by-zero).
  **Done:** unit test for normal, insufficient-history, and zero-variance cases.

- **T502 — `check_spike(value, history, profile, pending_state)` core logic.**
  A >Z-threshold reading becomes a *pending* candidate; verdict deferred until the
  confirmation window fills. Sustained across `confirm_window_n` consecutive
  points → REAL (pass through); not sustained → SPIKE.
  **Done:** function pure; returns one of {NORMAL, PENDING, SPIKE, REAL} given
  state; no DB.

- **T503 — Test single-point spike.**
  One >3σ reading, next 2–3 readings return to baseline → `SPIKE`, value withheld
  (AC-3).
  **Done:** test green; AC-3 asserted.

- **T504 — Test confirmed sustained shift.**
  >3σ reading sustained across the confirmation window → `OK` real signal, passed
  through (AC-4).
  **Done:** test green; AC-4 asserted; verifies a real structural change is NOT
  suppressed.

---

## Phase 6 — Gap Filling (interpolation / NO_DATA)

- **T601 — `fill_gaps(timeline, profile)` pure function.**
  1–2 consecutive missing → linear interpolation between surrounding good values,
  marked `is_interpolated=True`. ≥3 consecutive missing → `NO_DATA`, no
  interpolation (cap = `max_interp_gap` = 2).
  **Done:** function pure; interpolation is linear; cap enforced.

- **T602 — Test short gap (interpolated).**
  1 missing and 2 missing → interpolated values equal the linear midpoint(s);
  `is_interpolated=True`; status `OK` (AC-5).
  **Done:** test green; numeric interpolation asserted; AC-5 covered.

- **T603 — Test long gap (NO_DATA).**
  3+ consecutive missing → `NO_DATA`, value NULL, no interpolation (AC-6).
  **Done:** test green; AC-6 covered; confirms no guessed values.

---

## Phase 7 — Integration: `process_reading()` / `run_cycle()`

- **T701 — `process_reading(reading, state, profile, now)` orchestration.**
  Compose the four checks in plan order: liveness → range → spike → gap, producing
  one `ValidationResult` per the §7 contract. Pure given injected state/clock.
  **Done:** returns a contract-shaped `ValidationResult`; precedence correct
  (OFFLINE short-circuits range, etc.).

- **T702 — Per-sensor state management in `state.py`.**
  Rolling history window, last-seen, consecutive-missing counter, pending-spike
  carry-over across cycles.
  **Done:** unit test: state updates correctly across 3 simulated cycles.

- **T703 — `run_cycle(now)` over all expected sensors.**
  Iterate expected sensors, call `process_reading`, write results + logs via store.
  Guarantees one result per expected sensor (absent → OFFLINE).
  **Done:** test with FakeStore + 3 fixture sensors returns 3 results; an absent
  sensor appears as OFFLINE.

- **T704 — Per-sensor & cycle-level isolation guards.**
  Wrap each sensor's processing so one failure degrades only that sensor; cycle
  entrypoint catches escapes and survives (plan §6).
  **Done:** test: one sensor configured to raise internally → that sensor gets an
  error status, others still processed (T12 from plan).

---

## Phase 8 — Logging / Audit Trail

- **T801 — Reason-string generation per check.**
  Each check emits a specific human-readable reason (examples in plan §5).
  **Done:** unit test asserts reason format for RANGE, LIVENESS, SPIKE, GAP.

- **T802 — Wire audit writes into `run_cycle`.**
  Every flag/reject/interpolation/status-change writes a `validation_log` row with
  timestamp + causing input + reason (Constitution VI; Open Q-C default = log
  flags/transforms, OK flow recorded by `validated_readings`).
  **Done:** test: a cycle with 1 CORRUPT + 1 interpolation produces exactly the
  expected `validation_log` rows, each with reason + causing input.

- **T803 — Malformed-payload path → CORRUPT (`errors.safe_parse`).**
  Defensive parser: missing field, wrong type, bad timestamp, non-numeric value →
  structured `CORRUPT` + reason, never raises (Open Q-D default).
  **Done:** test: 4 malformed payloads each yield CORRUPT + reason, no exception
  (AC-7 / Principle IV).

---

## Phase 9 — End-to-End Acceptance Test

- **T901 — Simulated sensor data harness.**
  A generator that emits scripted streams per sensor (normal, offline gap, corrupt
  value, single spike, sustained shift, short gap, long gap) into a FakeStore.
  **Done:** harness produces deterministic, replayable streams via injected clock.

- **T902 — E2E test asserting every acceptance criterion.**
  Drive multiple cycles through `run_cycle`; assert AC-1…AC-7 each manifest in
  `validated_readings` / `validation_log`:
  - AC-1 offline within one cycle · AC-2 corrupt rejected+logged · AC-3 spike
    suppressed · AC-4 sustained passes · AC-5 short gap interpolated · AC-6 long
    gap NO_DATA · AC-7 malformed never crashes.
  **Done:** single test (or tight suite) green covering all 7 ACs end to end.

- **T903 — [P] Raw-immutability + audit-completeness assertions.**
  After the E2E run, assert raw rows unchanged and every derived row links to raw
  source; assert every flag/transform has a matching log row (plan T10/T11).
  **Done:** test green; Constitution II & VI verified end to end.

---

## Phase 10 — Documentation

- **T1001 — Module README.**
  `src/agents/data_collection/README.md`: purpose, position in pipeline, the §7
  input/output contract, the five statuses + `is_interpolated`, and the four
  checks. Explicit "out of scope" list (danger scoring, FFT, alerting).
  **Done:** README present; contract + statuses documented; matches code.

- **T1002 — [P] "Adding a new sensor type" guide.**
  Step-by-step: add a `SensorProfile` entry + seed row, fill ranges/windows, no
  check-code change required (validates plan §4 extensibility claim).
  **Done:** guide present; following it for a hypothetical 10th type requires only
  config edits.

---

## Dependency Order (summary)

```
Phase 0  ──► Phase 1 ──► Phase 2 ──► Phases 3,4,5,6 (parallel after config)
                                          └──► Phase 7 (integration) ──► Phase 8
                                                          └──► Phase 9 (E2E) ──► Phase 10
```

- Phases 3–6 (the four check functions) are mutually independent once Phase 2
  (config) lands — they can be built in parallel.
- Phase 7 requires all four checks. Phase 8 builds on Phase 7. Phase 9 requires 7+8.
  Phase 10 is last but T1002 can start once Phase 2 is stable.

## Coverage Check (tasks ↔ acceptance criteria)

| AC / Principle | Task(s) |
|----------------|---------|
| AC-1 offline within a cycle | T301/T302, T703, T902 |
| AC-2 corrupt rejected + logged | T401/T402, T802, T902 |
| AC-3 spike suppressed | T502/T503, T902 |
| AC-4 sustained shift passes | T504, T902 |
| AC-5 short gap interpolated | T601/T602, T902 |
| AC-6 long gap NO_DATA | T603, T902 |
| AC-7 never crashes | T704, T803, T902 |
| Const. II append-only/provenance | T102, T104, T903 |
| Const. VI auditability | T801, T802, T903 |
| Const. V four mandatory scenarios | T302, T402, T803, T302(offline) + E2E |

## Open Items (carried from plan — confirm during review)

Q-A interpolation-as-OK+flag · Q-B placeholder ranges · Q-C log flags/transforms only ·
Q-D malformed→CORRUPT · Q-E DB-table primary contract · Q-F drift out-of-scope.
