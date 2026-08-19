# Implementation Plan: Data Collection Agent

**Feature:** `001-data-collection-agent`
**Created:** 2026-06-20
**Status:** Draft — awaiting confirmation before task breakdown
**Spec:** `specs/001-data-collection-agent/spec.md`
**Constitution:** v1.0.0 (`.specify/memory/constitution.md`)

> Architecture and data-flow design only. No implementation code in this document.

## 1. Technical Context

| Aspect | Decision |
|--------|----------|
| Language / runtime | Python 3.11+ |
| Position in pipeline | Between MQTT ingestion (LoRaWAN gateway) and the Structural Analysis Agent |
| Input | Raw sensor payload: `sensor_id, sensor_type, value, unit, timestamp` via MQTT |
| Output | One structured validation result per sensor per cycle, written to PostgreSQL/TimescaleDB |
| Output status enum | `OK \| OFFLINE \| CORRUPT \| SPIKE \| NO_DATA` |
| Execution model | Scheduled background process, every 1–5 min (NOT request/response) |
| AI usage | **None** — this agent is fully deterministic (Constitution Principle IV) |

### Cycle / scheduler

The agent runs as a background worker, not a web service. Two cleanly separable
concerns:

- **Ingestion side (continuous):** An MQTT subscriber persists every raw payload
  to the append-only raw table the instant it arrives. This thread does *no*
  validation — its only job is to never lose a raw reading (Principle II).
- **Validation side (scheduled, every 1–5 min):** A scheduler tick invokes
  `DataCollectionAgent.run_cycle()`, which reads the latest raw window per sensor,
  runs the four checks, and writes validation results + audit logs.

Decoupling ingestion from validation means a slow/failed validation cycle can
never cause raw-data loss, and the validation cadence can be tuned independently.
[ASSUMPTION: scheduler is APScheduler or a plain loop+sleep worker; final choice
deferred to tasks. Ingestion MQTT client is `paho-mqtt`.]

## 2. Module Structure

A standalone, importable library — no framework coupling, independently testable
(Principle III). Proposed layout:

```
src/agents/data_collection/
  __init__.py
  agent.py            # DataCollectionAgent — orchestrates one cycle
  checks/
    __init__.py
    liveness.py       # check_liveness()  -> OFFLINE detection
    range_check.py    # check_range()     -> CORRUPT detection
    spike.py          # check_spike()     -> SPIKE vs real-signal (Z-score + confirmation)
    gap_fill.py       # fill_gaps()       -> linear interpolation (≤2) / NO_DATA (≥3)
  config/
    sensor_profiles.py # per-sensor-type ranges, units, window sizes (see §4)
  models.py           # dataclasses: RawReading, ValidationResult, ValidationLogEntry
  store.py            # persistence boundary (read raw window, write results + logs)
  state.py            # per-sensor rolling state (history, last-seen, gap counter, pending spike)
  errors.py           # payload parsing -> structured status, never raises out
tests/agents/data_collection/
  ...                 # see §8
```

Key boundary rules:
- `checks/*` are **pure functions**: given a reading + sensor state + profile,
  return a verdict. No I/O, no DB, no clock access beyond what's passed in. This
  makes them trivially unit-testable against all four constitution scenarios.
- `agent.py` is the only place that wires checks together and touches `store.py`.
- Nothing outside this package reaches into `checks/` or `state/` — downstream
  consumers use only the §7 contract.

### Cycle orchestration (data flow per tick)

```
run_cycle(now):
  for sensor in expected_sensors():
     raw_window = store.read_recent(sensor.id, window)      # append-only read
     parsed     = errors.safe_parse(raw_window)             # never throws (§6)
     if liveness says stale          -> result = OFFLINE
     elif latest value out of range  -> result = CORRUPT   (+ audit reason)
     else:
        spike_verdict = check_spike(latest, history, profile, pending_state)
        if spike_verdict == SPIKE    -> result = SPIKE      (+ audit reason)
        elif spike_verdict == REAL   -> result = OK         (sustained shift passes through)
        else (PENDING/unconfirmed)   -> hold, no downstream emit this cycle
     # gap handling runs over the assembled timeline:
     gap_fill applies interpolation (≤2 missing) or NO_DATA (≥3 missing)
     store.write_result(result)        # derived record, links to raw source(s)
     store.write_log(audit_entry)      # every flag/reject/interp/status change
  return CycleSummary(per_sensor statuses)
```

