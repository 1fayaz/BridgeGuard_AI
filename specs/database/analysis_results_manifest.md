# `analysis_results` — Column Manifest (D201)

**Status:** Ratification doc — **no SQL**. This maps every field of the Structural Analysis agent's
output contract to exactly one column, so D202 (migration `0005_analysis_results.sql`) is built
against a signed-off shape, not a guess. **Sign off before D202.**
**Date:** 2026-07-15
**Sources of truth:** `specs/structural-analysis-agent/spec.md` (output contract §383–391; the
per-FR detail §278–405; skip taxonomy FR-9/FR-12); `src/agents/structural_analysis/config/
calculations.py` (the `Calculation` enum this table's `calculation` column mirrors); the built
supersede tables `validated_readings` (0002) / `risk_assessments` (0006) whose discipline this table
copies; `specs/database/spec.md` FR-5/FR-7/FR-8/FR-10; `specs/database/plan.md` §1/§4/§5.

> **Why this table is a blocker (research §1):** `analysis_results` is referenced as "migration 0005"
> by the `0006`/`0008` headers and read by Risk (`source_analysis_ids`) and Report — but **no table
> exists** (`Glob db/migrations/*.sql` jumps 0004 → 0006). Until it exists the provenance chain
> `raw → validated → analysis → assessment → report/alert` is broken at the `analysis` hop. This
> manifest is the shape D202 will build to close that gap. **Note:** SA design docs call this
> migration "S203"; in this repo's numbering it is **0005** (plan §1, additive — fills the empty slot).

---

## 1. Grain (one row = what?)

**One row per `(sensor, calculation, block, input_version)` — exactly one structured result per
eligible pair per cycle** (SA FR-13 §383–385: "for every eligible (sensor, calculation, block) pair,
the agent emits exactly one structured result"). This grain drives the idempotency key (§4) and the
supersede discipline (§5).

---

## 2. Column manifest

Every column traces to a specific SA output-contract clause. Types are indicative for review (no DDL
here); D202 pins them.

### 2a. Identity & store-owned
| Column | Type (indicative) | Source clause | Notes |
|---|---|---|---|
| `id` | BIGINT identity PK | store-owned (mirrors 0002/0006) | the id Risk's `source_analysis_ids` / Report reference (soft, §5). |
| `computed_at` | TIMESTAMPTZ default now() | FR-17 audit clock | when this result was computed; distinct from the reading's `sensor_time`. |

### 2b. What was computed, on what
| Column | Type | Source clause | Notes |
|---|---|---|---|
| `sensor_id` | TEXT | input contract §92; FR-13 "the sensor" | the reporting sensor. Tenant FK wired in 0015 (not inline — sensors table is 0014). |
| `calculation` | enum `analysis_calc` | FR-13; `calculations.py` | closed set = the `Calculation` enum: `RMS \| FFT \| DEFLECTION_LIMIT \| THRESHOLD` (v1 active) + `FATIGUE \| MODAL \| CRACK_RATE` (declared-but-deferred; a v1 row emitting one fails — FR-10/11). The column's enum mirrors the Python enum so schema + code cannot drift. |
| `block_id` / block identity | TEXT or BIGINT | FR-13 "the block/reading identity" | which block/scalar reading this result is for. (Exact form — a reading id vs. a block key — pinned in D202; the grain needs a stable block identity.) |

### 2c. The outcome (closed vocabulary — FR-13)
| Column | Type | Source clause | Notes |
|---|---|---|---|
| `outcome` | enum `analysis_outcome` | FR-13 §385–386 | `RAN \| SKIPPED \| ERROR`. Closed set. Mirrors the (not-yet-existing) SA `statuses.py` — this migration defines the SQL enum the SA result code will mirror, the way 0002/0006/0010 did for their agents. |
| `reason_code` | enum `analysis_skip_reason`, NULL unless SKIPPED | FR-6/FR-9/FR-12 | closed skip taxonomy: `NO_CHANGE` (FFT within baseline, FR-6), `NO_CALC` (no calc mapped for the type, FR-12), `LIMIT_NOT_CONFIGURED` (type mapped but design limit unset, FR-9), `NO_REFERENCE` (displacement reference-zero missing/stale, FR-9), `DEGENERATE_RESULT` (non-finite/empty result validated out, FR-13 §397–401). |
| `error_detail` | TEXT, NULL unless ERROR | FR-13 §392–396 | the structured per-(sensor,calc,block) failure text; an ERROR row carries no value. |

### 2d. The result value(s) — RAN only
| Column | Type | Source clause | Notes |
|---|---|---|---|
| `value` | DOUBLE PRECISION, NULL unless a scalar RAN | FR-5/FR-9 | the scalar result: RMS severity, or the threshold/deflection **actual value**. NULL for FFT (which is peaks, not a scalar) and for SKIPPED/ERROR. |
| `limit_value` | DOUBLE PRECISION, NULL | FR-9 §343 | the configured design limit compared against (threshold/deflection). |
| `ratio` | DOUBLE PRECISION, NULL | FR-9 §343 | `value / limit`. |
| `passed` | BOOLEAN, NULL | FR-9 §343 | pass/fail-vs-limit. **No** "approaching"/danger band — that is the Risk agent's job (FR-9 §344, out of scope here). |
| `fft_peaks` | JSONB, NULL unless FFT RAN | FR-6 §299–300 | the **top-N dominant frequencies with amplitudes** + rate/resolution/window metadata (not the full spectrum). JSONB because it is a variable-length list (same rationale as `risk_assessments.contributing_factors`). |

### 2e. Provenance (FR-13 / FR-16 / FR-17) — the traceable chain + reproducibility
| Column | Type | Source clause | Notes |
|---|---|---|---|
| `source_validated_ids` | BIGINT[] NOT NULL default '{}' | FR-13 §388 "the validated readings that formed the input" | **SOFT** provenance (plan §5): the `validated_readings.id`(s) this result was computed from. Array (interpolation/windowing spans several), same shape as `validated_readings.source_raw_ids`. Not a hard FK (agent independence; arrays can't be FKs). This is the `analysis` hop of the provenance chain (spec FR-8). |
| `input_version` | TEXT (or INTEGER) NOT NULL | FR-16 §407–410 | the input version (derived from the DCA reading/supersession identity) recorded on the result; the idempotency key member (§4) and the supersede trigger (§5). |
| `config_version` | TEXT NOT NULL | FR-17 §417–422 | which SA config/constants were in force — so a result is reproducible even after a limit/threshold is retuned. |
| `constants_used` | JSONB | FR-13 §391; FR-17 | the actual constant values used (design limit, k, σ-floor, reference-zero, sample rate/block length as applicable) — captured so the number re-derives. Values themselves are **config TODO** until a stakeholder supplies them (research §4); the column holds whatever was in force. |

### 2f. Result flags (co-exist with any outcome — FR-2/FR-13/FR-14/FR-6)
| Column | Type | Source clause | Notes |
|---|---|---|---|
| `interpolated_input` | BOOLEAN NOT NULL default false | FR-13 §389; §256 | the input included an INTERPOLATED validated reading. Carried so downstream can see the result used filled data. |
| `clock_drift` | BOOLEAN NOT NULL default false | FR-14 §428; FR-13 §390 | the input carried a `clock_drift` flag (timing-trust propagation). |
| `rate_mismatch` | BOOLEAN NOT NULL default false | FR-2; FR-13 §390 | the block's sample rate/length disagreed with the configured/expected (the rate/length-mismatch flag). |
| `abnormal_quiet` | BOOLEAN NOT NULL default false | FR-6 §289–290 | the FFT was change-triggered by a **low-side** RMS deviation ("went unexpectedly quiet"), tagged distinctly from a high-side trigger. |

### 2g. Correction chain (FR-8 / spec-002 FR-7)
| Column | Type | Source clause | Notes |
|---|---|---|---|
| `superseded_by` | BIGINT REFERENCES analysis_results(id), NULL | FR-8 §323–334 | correct-by-append (self-FK, hard — internal consistency, plan §5). A late-arrival recompute appends a new row and stamps the old one's `superseded_by`; NULL = current, NOT NULL = historical. Never overwritten; DELETE blocked (D203). |

### 2h. Tenancy (added later, not inline)
`municipality_id` (denormalized) + the hard `sensor_id → sensors(id)` FK are **NOT** in 0005 — the
`sensors` table is created in 0014, after 0005. They are added to this table in **0015**
(`tenant_columns_and_fks`), uniformly with the other sensor-keyed tables (plan §1). Flagged here so
D202 does **not** add a tenant FK inline (it would reference a not-yet-existing table).

---

## 3. Shape-coherence rules (CHECKs D202 must encode)

Mirrors the coherent-shape CHECK discipline in `report_artifacts` (0008) / `risk_assessments` (0006):
- **RAN** ⇒ carries a result: a scalar RAN has a finite `value` (or an FFT RAN has `fft_peaks`); no
  `reason_code`, no `error_detail`.
- **SKIPPED** ⇒ carries exactly one `reason_code` from the closed taxonomy; no `value`/`fft_peaks`;
  no `error_detail`.
- **ERROR** ⇒ carries `error_detail`; no `value`, no `reason_code` (FR-13 §392–396).
- **Degenerate never flows as RAN** (FR-13 §397–401): a non-finite/empty computation is
  `SKIPPED/DEGENERATE_RESULT`, never a `RAN` NaN — so a NaN can never reach Risk as a real number.
- A threshold/deflection RAN that populates `ratio` should have `value` and `limit_value` present
  (ratio = value/limit).

---

## 4. Idempotency key (spec-002 FR-10; SA FR-16)

**Partial-unique index over current rows: `(sensor_id, calculation, block_id, input_version) WHERE
superseded_by IS NULL`** — at most one *current* result per eligible pair per input version. A
redelivered/duplicate trigger for the same input version is a no-op; a genuine input **correction**
(new `input_version`) supersedes (§5). Standard Postgres partial-unique B-tree — **no TimescaleDB**
(plan §1). Mirrors `uq_risk_current_bridge_cycle` (0006) / `uq_report_current_assessment_version`
(0008).

---

## 5. Discipline (D203 will implement)

Correct-by-supersede, identical to `validated_readings`/`risk_assessments`:
- **Guard-update trigger** blocks in-place edits to the substantive/provenance columns
  (`outcome`, `value`, `fft_peaks`, `reason_code`, `source_validated_ids`, `input_version`,
  `config_version`, `sensor_id`, `calculation`, `block_id`); permits stamping `superseded_by`.
- **Block-delete trigger** + `REVOKE DELETE, TRUNCATE` — history is permanent (Const. VI).
- Naming follows the repo convention: `analysis_results_guard_update` / `analysis_results_block_delete`.

---

## 6. Index summary (D202/D203; verified in D501/D503)

- **Idempotency:** the partial-unique in §4.
- **Risk/trend read:** a `(sensor_id, computed_at DESC)` read for "current results for a sensor over
  a window" (Risk reads current RAN results per scope; SA §102 per-sensor chronological). Standard
  B-tree; this is the `analysis_results` member of the `(sensor_id, <time>)` family (plan §4, §5.D501).
- **No** `(bridge_id, …)` index inline — `bridge_id`/`municipality_id` arrive in 0015; any
  bridge/cycle lookup index is decided there.

---

## 7. Open Items (do not guess — carried into D202)

- **`block_id` exact form** — a `validated_readings.id` vs. a synthesised block key. Needs the SA
  trigger's block-identity contract (SA Open Items §661–664). D202 picks the stable form.
- **`input_version` type** — TEXT vs INTEGER; how it is derived from the DCA reading/supersession
  identity (SA Open Item §661). Column present regardless; type pinned in D202.
- **`fft_peaks` JSON shape** — N, peak-prominence rule, amplitude/units, rate/resolution metadata
  keys (SA Open Item §643). JSONB holds it; the internal shape is SA's contract, not the DB's.
- **`constants_used` contents** — which constants are captured per calc; the *values* are config TODO
  (research §4). The column holds whatever was in force.
- These are **shape** open items, not blockers: the columns above are ratified; D202 pins the two
  types (`block_id`, `input_version`) and the two JSON shapes.
