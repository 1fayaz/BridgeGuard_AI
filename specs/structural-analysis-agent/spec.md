# Structural Analysis Agent — Specification

**Status:** Draft (scoping decisions A–D + two clarification interviews incorporated)
**Date:** 2026-06-27
**Anchors:** `CLAUDE.md` (constitution); `skills/bridgeguard-skills-README.md`
(`math-analysis`, `sensor-comparison`); `specs/data-collection-agent/spec.md`
(this agent's input contract + Out-of-Scope §142–144);
`specs/structural-analysis-agent/research-agent-002.md` (research, if saved).

> **Behaviour only.** This spec describes WHAT the agent does and WHY — no databases,
> frameworks, SDK classes, or file layout. Those are design decisions made later.

---

## Goal

This agent is the **calculation layer** of BridgeGuard. It consumes the Data Collection
Agent's (DCA) trustworthy output and decides **which engineering calculation, if any, to
run** on each sensor's recent data — then runs it and emits the numerical result with its
inputs and provenance. It exists so that expensive, safety-relevant math (vibration
frequency analysis, vibration severity, design-limit checking) runs **when and only when**
the data warrants it, and so that every number it produces is traceable back to the
validated readings it came from.

It does **not** judge whether a result is dangerous and it does **not** act on a result —
it computes and hands forward. It is the bridge between *"is this data trustworthy?"* (DCA)
and *"does this mean the bridge is at risk?"* (Risk Reasoning Agent).

---

## Core Concepts (settled in scoping + clarification interview)

- **Unit of analysis is the individual sensor (v1).** Every calculation in this version is
  keyed to a single sensor's data. Bridge-level calculations that require structure
  geometry and multi-sensor aggregation (modal / natural-frequency, span deflection across
  multiple points) are **named but deferred** — see FR-9/FR-10 and Out of Scope.

- **A "reading" can be a scalar OR a waveform block, by sensor class.** This is the
  foundational input fact:
  - **Block-valued sensors (accelerometer / vibration):** one validated reading is a
    **block** — a short array of high-rate samples (e.g. ~1 second of ~100 Hz data), not a
    single number. The DCA forwards pre-windowed blocks, each with **one** reading-status
    for the whole block.
  - **Scalar sensors (displacement/LVDT, strain gauge, load cell, crack, tiltmeter,
    temperature):** one validated reading is a single number, as in the DCA's original model.
  - The reading-status vocabulary (`OK | INTERPOLATED | SPIKE | CORRUPT | NO_DATA |
    PENDING`) applies to the **whole block** for block sensors and to the **value** for
    scalar sensors — one status per reading either way.

- **The agent is triggered after each DCA cycle and reads from the system of record.** The
  DCA persists its validated output; this agent runs when a DCA cycle completes, and pulls
  the validated readings + history + baseline data it needs from the store. It holds **no
  rolling state of its own** (see "State"). This decoupling is what makes late-arrival
  recompute (FR-8) and history queries possible by re-querying.

- **Calculations are pure functions of their input; per-block where the data is per-block.**
  FFT and RMS run **once per block** (not over a stitched multi-block series). The "rolling
  window" exists only for **change detection and baseline comparison**, never for
  assembling FFT input. Given the same block + same configured constants, a calculation
  always returns the same result. No wall-clock, no randomness, no model in the numeric path.

- **Multiple blocks per sensor per cycle are each processed independently.** The DCA may
  deliver several blocks for one sensor in a single cycle (it delivers one validated row
  per reading). The agent processes **every** block — each gets its own RMS, its own
  change-test, and its own FFT-if-triggered — and emits a result record per block. It never
  collapses a cycle's blocks to "the newest" (the exact bug fixed in the DCA).

- **"Run a calculation" is a deterministic rule, not a judgment call.** Whether a calc fires
  is decided by explicit trigger conditions over reading-status, value/RMS, and a baseline —
  never by a model. (Consistent with the DCA being fully deterministic; the genuine judgment
  lives in the downstream Risk Reasoning Agent.)

- **A skipped calculation is an explicit, emitted outcome — never silence.** For every
  (sensor, calculation) the agent *could* run, it emits either a **RAN** result (with value)
  or a **SKIPPED** result (with a reason: no change, insufficient data, no reference, no
  profile). Silence must never be mistaken for "all clear."

- **Calculation-to-sensor-type mapping, thresholds, rates, and limits are configuration,
  not code.** Which calc(s) apply to which sensor type; sample rate / block length; trigger
  margins; baseline window; design limits and reference zeros — all **configuration**.
  Adding a calc for a new type or tuning a threshold must not require changing the
  triggering or calculation logic. (Mirrors the DCA's "profiles are config, not code.")

---

## What this agent receives (input contract)

Per reading (block or scalar), per sensor, from the DCA via the store:

| Field | Meaning |
|---|---|
| `sensor_id` | which sensor |
| `sensor_type` | accelerometer, displacement/LVDT, strain, load cell, crack, tiltmeter, temperature |
| `sensor_status` | `LIVE` or `OFFLINE` (device health) |
| `reading_status` | `OK \| INTERPOLATED \| SPIKE \| CORRUPT \| NO_DATA \| PENDING` (whole-block or whole-value) |
| `value` | scalar value, **or** the waveform sample array for a block (may be null for NO_DATA) |
| `sensor_time` | the reading's own timestamp |
| `clock_drift` | timing-trust flag (co-exists with any status) |

For **block** readings the agent also needs the block's **sample rate** and **sample
count**. These come from **per-sensor-type config as the default, with optional per-block
metadata override** (FR-2). The agent also reads, from the store, the sensor's **recent
validated history** (to form a rolling window and detect change) and any **engineer
re-baseline marker** and **reference-zero** config.

The structural-analysis constants this agent needs (calc-to-type mappings, design limits,
RMS margins/ceilings, reference zeros, sample rate/block length, baseline window, k, σ-floor,
min-block counts) are **configuration**. This spec only declares *what* constants are
required (see FRs and Open Items); *where* they live relative to the DCA's existing sensor
profiles is a design decision deferred to `plan.md`. The agent resolves each reporting
sensor's type and constants from the **shared sensor registry/profiles** (the same registry
the DCA uses, not a separate one); it does **not** maintain its own expected-sensor list.

---

## Invocation & Work Intake

- **Triggered after each DCA cycle; the trigger defines the work.** When a DCA cycle
  completes, it fires a trigger to this agent carrying **two lists of reading/block IDs**:
  (a) the readings **newly validated** this cycle, and (b) the prior readings whose status
  the DCA **corrected/superseded** this cycle (late arrival, `PENDING→OK`, gap backfill).
  The agent processes exactly those — new IDs normally, corrected IDs via late-arrival
  recompute (FR-8). It does **not** scan the store for work or maintain a watermark/cursor;
  the trigger's ID lists are the unit of work.

- **No expected-sensor iteration.** Unlike the DCA, this agent does **not** iterate a
  registry of sensors that *should* report and emit a row for silent ones. Silence /
  OFFLINE / NO_DATA detection is the DCA's job and is already reflected in the validated
  readings the agent reads. A sensor that produced no validated reading this cycle simply
  yields no work here.

- **Per-sensor chronological ordering.** Within the handed-over IDs, the agent groups
  readings by sensor and processes each sensor's readings **oldest→newest by `sensor_time`**
  (re-sorting if delivered out of order, mirroring the DCA's sort-by-timestamp step). This
  ordering is required because a block's RMS-change is judged against a baseline of *prior*
  OK-blocks — **including earlier same-cycle blocks**, not only pre-cycle history. Processing
  out of order would compare a block against a baseline missing its true predecessors.

- **Only current (non-superseded) rows are processed.** The agent reads only current
  validated rows and **trusts the DCA's first-wins dedup**: there should be at most one
  logical reading per (sensor, `sensor_time`). If two non-superseded rows ever collide on
  (sensor, timestamp), that is a DCA-contract violation — the agent logs it and does not
  invent a tie-break (it does not silently pick one as real).

- **Idempotent re-trigger.** Triggers may fire more than once for the same cycle
  (at-least-once delivery, retry). Before emitting, the agent checks whether a **current
  (non-superseded) result already exists for that (sensor, calculation, block) at the same
  input version** (FR-16); if so, re-processing is a **no-op** — no duplicate record is
  created. A genuine input *correction* (different input version) supersedes (FR-8); an
  identical redelivery does not. This makes re-running a cycle safe.

---

## Result Outcome Vocabulary (closed set)

Every emission carries exactly one **outcome** and, when not `RAN`, exactly one
**reason code** from these closed sets (new reasons must be added deliberately, the same
way the DCA's reading-statuses are a fixed enum — a build using an unlisted outcome/reason,
or emitting no outcome for an eligible pair, fails):

**Outcomes:** `RAN` (a finite, sane result value) · `SKIPPED` (deliberately not computed) ·
`ERROR` (an unexpected failure was isolated — FR-13).

**SKIPPED reason codes:**
- `NO_CALC` — no calculation is mapped to this sensor type (FR-12).
- `LIMIT_NOT_CONFIGURED` — a calc *is* mapped but its required design-limit constant is
  absent (a half-configured profile) (FR-9). Distinct from `NO_CALC`.
- `NO_REFERENCE` — a displacement sensor's reference zero is missing or stale (FR-9).
- `NO_CHANGE` — RMS is within the (usable) learned baseline band, so FFT is not run (FR-6).
- `INSUFFICIENT_BLOCK_COVERAGE` — a block is below the per-block completeness floor (FR-4.1).
- `INSUFFICIENT_WINDOW` — too few usable blocks for a baseline comparison (FR-4.2).
- `PENDING_WITHHELD` — the reading is still `PENDING` and cannot be consumed (FR-3).
- `INELIGIBLE_STATUS` — the reading is `CORRUPT`/`SPIKE` (excluded) or `INTERPOLATED` for a
  frequency calc (FR-3).
- `DEGENERATE_RESULT` — the calculation produced a non-finite/empty result (NaN/Inf/empty
  spectrum); never emitted as a RAN value (FR-13).

---

## User Scenarios

- **Vibration spikes (RMS deviates) — FFT runs.** An accelerometer block's per-block RMS
  deviates from the sensor's learned RMS baseline beyond the configured margin (or exceeds
  the fixed engineer-set ceiling). The agent — which has already computed RMS for every
  block — additionally runs **FFT** on that block and emits its top-N dominant frequencies.

- **Nothing changed — FFT is skipped (explicitly); RMS still runs.** An accelerometer
  streams blocks whose RMS stays within the learned baseline band. RMS is emitted every
  block (it's cheap and it *is* the trigger signal), but **FFT is not run** — the agent
  emits a **SKIPPED** FFT result, reason "no change vs baseline."

- **A scalar reading crosses its design limit — threshold check runs regardless of change.**
  A displacement/strain/load/crack/tilt reading is compared to its configured design limit
  every cycle, independent of change vs baseline, because an absolute-threshold breach
  matters even with a flat trend. The agent emits the actual value, the limit, the ratio,
  and a pass/fail flag — but does **not** decide whether the breach is dangerous.

- **Too much of the window / block is missing — calculation skipped for insufficient data.**
  Either a single block arrived with too few of its declared samples (per-block completeness
  below floor), or the rolling window has too few usable blocks to form a baseline
  comparison. The agent skips the affected calculation and emits a **SKIPPED** result naming
  achieved-vs-required coverage — so the blind spot is visible rather than producing a
  misleadingly confident number.

- **A spike is still PENDING — the agent waits.** A block/reading is still `PENDING`
  (withheld by the DCA pending confirmation). The agent does **not** consume it into any
  calculation; it waits for the DCA to resolve it to `OK` or `SPIKE`, at which point
  late-arrival recompute (FR-8) covers it.

- **A previously-PENDING block resolves to OK after its cycle — results are recomputed.**
  The DCA later supersedes a block's status (or backfills a gap). The agent re-runs the
  affected calculations and emits **new result records that supersede the old**, so results
  stay consistent with corrected data.

- **A sensor type has no calculation defined — passed over, logged.** A reading arrives for
  a sensor type with no calculation configured. The agent emits a **SKIPPED/NO_CALC** result
  naming the type, so the coverage gap is explicit and a calc can be added later as config.

- **A fresh sensor with no baseline yet — FFT runs on every block.** A newly-installed
  sensor (or one returning from a long outage) lacks enough OK-block history to form a
  learned RMS baseline. Until the baseline is usable, the agent **runs FFT on every eligible
  block** (it cannot decide "changed," so it does not skip), reverting to change-gating once
  the baseline is ready.

---

## Functional Requirements

A build that ignores any of these should **visibly fail** a corresponding test.

- **FR-1 — Calculation selection is rule-based, per-block, per-cycle.** Each cycle, for each
  sensor, for each block/reading delivered, the agent evaluates the configured trigger
  condition(s) for every calculation mapped to that sensor's type and runs exactly those
  whose conditions are met. Selection is deterministic: identical input + identical config ⇒
  identical set of calculations run. Every block is processed (multiple blocks per sensor
  per cycle are each handled independently — Core Concepts). A build that runs calculations
  at random, runs them unconditionally when a trigger is defined, never runs a triggered
  calculation, or collapses a cycle's multiple blocks to one, fails.

- **FR-2 — Block sample-rate/length resolution, with mismatch handling.** For block sensors,
  the agent determines the block's sample rate and sample count from **per-type config as
  the default**, allowing a **per-block metadata override**. If a block's self-declared rate
  or length **disagrees** with config, the agent **uses the block's own declared rate** (the
  device knows itself best) and **flags the result** "rate/length differs from config" so a
  downstream consumer knows the spectrum's Hz axis came from an unverified rate. A build that
  computes FFT frequencies without a known rate, or that silently ignores a config/block
  mismatch, fails.

- **FR-3 — Window eligibility by reading-status (whole-reading).** Before any calculation,
  the agent assembles inputs from validated readings and applies these rules, with **no
  exceptions** — status applies to the **whole block/value**:
  - `PENDING` readings are **never consumed** and do not count as usable.
  - `CORRUPT` and `SPIKE` readings are **excluded** (rejected / noise).
  - `NO_DATA` periods count as **missing**, not as values/zeros.
  - `INTERPOLATED` readings are **usable for amplitude/severity/trend/threshold calculations
    (RMS, scalar threshold checks)** but are **flagged as containing interpolated input**,
    and are **ineligible for frequency-domain calculations (FFT/modal)** because
    interpolation injects artificial frequency content. The emitted result must record
    whether interpolated input was used.
  - `OK` readings are fully usable.
  A build that feeds a PENDING, CORRUPT, or SPIKE reading into a calculation, or runs FFT on
  an INTERPOLATED block without flagging/excluding it, fails.

- **FR-4 — Two-level data-quality gate.** Coverage is gated at two distinct levels, and each
  calculation names which gate(s) it uses:
  1. **Per-block completeness gate (FFT, RMS):** a block must contain at least a configured
     fraction/count of its declared samples to be computed on. A block below that floor is
     skipped (SKIPPED, reason naming achieved-vs-required intra-block coverage).
  2. **Window-coverage gate (change detection, baseline comparison):** there must be at
     least a configured number of usable blocks in the rolling window to compute a baseline
     and decide "changed." Below that floor, the change-trigger is treated as
     not-yet-available (see FR-6 cold-start), not as "no change."
  A build that computes on an under-complete block, decides "no change" on an
  under-populated window, or skips silently without a reason, fails. *(Numeric floors are
  per-calculation config — Open Items.)*

- **FR-5 — RMS runs on every eligible block (it is also the change metric).** For block
  sensors, the agent computes per-block RMS (`RMS = √(1/N · Σ xᵢ²)`, N = the block's usable
  samples) on **every** block that passes the per-block completeness gate (FR-4.1). RMS is
  both an emitted severity result and the scalar used for change detection (FR-6). A build
  that gates RMS behind a change trigger, or computes RMS over multiple blocks instead of
  per-block, fails.

- **FR-6 — FFT is change-triggered by RMS vs baseline (two-sided, with cold-start
  fallback).** For block sensors, FFT runs on a block when **either**:
  - the block's RMS **deviates from the learned RMS baseline beyond ±k·σ in *either*
    direction** — an abnormally **high** RMS (got louder) **or** an abnormally **low** RMS
    (went unexpectedly quiet, which can signal a stuck/failed sensor, a detached mount, or a
    load-path change). A **low-side** trigger is **tagged distinctly** (`abnormal-quiet`) on
    the result so downstream can tell "got louder" from "went quiet"; **or**
  - the block's RMS exceeds the **fixed engineer-set ceiling** (an absolute, high-side
    trigger, independent of the learned baseline).
  When the learned baseline is **not yet usable** (FR-7 readiness), the agent **runs FFT on
  every eligible block** until the baseline is ready (fail-safe: compute when it cannot decide
  "changed"). When the baseline is usable and neither trigger fires, FFT is emitted
  **SKIPPED/`NO_CHANGE`**. A build that runs FFT on an unchanged-within-baseline block once
  the baseline is ready, fails to run it on a baseline/ceiling breach (either direction),
  omits the `abnormal-quiet` tag on a low-side trigger, or suppresses FFT during cold-start,
  fails. An FFT result emits the **top-N dominant frequencies with amplitudes**, plus
  rate/resolution/window metadata (not the full spectrum). *(N, peak-prominence rule, k,
  ceiling, baseline window — Open Items.)*

