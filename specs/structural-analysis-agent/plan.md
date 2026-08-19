# Structural Analysis Agent — Technical Plan

**Status:** Draft for review (built on the agreed `spec.md`, two clarification interviews)
**Date:** 2026-06-27
**Spec:** `specs/structural-analysis-agent/spec.md` (behaviour-only, 17 FR / 20 AC)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.0.0** (agree on stack)
**Research:** `specs/structural-analysis-agent/research-agent-002.md` (Option A/B framing);
prior art: `specs/data-collection-agent/plan.md` (the DCA's deterministic-service decision).

> Planning under the **CLAUDE.md / constitution v2.0.0 stack** (OpenAI Agents SDK *as
> layout convention*, MCP, Supabase/Postgres, n8n glue). This agent is **Agent 002**,
> downstream of the Data Collection Agent (DCA, Agent 001).
>
> **Settled in spec + interviews (baked in below):** block-valued accelerometer readings,
> one-FFT-per-block, per-block RMS as the change metric, two-sided RMS-vs-baseline trigger
> (+ `abnormal-quiet` tag), learned-baseline + fixed-ceiling, deflection = reading − ref-zero,
> generic scalar threshold check, closed outcome vocabulary `{RAN, SKIPPED, ERROR}` + reason
> codes, trigger-carries-IDs work intake, per-item failure isolation, idempotency by input
> version, config-version audit. Deferred: fatigue (FR-10), modal (FR-11), crack-rate.

---

## 1. Is the Structural Analysis Agent an Agent, or a deterministic service?

**Recommendation: Option A — a deterministic Python service, no model-calling Agent loop in
v1.** Identical posture to the DCA, reached independently from this agent's own facts.

Rationale (constitution Principle IV — rule-based over LLM where deterministic; research §1–2):
- **Calculation *selection* is rule-based** (spec FR-1, FR-6, FR-9): "run FFT when per-block
  RMS breaches the learned baseline ±k·σ or the fixed ceiling," "run the threshold check every
  eligible scalar reading." These are exact predicates over reading-status, RMS, and configured
  constants — the same shape that made the DCA fully deterministic. There is no open-ended
  judgment for a model to add.
- **The math is pure functions** (FFT, RMS, deflection-limit): NumPy/SciPy, exact and testable.
  Research recorded that LLMs are unreliable at precise numeric work — keeping math out of any
  model is a safety property, not a convenience.
- **The genuine judgment lives elsewhere.** "Does this spectrum/ratio indicate danger?" is the
  **Risk Reasoning Agent's** job (spec Out of Scope; DCA spec §142). This agent emits numbers,
  ratios, and pass/fail-vs-limit facts — never a verdict.

**Where (if anywhere) an SDK Agent could appear later.**
- **Option A (v1, recommended): no model-calling Agent.** "Agent" = *Digital FTE* (a unit of
  overseen autonomous work), not an LLM loop. Simplest thing that satisfies the spec; fully
  testable the way the DCA is.
- **Option B (later, out of v1): a minimal Agent for non-safety result *narration*** — e.g.
  plain-language framing of a result set for the PDF/exec-summary path. Even then the numbers
  are computed deterministically and handed to the model as read-only context; the model never
  computes or overrules a value. This belongs to the `pdf-report` / Risk path, not here.

**`needs_approval`:** **not** needed in this agent — it takes **no real-world physical action**
(that gate lives downstream on closure/alert/publish tools). The one human-in-the-loop touch is
the engineer **re-baseline** marker (FR-7), which changes *future* change-detection only and is
**logged**, not approval-gated. This also sidesteps the open Python-SDK HITL-maturity risk
(research, issue #2401).

**Tracing (constitution VII):** as with the DCA, the load-bearing obligation is the **audit
trail** (FR-13/FR-17), which is deterministic-code logging and is always-on. SDK tracing
instruments *model runs*; in Option A there is no model to trace, so the obligation is
satisfied by the audit trail. The instant any model-calling Agent (Option B) is introduced,
SDK tracing goes on from its first run — no exceptions.

---

## 2. Reading & writing the Supabase schema (shared with the DCA)

**Key finding:** the DCA's schema (`db/migrations/`) has tables for *raw*, *validated*,
*sensor_status*, and *decision_log* — but **no table for calculation results**. This agent
**reads the DCA's existing tables** and **writes one new table of its own**; it never mutates
the DCA's outputs.

### 2a. What this agent READS (DCA's existing schema, unchanged)

- **`validated_readings` (0002)** — the primary input. The agent consumes **current
  (non-superseded) rows** for the triggered `sensor_id`s, using:
  - `status` (the six `reading_status` values) → window-eligibility (FR-3): `PENDING`
    withheld, `CORRUPT`/`SPIKE` excluded, `INTERPOLATED` flagged & FFT-ineligible, `NO_DATA`
    = missing, `OK` usable.
  - `value` → the block waveform / scalar (see 2c on block storage), `sensor_time` → ordering
    (FR oldest→newest), `clock_drift` → carried through (FR-14), `source_raw_ids` → provenance
    chaining, `superseded_by`/`id` → **input version** for idempotency (FR-16) and the
    corrected-IDs path (FR-8).
- **`sensor_status` (0003)** — device `LIVE|OFFLINE`, read for context (OFFLINE → typically
  NO_DATA windows; recorded, not a trigger).
- **Sensor registry / profiles** — the **shared** config the DCA already uses (type, cadence),
  read to resolve each sensor's type. The **structural-analysis constants** this agent adds
  (calc-to-type map, design limits, ref-zeros, RMS k/ceiling/σ-floor/min-blocks, sample
  rate/block-length, baseline window) extend that config — **where they live is a build
  decision (Open Item), but they are config, not code** (spec Core Concepts).

### 2b. What this agent WRITES (one new table + audit, append-only)

A new migration set (proposed `0005…`), mirroring the DCA's **append-+-supersede, never
in-place** discipline (the exact pattern proven in `validated_readings`):

- **`analysis_results`** — one row per (sensor, calculation, block) emission. Columns (behaviour
  → schema, for review):
  - `sensor_id`, `sensor_type`, `sensor_time` (the block/reading's own time);
  - `calculation` (enum: `FFT | RMS | DEFLECTION_LIMIT | THRESHOLD` in v1; `FATIGUE`, `MODAL`,
    `CRACK_RATE` reserved-but-unused — FR-10/11);
  - `outcome` (enum **closed set**: `RAN | SKIPPED | ERROR`);
  - `reason_code` (enum: `NO_CALC | LIMIT_NOT_CONFIGURED | NO_REFERENCE | NO_CHANGE |
    INSUFFICIENT_BLOCK_COVERAGE | INSUFFICIENT_WINDOW | PENDING_WITHHELD | INELIGIBLE_STATUS |
    DEGENERATE_RESULT`; NULL when `RAN`) — the spec's Result Outcome Vocabulary, as a DB enum
    so new reasons are added deliberately (same approach as `reading_status`);
  - `result` (JSONB) — calc-specific payload: RMS scalar; FFT top-N peaks + rate/resolution
    metadata; threshold value/limit/ratio/pass-fail. JSONB because the four calcs have
    different result shapes but share one provenance/audit envelope;
  - flags: `interpolated_input`, `clock_drift`, `rate_mismatch`, `abnormal_quiet` (FR-2/6/14);
  - **provenance:** `source_validated_ids BIGINT[]` → the `validated_readings.id`(s) the result
    derived from (Constitution II/VI; analogous to `validated_readings.source_raw_ids`);
  - **idempotency/version:** `input_version` (derived from the DCA reading identity/supersession)
    + a uniqueness rule on `(sensor_id, calculation, sensor_time, input_version)` among current
    rows, so a redelivered trigger is a no-op (FR-16);
  - **audit/reproducibility:** `config_version`, `constants` (JSONB snapshot of the values used)
    → a result stays re-derivable after a limit is retuned (FR-17);
  - **correction chain:** `superseded_by` + the same BEFORE-UPDATE guard / DELETE-block triggers
    as `validated_readings`, so a late-arrival recompute **appends a new row and links the old**
    (FR-8), never an in-place edit.
- **Audit logging.** Two honest choices for review: **(i)** extend the DCA's `decision_log`
  `decision_kind` enum with analysis kinds (`ANALYSIS_RUN`, `ANALYSIS_SKIP`, `ANALYSIS_ERROR`,
  `RECOMPUTE`, `REBASELINE`), reusing one audit trail; or **(ii)** a separate `analysis_log`.
  **Recommend (i)** — one reconstructable audit story across both agents, consistent with "a
  human can reconstruct WHY from the log alone." The **re-baseline** action is logged here.

### 2c. The one schema question that needs a decision: where does the block waveform live?

The spec settled that an accelerometer reading is a **block** of samples, FFT runs **per block**,
and `validated_readings.value` is a single `DOUBLE PRECISION` — it **cannot hold a waveform
array**. Three options (Open Item, but the plan must flag it):
- **(A)** Block samples live in `raw_readings` (raw, append-only) and `validated_readings.value`
  carries a per-block scalar (e.g. the block's RMS or a reference); this agent reads the *raw*
  waveform for FFT by following `source_raw_ids`. Keeps the DCA schema untouched; couples FFT to
  raw provenance.
- **(B)** Add a waveform column/sidecar (e.g. `validated_blocks` with `samples` + rate/count
  metadata) the DCA populates for block sensors; this agent reads it directly.
- **(C)** Blocks stored out-of-row (object storage) with a pointer in the row.
  This intersects the DCA's own (unbuilt) block-handling, so it is a **cross-agent decision** —
  see Open Items. The agent's logic is buildable against any of the three; only the read path
  changes.

---

## 3. How it's triggered (n8n, downstream of the DCA — not the same cycle)

**Decision: downstream of the DCA, triggered *after* a DCA cycle commits its validated rows —
not co-scheduled, not in-process.** (Spec: "triggered after each DCA cycle; reads from store.")

```
Sensors → MQTT (Mosquitto) → n8n → DCA service → writes validated_readings/sensor_status/log
                                                        │  (cycle commits)
                                                        ▼
                              n8n: on DCA-cycle-complete, trigger Structural Analysis service
                                                        │  passes two ID lists:
                                                        │    • newly-validated reading IDs
                                                        │    • corrected/superseded reading IDs
                                                        ▼
        Structural Analysis service (deterministic):
          1. resolve each ID's sensor/type/config from the shared registry
          2. read current validated rows + history (baseline) from Supabase
          3. group per sensor, order oldest→newest by sensor_time (same-cycle siblings included)
          4. per (sensor, calc, block): eligibility (FR-3) → gates (FR-4) → RMS always →
             FFT if triggered (FR-6) → scalar threshold (FR-9); isolate failures per item
          5. write analysis_results (append/supersede) + audit log; idempotent by input_version
        → downstream (Risk Reasoning Agent) reads analysis_results
```

**Why downstream, not the same cycle:**
- **Correctness:** the agent reads *current, committed* validated rows (FR: non-superseded only).
  Running inside the DCA cycle would race the DCA's own writes (incl. PENDING→OK resolution).
- **Late-arrival fit (FR-8):** the DCA's correction/supersede happens *in* its cycle; firing the
  analysis trigger *after* lets the DCA hand over both the new **and** corrected ID lists in one
  signal — exactly the work-intake contract the spec assumes.
- **Decoupling / re-runnability:** a separate trigger is independently retryable; idempotency
  (FR-16) makes an at-least-once n8n redelivery safe (no duplicate results).

**Responsibility split (proposed, for review):**
- **n8n owns:** detecting DCA-cycle-complete, assembling the two ID lists (or relaying them from
  the DCA service's return), invoking the analysis service, retrying the *trigger*. Glue, not logic.
- **The Python analysis service owns:** all reads, all calculations, all `analysis_results` and
  audit writes, all idempotency/supersession. It never writes the DCA's tables.
- **Open contract question (Open Item):** does **n8n** derive the new/corrected ID lists, or does
  the **DCA service** return them for n8n to forward? Recommend the **DCA returns them** (it
  already knows precisely what it validated/superseded this cycle) and n8n forwards — keeps n8n
  dumb and the lists authoritative.

---

## Constitution Check

| Principle (CLAUDE.md / v2.0.0) | How this plan complies |
|---|---|
| Digital FTE / human signs off physical actions | Takes no physical action; no `needs_approval`. Re-baseline is logged, not gated. Danger verdict deferred to Risk Agent. |
| Raw immutable, every number traceable | Reads (never mutates) DCA raw/validated; `analysis_results` links `source_validated_ids` → validated → raw; append+supersede, DELETE blocked. |
| Prefer SDK primitives over custom | Deterministic service in SDK-convention layout; sessions/tracing reserved for any future model Agent (Option B). |
| Domain expertise in README | FFT/RMS/Miner/deflection/modal formulas + thresholds taken from `math-analysis`; baseline from `sensor-comparison`. |
| Trace from day one | Audit log (decision_log extension) always-on; SDK tracing on for any model Agent from first run. |
| Gate real-world actions w/ needs_approval | N/A here; explicitly downstream (closure/alert/publish). |

## Open Items To Resolve Before Build

1. **Agent presence (decision):** confirm **Option A** (deterministic service, no model loop)
   for v1 — recommended. Everything below assumes A.
2. **Block-waveform storage (§2c) — cross-agent:** which of (A) raw-via-`source_raw_ids`, (B) a
   validated-block sidecar, or (C) object-storage pointer holds the accelerometer samples FFT
   runs on. Blocks on the DCA's own (unbuilt) block ingestion; coordinate before building FFT.
2. **Trigger ID-list ownership (§3):** DCA-returns vs n8n-derives the new/corrected ID lists.
   Recommend DCA-returns.
3. **`analysis_results` schema sign-off:** the JSONB `result` shapes per calc, the `calculation`
   / `reason_code` enums, and the uniqueness/`input_version` rule for idempotency (FR-16).
4. **Audit home:** extend `decision_log` (recommended) vs separate `analysis_log`.
5. **`config_version` mechanics (FR-17):** how config is versioned/stamped so results stay
   reproducible after retuning; and where the structural-analysis constants live relative to the
   DCA profiles.
6. **All physical/safety constants stay `TODO`-marked config (do not guess):** per-block
   completeness floor, window min-blocks, RMS k/σ-floor/ceiling, baseline window, FFT top-N +
   peak rule, per-type design limits, span L (live vs dead), reference zeros, late-arrival
   recompute lookback bound, `clock_drift` policy for frequency calcs (run-but-flag vs skip).
7. **Deferred calcs confirmed out of v1:** fatigue (FR-10, needs cumulative state + S-N curve),
   modal (FR-11, needs geometry/k/m + bridge grouping), crack-rate — named, not built.
</content>