## 3. Data Model (TimescaleDB)

Three concerns, never co-mingled, raw never mutated (Principle II):

### `raw_readings` (hypertable, append-only)
| column | type | notes |
|--------|------|-------|
| time | TIMESTAMPTZ | partition key (hypertable on `time`) |
| sensor_id | TEXT | |
| sensor_type | TEXT | |
| value | DOUBLE PRECISION | nullable (missing/garbled value still recorded) |
| unit | TEXT | |
| payload_raw | JSONB | the exact original payload, for forensic replay |
| ingest_time | TIMESTAMPTZ | when we received it (vs sensor's `time`) |

- **Append-only enforced at the DB layer**: `REVOKE UPDATE, DELETE` on this table
  for the agent's role; only `INSERT`/`SELECT`. This makes the immutability a
  database guarantee, not a code convention (Operational Constraints, Principle II).

### `validated_readings` (hypertable, derived)
| column | type | notes |
|--------|------|-------|
| time | TIMESTAMPTZ | |
| sensor_id | TEXT | |
| value | DOUBLE PRECISION | the trustworthy value (or NULL for OFFLINE/NO_DATA/CORRUPT) |
| status | TEXT | `OK \| OFFLINE \| CORRUPT \| SPIKE \| NO_DATA` |
| is_interpolated | BOOLEAN | TRUE when value was reconstructed (≤2 gap) |
| source_raw_ids | array/refs | link(s) back to the raw record(s) that produced this |
| cycle_id | UUID | groups all results from one `run_cycle()` |

### `validation_log` (hypertable, audit — Principle VI)
| column | type | notes |
|--------|------|-------|
| time | TIMESTAMPTZ | timestamp of the decision |
| sensor_id | TEXT | |
| decision | TEXT | which check fired (LIVENESS/RANGE/SPIKE/GAP/PARSE) |
| status_emitted | TEXT | resulting status |
| raw_value | DOUBLE PRECISION | the causing input value |
| raw_payload | JSONB | full causing input |
| reason | TEXT | **human-readable WHY** (e.g. "value 812.0 g exceeds accelerometer max 16.0 g") |

Audit answers "what was decided, when, on the basis of what input" from the log
alone. Reason strings are mandatory and human-readable, not bare codes
(Principles I & VI).

> Note on status enum vs internal interpolation: the *output* status set is the
> five values you specified. Interpolation is represented as `status=OK` +
> `is_interpolated=TRUE` rather than as its own status, so downstream consumers
> have one clean "is this usable?" axis. Confirm this is the intent (Open Q-A).

## 4. Per-Sensor-Type Configuration

Validation parameters differ per sensor type. Config is **data, not code** — a
single declarative profile table so new sensor types are added without touching
check logic (extensibility requirement).

Proposed profile shape (one entry per type):

```
SensorProfile:
  sensor_type        : str        # "accelerometer", "strain_gauge", ...
  unit               : str        # canonical unit
  phys_min           : float      # CORRUPT below this
  phys_max           : float      # CORRUPT above this
  report_interval_s  : int        # expected reporting cadence
  offline_after_s    : int        # liveness threshold (default report_interval * N)
  zscore_threshold   : float      # default 3.0
  baseline_window_n  : int        # # recent readings for mean/σ
  confirm_window_n   : int        # # subsequent readings to confirm spike-vs-real (2–3)
  max_interp_gap     : int        # = 2 (cap), per spec
```

Covered types (values to be filled — see Open Q-B):
`accelerometer, strain_gauge, tiltmeter, crack_sensor, temperature, humidity,
load_cell, scour_sensor, anemometer`.

Storage decision: profiles live in a versioned `sensor_profiles` **DB table**
(seeded from `config/sensor_profiles.py` defaults), so:
- engineers can adjust a range without a code deploy,
- every change is itself auditable (who changed a bound, when),
- the agent reads the active profile per cycle.

[ASSUMPTION pending your numbers: I will scaffold the table with placeholder
phys_min/phys_max and window sizes, clearly marked `TODO: confirm with structural
engineer`, so logic is testable immediately and only the constants change later.]

## 5. Logging / Audit Strategy

- Every check that flags, rejects, interpolates, or changes status writes one
  `validation_log` row with: `sensor_id`, decision-timestamp, `raw_value`,
  full `raw_payload`, and a **human-readable reason** string.
- Reason strings are generated by the check that fired, so the WHY is specific:
  - RANGE: `"value 812.0 g exceeds accelerometer phys_max 16.0 g"`
  - LIVENESS: `"no reading since 2026-06-20T10:02Z, 6m12s > offline_after 5m"`
  - SPIKE: `"value 4.1σ above baseline mean 1.2 (window=20); not confirmed by next 3 readings"`
  - GAP: `"3 consecutive missing readings 10:01–10:03; exceeds max_interp_gap 2 → NO_DATA"`
- `OK` pass-throughs do **not** spam the audit log per reading; the
  `validated_readings` table is the record of normal flow. The audit log is for
  exceptions and transformations (interpolation counts as a transformation and IS
  logged). [Confirm: Open Q-C — do you want EVERY reading logged, or only
  flags/transforms? Constitution VI requires every *decision* be logged; I read a
  clean OK as recorded by `validated_readings`, but will log all if you prefer.]
- Audit tables share the append-only `REVOKE UPDATE,DELETE` treatment.

## 6. Error-Handling Strategy

Principle IV: always return a status, never throw out of the agent.

- **Parsing boundary (`errors.safe_parse`)**: every payload passes through a
  defensive parser that validates presence and type of `sensor_id, sensor_type,
  value, unit, timestamp`. On any defect (missing field, wrong type, unparseable
  timestamp, non-numeric value) it returns a structured failure, never raises.
- **Malformed payload disposition**: a structurally-broken payload is still
  recorded raw (forensics), and produces a `CORRUPT` status with reason
  `"malformed payload: <what was wrong>"`. [Open Q-D: do you want malformed-shape
  treated as `CORRUPT`, or a distinct status? Your enum has no `MALFORMED`, so I
  default to `CORRUPT` + reason.]
- **Per-sensor isolation**: `run_cycle` wraps each sensor's processing in a guard
  so one sensor's unexpected failure degrades only that sensor (emits an
  error-status row + logs the traceback reason) and never aborts the cycle for the
  other sensors.
