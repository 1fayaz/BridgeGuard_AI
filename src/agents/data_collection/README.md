# Data Collection Agent

The Data Collection Agent is the first stage of the BridgeGuard pipeline: it turns a
stream of raw IoT sensor payloads into **trustworthy, traceable, validated readings**.
It is a **deterministic Python service** (no LLM in the decision path — Constitution IV)
that n8n triggers once per processing cycle.

> Its single job: decide, for every expected sensor, whether the device is alive, whether
> each value can be trusted, and whether the timing is sound — and to record *why*, so a
> human can audit every number. **Silence must never be mistaken for safety.**

---

## Inputs

One **cycle** = a batch of raw payloads (dicts), delivered by n8n off MQTT. A payload:

```jsonc
{
  "sensor_id":   "acc-01",                  // required, non-empty string
  "sensor_type": "accelerometer",           // required; must be a registered type
  "sensor_time": "2026-06-24T12:00:00Z",    // required; the SENSOR's own timestamp (G4)
  "value":       0.83,                      // numeric, or null for an explicit no-reading
  "ingest_time": "2026-06-24T12:00:02Z"     // optional; when WE received it (drift calc)
}
```

`sensor_time` (not arrival time) drives liveness, ordering, and gap detection. Malformed
payloads never crash the cycle — they become a `CORRUPT` verdict with a logged reason.

The set of sensors that *should* report is the **expected-sensor registry**
(`config/registry.py`), independent of any incoming batch. The agent iterates the
**registry**, so a sensor that sends nothing is still evaluated (→ `OFFLINE`), never an
absent row.

## Outputs — three independent axes

A reading carries up to three independent signals. They **co-exist**; none replaces another:

| Axis | Field | Values | Owned by |
|------|-------|--------|----------|
| **Device health** | `sensor_status.status` | `LIVE` \| `OFFLINE` | liveness only (single owner) |
| **Value / timeline** | `validated_readings.status` | `OK` \| `INTERPOLATED` \| `SPIKE` \| `CORRUPT` \| `NO_DATA` \| `PENDING` | range / spike / gap-fill |
| **Timing** | `validated_readings.clock_drift` | `true` \| `false` (a flag) | clock-drift check |

A reading can be `OK` **and** `clock_drift=true`; a sensor can be `OFFLINE` **and** carry
a `NO_DATA` reading row for the same cycle. `is_interpolated` mirrors
`status == INTERPOLATED` for convenient display.

Every validated row links to its **raw source id(s)** (`source_raw_ids`) — every number
traces back to immutable raw data (Constitution II/VI).

---

## Pipeline order (`process_cycle`, `agent.py`)

```
safe-parse            (parsing.py)      malformed payload -> CORRUPT + reason, never raises
   |
clock-drift annotate  (checks/clock_drift.py)   |sensor_time - ingest_time| > tol -> flag
   |
dedup first-wins      (dedup.py)        same sensor+ts: identical -> collapse;
+ sort by sensor ts                     conflicting -> first kept, both logged
   |
ITERATE the registry  (config/registry.py)   one verdict per EXPECTED sensor (incl silent)
   |
  per sensor:
    liveness          (checks/liveness.py)     owns OFFLINE; 3 missed -> OFFLINE
    resolve PENDING   (checks/pending.py)       advance an open spike candidate (cross-cycle)
    range             (checks/range_check.py)   out of bounds -> CORRUPT (precedence)
    spike / PENDING   (checks/spike.py)         > +/-3 sigma -> PENDING candidate
   |
emit per-sensor result (both axes + clock_drift flag)  ->  persist (store.py)
```

`CORRUPT` has **precedence**: an out-of-range value is never re-judged as a spike or
interpolated.

## The four checks + the cross-cutting rules

1. **Liveness (FR-1)** — counts consecutive missed reports against the per-type cadence
   using the sensor's own timestamp; `offline_after_n` (=3) missed → `OFFLINE`. The
   **sole writer** of device health. A never-seen registry sensor is `OFFLINE`.
2. **Range (FR-2)** — value outside `phys_min`/`phys_max` → `CORRUPT`, reason names the
   value + violated bound + unit. Unknown type / non-numeric / NaN → `CORRUPT`.
3. **Spike (FR-3)** — `> ±zscore_threshold` (=3) σ from an **OK-only** baseline
   (the most recent ≤100 readings within 24h — the *intersection*) → a `PENDING`
   candidate. Confirmed by the next `confirm_count` (=3) readings: sustained → `OK`
   (real signal), returns to baseline → `SPIKE` (transient, withheld).
4. **Gap-fill (FR-4)** — 1–2 consecutive missing slots → linear interpolation
   (`INTERPOLATED`); 3+ → `NO_DATA`. Sets **only** the reading-status, never device
   health (that stays liveness's job).

- **PENDING resolution (FR-5)** — a candidate resolves on the *first* of: confirmation
  window fills, sensor goes `OFFLINE`, or elapsed time strictly > 3× cadence. It is
  **never left unresolved**.
- **Late arrival** — a reading placed by its own timestamp within the 3× cadence
  lookback triggers a **bounded recompute**: a *new* validated row is appended, the prior
  row's `superseded_by` is stamped, and a `CORRECTION` (old→new) is logged. Outside the
  window → raw-only. **Raw is never overwritten.**
- **Clock drift (G4)** — `|sensor_time − ingest_time|` beyond the per-type tolerance sets
  the `clock_drift` flag + logs `CLOCK_DRIFT`; the reading is **still processed** using
  its sensor timestamp, its value-status unaffected.
- **Duplicate conflict** — same sensor+timestamp, different value: the **first-received**
  value wins, the later one is discarded and logged as `DUPLICATE_CONFLICT` with **both**
  values. No averaging.

Every reject / flag / interpolation / status-change / correction / drift / dup-conflict
is written to the append-only `decision_log` with a human-readable reason. A clean `OK`
reading is recorded by its validated row, not spammed to the log.

---

## Persistence (`store.py` + `db/migrations/`)

| Table | Migration | Guarantee |
|-------|-----------|-----------|
| `raw_readings` | `0001` | append-only (REVOKE + trigger); both timestamps stored |
| `validated_readings` | `0002` | six statuses + flags; correction by append + `superseded_by` |
| `sensor_status` | `0003` | one current row per sensor (`LIVE`/`OFFLINE`) |
| `decision_log` | `0004` | append-only audit; a reason on every row |

`FakeStore` mirrors these guarantees in memory for tests. **[DB-DEP]:** live Supabase
enforcement of the migrations is verified when an instance exists (none locally).

## Out of scope

This agent **only validates and records**. It does **not**:
- compute danger / risk scores or health bands (that is `math-analysis`, a later agent);
- do frequency-domain analysis (FFT) or Butterworth filtering (`data-refinement`);
- dispatch alerts, recommend closures, or take any real-world action
  (those are `needs_approval`-gated agents downstream — Constitution I).

## Tested contract

229 tests in `tests/data_collection/` cover every function and AC-1…AC-7 end-to-end.
See `T1202` (below, `ADD_SENSOR_TYPE.md`) to add a new sensor type **with config only**.