- **FR-7 — Learned RMS baseline definition + readiness (recomputed from history, events
  excluded).** The learned baseline is **not** agent-held state; each cycle it is
  **recomputed by querying the store** for the sensor's recent **OK-status blocks** that fall
  **after the most recent engineer re-baseline marker**, and within that set **excluding
  blocks the agent previously flagged as events** (read from their own stored result
  records). The baseline is the mean and standard deviation of those blocks' RMS; "changed" =
  a new RMS beyond ±k·σ (FR-6).
  - **Readiness gate:** the baseline is **usable** only when **both** (a) the count of
    qualifying OK-blocks ≥ a configured **minimum** (FR-4.2), **and** (b) the computed **σ is
    above a configured σ-floor**. The σ-floor prevents a freak run of near-identical RMS
    values from producing σ≈0, which would otherwise make *every* later block read as a
    deviation and over-trigger FFT. While either condition is unmet, the baseline is "not yet
    usable" → cold-start fail-safe (FR-6).
  This prevents a sustained elevated vibration from silently "becoming the new normal" and
  hiding itself (the DCA's finding-#4 hazard), while letting a human deliberately re-baseline
  after a genuine sustained change (e.g. post-retrofit). A build whose baseline absorbs its
  own flagged events, ignores the re-baseline marker, or treats a σ≈0 baseline as usable,
  fails. *(Baseline window size, k, σ-floor, min-block count, re-baseline marker mechanics —
  Open Items.)*

- **FR-8 — Late-arrival recompute + supersede (bounded to the corrected reading's own
  result).** When the DCA supersedes a previously-processed reading's status (e.g.
  `PENDING → OK`) or backfills a gap — signalled via the trigger's **corrected-IDs** list
  (Invocation & Work Intake) — the agent **re-runs the calculation(s) for that corrected
  reading itself** and emits **new result records that supersede the prior ones**,
  append-only, with the old→new supersession linked. Prior records are never overwritten or
  deleted. **Scope of recompute is deliberately bounded to the corrected reading's *own*
  result**: the agent does **not** retroactively re-judge *other* blocks whose baseline
  happened to include the corrected reading. **Accepted tradeoff:** a corrected
  baseline-member can leave neighbouring change-decisions slightly stale; this is a chosen
  bound (keeps recompute fan-out finite), documented rather than silent. A build that leaves
  the corrected reading's *own* result stale, or that mutates an old record in place, fails.
  *(Recompute window bound — Open Items; mirror the DCA's bounded late-arrival policy.)*

- **FR-9 — Scalar design-limit check (every eligible scalar reading).** For every scalar
  sensor mapped to the threshold check (displacement/LVDT, strain, load cell, crack,
  tiltmeter), the agent runs a **threshold check every cycle the sensor has an eligible
  reading — independent of change vs baseline**, because an absolute-limit breach is
  meaningful even with a flat trend. For **displacement/LVDT**, the deflection value is
  derived as `δ_actual = reading − configured reference zero`, then compared to the
  configured limit (`δ ≤ L/800` live load). The result emits the **actual value, the
  configured limit, the ratio (value/limit), and a pass/fail flag** — and **no**
  "approaching"/warning band and **no** danger classification (those are the Risk Reasoning
  Agent's). Two distinct missing-config skips (closed-vocabulary, FR-12 taxonomy):
  - If the sensor's type is **mapped to the check but its design-limit constant is not yet
    configured** (a half-finished profile — likely, since limits are Open Items), the check
    is **SKIPPED/`LIMIT_NOT_CONFIGURED`** naming the type. This is **distinct** from
    `NO_CALC` (no calc mapped at all) — it surfaces a profile that needs finishing, and never
    compares against a guessed limit.
  - If a displacement sensor's **reference zero is missing or stale**, the check is
    **SKIPPED/`NO_REFERENCE`** — δ is never computed from a raw displacement that still
    includes install offset.
  **Crack sensors — absolute width only in v1.** The check compares absolute crack width to
  its limit. Crack-growth **rate** (trend/regression over time) — which matters even for a
  widening-but-under-limit crack — is **explicitly deferred** (like fatigue/modal). v1
  **knowingly does not flag** a slowly-widening crack that remains under its absolute limit;
  this limitation is documented, not silent. A build that runs FR-9 only on a detected
  change, computes δ without a reference, emits a danger/closeness judgement, or fabricates a
  crack-rate result in v1, fails. *(Per-sensor reference zeros, span length L, dead-vs-live
  limit selection, per-type design limits, and the deferred crack-rate calc — Open Items.)*

- **FR-10 — Cumulative fatigue (Miner's Rule) — DEFERRED, stubbed.** Fatigue damage
  accumulation (`D = Σ nᵢ/Nᵢ`, failure at D ≥ 1.0) is **named but not specified in v1**
  because it requires (a) persistent, append-only cumulative state across cycles and (b) an
  S-N curve (Nᵢ) that is a structural-engineering input not yet defined. v1 **must not** emit
  a fatigue number. A v1 build that fabricates a cumulative damage value, or silently drops
  the requirement, fails. *(Scope + S-N curve + cumulative-state model — Open Items.)*

- **FR-11 — Modal / natural-frequency analysis — DEFERRED, stubbed.** Natural-frequency
  identification (`f = (1/2π)√(k/m)`, compared to measured FFT peaks) is **named but not
  specified in v1** because it requires bridge geometry / stiffness (k) and mass (m), which
  are multi-sensor, bridge-level inputs out of v1's per-sensor scope. v1 **must not** emit a
  modal result. A v1 build that produces a natural-frequency number without these inputs
  fails. *(Geometry/k/m + bridge-level aggregation — Open Items.)*

- **FR-12 — Unknown / unmapped calculation target is explicit, never guessed.** A sensor
  whose type has **no calculation configured** is emitted as **SKIPPED/NO_CALC** naming the
  type — never run through a default or guessed calculation. A build that applies a
  calculation to a sensor type it isn't configured for fails.

- **FR-13 — Exhaustive, structured, provenance-linked emission; per-item failure isolation;
  never crashes.** Each cycle, for **every** eligible (sensor, calculation, block) pair, the
  agent emits **exactly one** structured result with an outcome from the closed vocabulary:
  **RAN** (a finite, sane value), **SKIPPED** (with a closed reason code), or **ERROR**.
  Every result records: the calculation type, the sensor, the block/reading identity, the
  result value(s) or skip/error reason, the identifiers of the **validated readings that
  formed the input**, the **input version** (FR-16), whether **interpolated input** was used,
  whether the input carried a **`clock_drift`** flag (FR-14), the **rate/length-mismatch**
  flag if any (FR-2), and the **configured constants + config version used** (FR-17).
  - **Failure isolation is per-(sensor, calculation, block).** Each calculation on each block
    is independently guarded; an unexpected failure (e.g. a thrown exception) becomes a
    structured **`ERROR`** result for **that one pair** and the agent **continues** every
    other sensor/calc/block — one bad input never blinds the cycle (mirrors the DCA's
    per-sensor isolation).
  - **Degenerate-but-non-throwing results never flow as values.** A calculation that returns
    a non-finite or empty result (NaN/Inf RMS, empty/meaningless spectrum from an all-zero or
    single-sample block) is validated for finiteness/sanity and emitted as
    **SKIPPED/`DEGENERATE_RESULT`** (with detail) — **not** as a RAN value. A NaN must never
    reach downstream risk scoring as a real number.
  A result that cannot be traced to its input readings, a missing record for an eligible
  pair, a degenerate value emitted as RAN, or a crash that abandons other work, fails the
  build. *(CLAUDE.md: every number traceable to source; no unhandled crashes; nothing
  silently dropped.)*

- **FR-16 — Idempotent processing keyed by input version.** Each validated reading the agent
  consumes has an **input version** (e.g. derived from the DCA's reading/supersession
  identity) recorded on any result computed from it. Before emitting, the agent treats a
  (sensor, calculation, block, input-version) it has **already produced a current result
  for** as a **no-op** — no duplicate record. A redelivered/duplicate trigger therefore
  produces no double records, while a genuine input **correction** (a *new* input version)
  legitimately supersedes (FR-8). A build that creates duplicate current results for an
  identical re-trigger, or that fails to supersede when the input version genuinely changed,
  fails.

- **FR-17 — Reproducible audit trail (run + result + config version).** Per CLAUDE.md every
  run is traceable. **Each agent run** records which trigger/cycle invoked it, the reading-ID
  lists it received, and the **config version** in force. **Each emitted result** links to
  its exact input reading IDs, the calculation identity, and the **config version + constant
  values** it used — so any number can be **re-derived later even after a threshold/limit is
  retuned** (a result computed under an old limit remains distinguishable and reproducible).
  This agent takes **no physical-world action**, so the constitution's `needs_approval` gate
  does **not** apply here (that gate lives downstream at closure/alert/publish); but the
  engineer **re-baseline** action (FR-7) and every result must still be logged. A build whose
  result cannot be reproduced because the config it ran under wasn't captured fails.

- **FR-14 — Timing-trust propagation.** Any result whose input included a `clock_drift`-
  flagged reading **carries that drift flag through** to the result (frequency results are
  especially timing-sensitive). v1 policy is **run-but-flag**, not skip. The agent never
  silently treats a drifted reading as clean. A build that drops the drift flag from a
  derived result fails. *(Whether frequency calcs should instead downgrade to SKIPPED on
  drift — Open Item.)*

- **FR-15 — Concurrent temperature recorded, not compensated (v1).** v1 does **not**
  thermally compensate deflection/strain results (that needs material coefficients + a
  co-located temperature sensor — unknowns). Where a co-located temperature reading exists,
  the agent **records the concurrent temperature alongside** the scalar result so engineers/
  downstream can interpret a thermally-influenced value. A build that thermally *corrects* a
  value in v1, or that discards an available concurrent temperature, fails. *(Material
  coefficients + co-located temp mapping — Open Items.)*

---

## Edge Cases & Rules

- **Input window mostly NO_DATA, or an internally-incomplete block.** Handled by the two-
  level gate (FR-4): an under-complete block skips FFT/RMS; an under-populated window makes
  the change-trigger "not yet available" (→ cold-start fail-safe FFT, FR-6), never a false
  "no change." Every skip is an emitted SKIPPED with a coverage reason. NO_DATA is missing
  samples, never zeros.

- **Conflicting signals from different sensors on the same bridge.** In v1 (per-sensor
  scope) the agent does **not** reconcile or arbitrate between sensors — it computes each
  sensor's result independently and emits all of them, including when two sensors on the same
  structure disagree. It must not suppress one sensor's result because another disagrees.
  Cross-sensor reconciliation belongs to bridge-level aggregation / the Risk Reasoning Agent.

- **A sensor type with no calculation defined for it yet.** Handled by FR-12 — emitted as
  SKIPPED/NO_CALC with the type named, so coverage gaps are visible.

- **Interpolated samples in a frequency calculation.** INTERPOLATED readings are ineligible
  for FFT/modal (FR-3). If excluding them drops the window below a needed floor, the affected
  calc is skipped (FR-4) rather than run on interpolated data.

- **A still-PENDING reading.** Excluded (FR-3); the agent waits for DCA resolution, then
  late-arrival recompute (FR-8) covers it once resolved.

- **`clock_drift` on input readings.** Carried through to any result whose input included it
  (FR-14); run-but-flag in v1.

- **Fresh sensor / post-outage cold start.** No usable learned baseline ⇒ FFT runs on every
  eligible block until the baseline is ready (FR-6). The scalar threshold check (FR-9) does
  not depend on a baseline and runs immediately.

- **Block sample-rate disagreement.** Trust the block's declared rate, flag the result
  (FR-2); the spectrum is still produced but marked as resting on an unverified Hz axis.

- **OFFLINE sensor.** Its recent readings are typically NO_DATA; calculations skip via the
  coverage gate. OFFLINE alone does not trigger a calculation but is recorded on the cycle's
  output so the blind spot is visible.

- **Engineer re-baseline is a human action.** Setting a re-baseline marker (FR-7) is the
  agent's one human-in-the-loop touchpoint. It changes future change-detection but is **not**
  a physical-world action, so it does not require the constitution's `needs_approval`
  closure-style gate — but it **must** be logged (who/when/why) like any other state change.

- **Abnormally quiet sensor.** A low-side RMS deviation (much quieter than baseline) **does**
  trigger FFT (FR-6), tagged `abnormal-quiet`, because going silent can mean a stuck/failed
  sensor, a detached mount, or a load-path change — not "less vibration, nothing to see."

- **Duplicate (sensor, timestamp) among current rows.** Should not occur — the agent trusts
  the DCA's first-wins dedup and only processes non-superseded rows. If it does occur, it is
  a DCA-contract violation: logged, **not** silently tie-broken (the agent does not guess
  which row is real).

- **Half-configured profile (mapped calc, missing limit).** Emitted as
  SKIPPED/`LIMIT_NOT_CONFIGURED` (FR-9), distinct from `NO_CALC` — surfaces a profile that
  needs an engineer to finish it, rather than hiding it or comparing against a guessed limit.

- **Redelivered / double-fired trigger.** Idempotent (FR-16): a re-trigger over the same
  input versions produces no duplicate results; only a genuine correction (new input version)
  supersedes.

- **Degenerate calculation result (NaN/Inf/empty spectrum).** Emitted as
  SKIPPED/`DEGENERATE_RESULT` (FR-13), never as a RAN value — a NaN must not reach risk
  scoring as a number.

- **A corrected baseline-member leaves neighbours slightly stale.** Accepted, documented
  bound (FR-8): recompute covers the corrected reading's *own* result, not every later block
  whose baseline included it. Chosen to keep recompute fan-out finite.

---

## Out of Scope

- **Deciding whether a result indicates danger** — risk scoring, severity classification,
  "approaching the limit" interpretation, closure recommendation: **Risk Reasoning Agent's**
  job. This agent emits numbers, ratios, and pass/fail-vs-limit facts, never a danger verdict.
- **Sending alerts or notifications** of any kind — **Alert Agent's** job.
- **Bridge-level / multi-sensor aggregation** — modal analysis, cross-sensor reconciliation,
  multi-point span deflection, load distribution across the deck, asymmetric-loading
  comparison between spans. (Deferred; some lives in a later version of this agent, some in
  the Risk Reasoning Agent.)
- **Cumulative fatigue and modal/natural-frequency results in v1** — named but deferred
  (FR-10, FR-11).
- **Thermal compensation of values** — v1 records concurrent temperature but does not correct
  (FR-15).
- **Validating or cleaning data** — that already happened in the DCA. This agent trusts the
  reading-status it is given and never re-judges a value's trustworthiness.
- **Generating charts or PDF reports** — `visual-output` / `pdf-report` skills, downstream.

This agent only **computes** engineering quantities from trustworthy data, never what they
*mean* or what to *do* about them.

---

## Acceptance Criteria

Each is testable against a scenario above.

- **AC-1.** Given an accelerometer block whose per-block RMS deviates from the learned
  baseline beyond margin (or exceeds the fixed ceiling) and which passes the per-block
  completeness gate, the agent **runs FFT** and emits its top-N dominant frequencies with
  rate/resolution metadata and input-reading provenance. *(vibration spikes)*
- **AC-2.** Given accelerometer blocks whose RMS stays within the learned baseline band, the
  agent **emits RMS every block** but emits a **SKIPPED** FFT result with reason "no change
  vs baseline." *(nothing changed)*
- **AC-3.** Given a block below the per-block completeness floor, **or** a window below the
  usable-block floor, the affected calculation is **skipped** with a coverage reason and **no
  computed number** is emitted; an under-populated window yields cold-start fail-safe FFT, not
  a false "no change." *(insufficient data, two-level gate)*
- **AC-4.** A `PENDING`, `CORRUPT`, or `SPIKE` reading is **never** included in any
  calculation; an `INTERPOLATED` reading is excluded from FFT but, if used in RMS/threshold,
  the result is **flagged as using interpolated input**. *(window eligibility)*
- **AC-5.** A fresh sensor with no usable learned baseline gets **FFT run on every eligible
  block** until the baseline is ready, then reverts to change-gating. *(cold start)*
- **AC-6.** The learned RMS baseline, recomputed from stored OK-blocks after the latest
  re-baseline marker, **excludes blocks the agent previously flagged as events** — a
  sustained elevated RMS does not silently enter the baseline. *(baseline poisoning guard)*
- **AC-7.** A scalar sensor with a configured design limit has its **threshold check run
  every eligible cycle regardless of change**, emitting value, limit, ratio, and pass/fail —
  with no warning band and no danger classification. For displacement, δ is computed as
  `reading − reference zero`; a **missing/stale reference** yields **SKIPPED/`NO_REFERENCE`**;
  a **mapped-but-unconfigured limit** yields **SKIPPED/`LIMIT_NOT_CONFIGURED`** (distinct
  from `NO_CALC`); a crack sensor is checked on **absolute width only** (no rate in v1).
  *(design-limit check)*
- **AC-8.** A block whose declared sample rate/length disagrees with config has its FFT run
  on the **block's own rate** and the result **flagged** "rate differs from config." *(rate
  mismatch)*
- **AC-9.** When the DCA supersedes an input reading's status (e.g. `PENDING → OK`) or
  backfills a gap, affected results are **recomputed and emitted as new records that
  supersede the old**, append-only, old→new linked — prior records unchanged. *(late-arrival
  recompute)*
- **AC-10.** A sensor whose type has **no configured calculation** produces a
  **SKIPPED/NO_CALC** result naming the type — never a default/guessed calculation. *(no calc
  defined)*
- **AC-11.** Multiple blocks delivered for one sensor in a single cycle are **each processed
  independently**, each producing its own result record(s) — none dropped. *(multi-block
  cycle)*
- **AC-12.** Every emitted result carries one **closed-vocabulary outcome** (`RAN` /
  `SKIPPED`+reason-code / `ERROR`), is **structured, links back to the validated readings
  that formed its input, and records the constants used and the interpolated/drift/
  rate-mismatch flags**; **exactly one** record exists per eligible (sensor, calc, block)
  pair. *(exhaustive + traceable + closed vocabulary)*
- **AC-13.** In v1, the agent emits **no cumulative-fatigue value and no modal/natural-
  frequency value**; a build that produces either from incomplete inputs fails. *(deferred
  calcs)*
- **AC-14.** Two sensors on the same bridge that disagree both have their **independent
  results emitted** — neither suppressed in favour of the other. *(conflicting signals)*
- **AC-15.** A result whose input included a `clock_drift`-flagged reading **carries that
  drift flag through**; where a co-located temperature reading exists, a scalar result
  **records the concurrent temperature** (without correcting the value). *(timing + thermal
  provenance)*
- **AC-16.** When one calculation on one block fails unexpectedly, the agent emits an
  **`ERROR`** result for **that pair only** and **still produces results for every other
  sensor/calc/block** in the cycle. A degenerate (NaN/Inf/empty) result is emitted as
  **SKIPPED/`DEGENERATE_RESULT`**, never as a RAN value. *(per-item isolation + degenerate)*
- **AC-17.** A trigger redelivered for the same cycle (same input versions) produces **no
  duplicate result records** (idempotent); a genuine input correction (new input version)
  **supersedes** the prior result. *(idempotency)*
- **AC-18.** A sensor's blocks delivered out of order within a cycle are processed
  **oldest→newest by `sensor_time`**, so each block's RMS-change is judged against a baseline
  that includes its earlier **same-cycle** OK-blocks. *(ordering)*
- **AC-19.** An accelerometer block whose RMS falls **far below** baseline (abnormally quiet)
  **triggers FFT**, and the result is **tagged `abnormal-quiet`** to distinguish it from a
  high-side trigger. *(two-sided change)*
- **AC-20.** Each run records its trigger/cycle, received reading-IDs, and **config version**;
  each result records the **config version + constants** used, so a number computed under an
  old limit can be **reproduced after the limit is retuned**. *(reproducible audit)*

---

## State

The agent is **stateless / triggered-per-batch** at the cycle level: it keeps no threaded
rolling object between cycles, and its work is defined entirely by the trigger's reading-ID
lists (Invocation & Work Intake), not a watermark/cursor it maintains. Every derived input it
needs — the rolling window, the learned RMS baseline (FR-7), prior event flags, re-baseline
markers, reference zeros — is **read from the system of record** each run (the baseline is a
*query*, not a kept object). The two genuinely persistent things it relies on are **(a)** the
store's append-only validated history (owned upstream) and **(b)** its own append-only result
records, which it re-reads for **event exclusion** (FR-7), **idempotency** (FR-16, "have I
already produced a current result for this input version?"), and **supersession** on
recompute (FR-8). This self-referential read of its own prior results is what keeps it
stateless without losing memory of what it has done. The one deferred calc that is
*inherently* stateful — cumulative fatigue (FR-10) — is out of v1 precisely because it needs
persistent accumulation that this stateless model doesn't yet provide.

---

## Open Items (to resolve before design, not part of "done")

- **Block sample rate + length per sensor type**, and the per-block override metadata format
  (FR-2).
- **Per-block completeness floor** and **window usable-block floor** per calculation (FR-4) —
  structural-engineering calls; sentinels until confirmed. **Do not guess for safety-critical
  math.**
- **RMS-change margin (k·σ), the learned-baseline window size, and the fixed engineer-set RMS
  ceiling** per sensor type (FR-6, FR-7).
- **Engineer re-baseline marker mechanics** — how a human sets it, how it's logged (FR-7,
  Edge Cases).
- **FFT output detail** — N (number of peaks), the peak-prominence/picking rule, and the
  rate/resolution metadata fields (FR-6).
- **Per-sensor reference zeros, span length L, dead-vs-live limit selection, and per-type
  design limits** for the scalar threshold check (FR-9).
- **S-N curve (Nᵢ) and cumulative-state model** for fatigue (FR-10).
- **Bridge geometry / stiffness k / mass m and bridge→sensors grouping** for modal analysis
  and future bridge-level calcs (FR-11).
- **Late-arrival recompute window bound** — how far back a correction can retrigger
  calculations (FR-8); mirror the DCA's bounded policy.
- **`clock_drift` policy for frequency calcs** — confirm run-but-flag (FR-14) vs downgrade-to-
  SKIPPED.
- **Material thermal coefficients + co-located temperature-sensor mapping** for any future
  thermal compensation (FR-15).
- **Confirmed-change signal availability** — confirm whether the DCA output exposes a
  block-level "OK that resolved from a >3σ shift" the agent could also use, or whether change
  detection rests solely on RMS-vs-baseline (current assumption).
- **Baseline readiness constants** — the **σ-floor** and **minimum OK-block count** that
  together gate baseline usability (FR-7).
- **Input-version + config-version semantics** — how a reading's input version is derived
  from DCA identity/supersession (FR-16), and how config versions are stamped and resolved so
  results stay reproducible after retuning (FR-17).
- **Trigger contract** — the exact shape of the post-DCA trigger's two ID lists (new +
  corrected) and its delivery guarantees (FR-8, FR-16, Invocation & Work Intake).
- **Structural-analysis config home** — where this agent's constants live relative to the
  DCA's sensor profiles (declared as required here; layout deferred to `plan.md`).
- **Crack-growth rate calc** — the deferred crack trend/regression check and its window
  (FR-9).