- **Cycle-level guard**: the scheduler entrypoint catches anything escaping
  `run_cycle`, logs it, and lets the next tick proceed — the process stays alive.
- No bare `except: pass`. Every caught error becomes a logged status with a reason.

## 7. Interface Contract (downstream dependency)

The Structural Analysis Agent depends ONLY on this contract (Principle III).
Two equivalent access modes — pick per Open Q-E:

**Primary (DB contract):** downstream reads `validated_readings` filtered to
`status='OK'` (optionally `is_interpolated` as a quality flag). This is the
loose-coupling default.

**Library contract (for in-process use & for tests):**

```python
@dataclass(frozen=True)
class ValidationResult:
    sensor_id: str
    sensor_type: str
    timestamp: datetime
    value: float | None          # None when not usable (OFFLINE/CORRUPT/NO_DATA)
    status: Literal["OK","OFFLINE","CORRUPT","SPIKE","NO_DATA"]
    is_interpolated: bool
    reason: str | None           # populated for non-OK / interpolated
    source_raw_ids: list[int]

class DataCollectionAgent:
    def __init__(self, store: Store, profiles: ProfileProvider, clock: Clock): ...
    def run_cycle(self, now: datetime) -> CycleSummary: ...
    # CycleSummary.results -> list[ValidationResult], one per expected sensor
```

Contract guarantees the downstream agent may rely on:
1. A result is returned for **every expected sensor**, every cycle (silence is
   never ambiguous — an absent sensor appears as `OFFLINE`, satisfying US-2).
2. `value` is non-null **only** when `status == OK`.
3. `clock` is injected (not `datetime.now()` inside), so cycles are deterministic
   and testable.

## 8. Testing Plan

Constitution Principle V mandates the four scenarios; the spec adds four more.
All eight as isolated unit tests against pure check functions + agent-level tests
with a fake store and injected clock.

| # | Scenario | Asserts | Constitution mapping |
|---|----------|---------|----------------------|
| T1 | Normal reading | in-range, live, non-outlier → `OK`, value passed through | normal |
| T2 | Missing sensor (no reading at all this cycle) | result still emitted, `OFFLINE` | missing |
| T3 | Corrupt / out-of-range | value beyond profile bounds → `CORRUPT`, value NULL, reason logged | corrupt |
| T4 | Sensor offline (last-seen > threshold) | `OFFLINE` within one cycle (AC-1) | offline |
| T5 | Single-point spike | >3σ, unconfirmed by next 2–3 → `SPIKE`, withheld (AC-3) | (extra) |
| T6 | Confirmed sustained shift | >3σ sustained across confirm window → `OK` real signal (AC-4) | (extra) |
| T7 | Short gap (1–2 missing) | linear interpolation, `OK` + `is_interpolated=TRUE` (AC-5) | (extra) |
| T8 | Long gap (3+ missing) | no interpolation, `NO_DATA` (AC-6) | (extra) |

Additional cross-cutting tests:
- **T9 Crash-safety / malformed payload**: missing field, wrong type, non-numeric
  value, bad timestamp → structured status, no exception escapes (AC-7, Principle IV).
- **T10 Raw immutability**: after a cycle, original raw rows are unchanged and a
  derived `validated_readings` row links back to them (Principle II).
- **T11 Audit completeness**: every flag/reject/interp produced a `validation_log`
  row with timestamp + causing input + reason (Principle VI).
- **T12 Per-sensor isolation**: one sensor raising internally does not abort the
  cycle for others (§6).

Test doubles: in-memory `FakeStore`, injected `FixedClock`, profile fixtures with
known bounds/windows — no real DB or MQTT needed for unit tests. An optional
integration test exercises real TimescaleDB append-only enforcement.

## Constitution Re-Check (post-design)

| Principle | Status |
|-----------|--------|
| I. Safety First | PASS — no physical action; reasons are human-readable WHY |
| II. Data Integrity | PASS — DB-enforced append-only raw; derived rows link to source; transforms logged |
| III. Modularity | PASS — pure-function checks; single store boundary; explicit §7 contract |
| IV. Reliability over Cleverness | PASS — fully deterministic, zero LLM; always-return-status |
| V. Testability | PASS — four mandatory + four spec scenarios + 4 cross-cutting |
| VI. Auditability | PASS — `validation_log` with timestamp + input + reason |
| VII. Tech Stack | PASS — Python, PostgreSQL/TimescaleDB, MQTT; no AI in this agent |

## Open Questions To Confirm Before Tasks

- **Q-A:** Represent interpolation as `status=OK` + `is_interpolated=TRUE` (my
  default), or do you want it surfaced differently? Your enum has no `INTERPOLATED`.
- **Q-B:** Physical min/max + window sizes per sensor type — provide now, or shall I
  scaffold `TODO`-marked placeholders so logic is buildable immediately?
- **Q-C:** Audit every reading, or only flags/transforms (OK flow recorded by
  `validated_readings`)? I default to the latter.
- **Q-D:** Malformed-shape payloads → `CORRUPT` + reason (my default), since the enum
  has no `MALFORMED`?
- **Q-E:** Downstream consumes via the **DB table** (default) or the **library
  contract**, or both?
- **Q-F (carried from spec):** Is calibration-**drift** detection in scope here? It
  is not in the 8 acceptance tests and would need its own rule; I currently treat it
  as OUT of scope (deferred to Structural Analysis), matching the spec's Out-of-Scope.
```
