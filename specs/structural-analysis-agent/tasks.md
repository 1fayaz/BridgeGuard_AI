# Structural Analysis Agent — Tasks

**Status:** Draft for review (do not implement until approved)
**Date:** 2026-06-27
**Spec:** `specs/structural-analysis-agent/spec.md` (17 FR / 20 AC)
**Plan:** `specs/structural-analysis-agent/plan.md` (Option A — deterministic service)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` v2.0.0

## Confirmed decisions (acceptance checks reference these + spec ACs)

- **Option A:** deterministic Python service, **no model-calling Agent loop**; SDK
  *conventions* for layout only. **n8n triggers it downstream of the DCA**; **Supabase**
  is the store.
- **Reads DCA tables unchanged** (`validated_readings`, `sensor_status`, registry/profiles);
  **writes one new table** `analysis_results` (+ audit), append-+-supersede, never in-place.
- **Block accelerometer reading = a waveform block**; **one FFT per block**; **per-block RMS**
  is computed on every eligible block and **is the change metric**.
- **FFT trigger** = per-block RMS deviates from the **learned baseline** ±k·σ (two-sided;
  low-side tagged `abnormal-quiet`) **OR** exceeds the **fixed engineer-set ceiling**;
  cold-start (baseline not yet usable) → **FFT every block**.
- **Learned baseline** recomputed from stored **OK-blocks after the latest re-baseline marker**,
  **excluding the agent's own prior event-flagged blocks**; usable only when **≥ min-block count
  AND σ ≥ σ-floor**.
- **Scalar threshold check** runs every eligible scalar reading regardless of change; emits
  **value, limit, ratio, pass/fail** (no warning band, no danger verdict). Displacement δ =
  `reading − reference zero`.
- **Closed outcome vocabulary:** `RAN | SKIPPED | ERROR`; skip-reason codes `NO_CALC |
  LIMIT_NOT_CONFIGURED | NO_REFERENCE | NO_CHANGE | INSUFFICIENT_BLOCK_COVERAGE |
  INSUFFICIENT_WINDOW | PENDING_WITHHELD | INELIGIBLE_STATUS | DEGENERATE_RESULT`.
- **Work intake:** trigger carries **two ID lists** (newly-validated + corrected/superseded);
  process per sensor **oldest→newest by sensor_time** (same-cycle siblings included);
  **non-superseded rows only**; **idempotent by input_version**.
- **Failure isolation per (sensor, calc, block)** → ERROR, continue; **degenerate result →
  SKIPPED/DEGENERATE_RESULT**, never a RAN NaN.
- **Deferred (named, not built in v1):** fatigue (FR-10), modal (FR-11), crack-rate.
- **All physical/safety constants stay `TODO`/`NaN`-marked config** (do not guess): per-block
  completeness floor, window min-blocks, k, σ-floor, RMS ceiling, baseline window, FFT top-N +
  peak rule, per-type design limits, span L, reference zeros, late-arrival lookback.

## Conventions

- Each task is < 1 hour and **independently verifiable**; acceptance checks are concrete
  (tied to an FR/AC or a decision above), never "works correctly".
- **[DB-DEP]** = needs live Supabase to fully verify; built/verified against an in-memory
  fake now, live verification honestly deferred (no Supabase locally).
- Constitution gates: never crash → always emit a structured outcome (FR-13); reads never
  mutate DCA tables; every result traces to its `validated_readings` source ids (Const. II/VI);
  fully deterministic (no LLM).
- **Reuse the DCA's proven patterns:** `statuses.py` enum style, `FakeStore` mirror,
  append-+-supersede triggers from `validated_readings` (0002), per-item isolation from
  `process_cycle`.

---

## Phase 1 — Analysis config (calc mapping + constants, config not code)

- **S101 — `AnalysisProfile` shape (per sensor type).**
  Fields: `sensor_type`, `calcs` (ordered list of calculations mapped to this type),
  `sample_rate_hz`/`block_len_n` (block sensors; **TODO**), `block_completeness_floor`
  (**TODO**), `window_min_blocks` (**TODO**), `rms_k_sigma` (**TODO**), `rms_sigma_floor`
  (**TODO**), `rms_ceiling` (**TODO**), `baseline_window` (count/age — **TODO**),
  `fft_top_n`/`peak_prominence` (**TODO**), `design_limit` + `limit_basis` (e.g. L/800;
  **TODO**), `reference_zero` (displacement; **TODO**), `clock_drift_policy` (=run-but-flag).
  **Acceptance:** constructs with all fields; non-physical defaults present (run-but-flag,
  calc list); every physical constant is a clearly-flagged `TODO`/`NaN` sentinel a reviewer
  sees is unset (config-TODO decision). Adding analysis for a type = one config entry.

- **S102 — Calc→type mapping + closed calc enum.**
  `Calculation` enum: `FFT | RMS | DEFLECTION_LIMIT | THRESHOLD` (v1) + reserved
  `FATIGUE | MODAL | CRACK_RATE` (declared, **unused**). Seed mappings: accelerometer →
  {RMS, FFT}; displacement/LVDT → {DEFLECTION_LIMIT}; strain/load/crack/tiltmeter →
  {THRESHOLD}; temperature → {} (context only).
  **Acceptance:** each of the 7 types resolves to its mapped calc list; the 4 v1 calcs are
  active and the 3 deferred are present-but-unmapped; a type with no mapped calc resolves to
  an empty list (drives `NO_CALC`, S401/FR-12).

- **S103 — Profile lookup + unknown/half-config signals.**
  `get_analysis_profile(sensor_type)` → profile or structured **"no analysis profile"** signal
  (never raises). Helpers distinguish **no calc mapped** (`NO_CALC`) from **calc mapped but
  required constant missing** (`LIMIT_NOT_CONFIGURED`) and **missing/stale reference zero**
  (`NO_REFERENCE`).
  **Acceptance:** known type → profile; unknown → signal, no raise; a mapped THRESHOLD calc
  with `design_limit=NaN` → `LIMIT_NOT_CONFIGURED` signal (distinct from `NO_CALC`); a
  displacement with no `reference_zero` → `NO_REFERENCE` signal. Supports FR-9/FR-12 taxonomy.

---

## Phase 2 — Shared status/outcome vocabulary + schema [DB-DEP]

- **S201 — `analysis_statuses.py` (closed vocabulary).**
  `Outcome` enum (`RAN | SKIPPED | ERROR`) and `SkipReason` enum (the 9 codes above),
  mirroring the DCA's `statuses.py` style and the SQL enums (S203).
  **Acceptance:** all 3 outcomes + all 9 skip reasons representable; a SKIPPED carries exactly
  one reason; RAN/ERROR carry none. Matches spec "Result Outcome Vocabulary (closed set)".

- **S202 — Result payload shapes (typed, per calc).**
  Frozen dataclasses for each calc's `result`: `RmsResult` (scalar + N); `FftResult` (top-N
  peaks [freq, amp] + sample_rate + resolution + window meta); `ThresholdResult` (value,
  limit, ratio, passed) — shared by DEFLECTION_LIMIT and generic THRESHOLD.
  **Acceptance:** each constructs typed; FFT result carries rate/resolution metadata (FR-6);
  threshold carries value/limit/ratio/pass-fail and **no** warning band (FR-9).

- **S203 — `analysis_results` table (append-+-supersede) [DB-DEP].**
  Columns: `id`, `sensor_id`, `sensor_type`, `sensor_time`, `calculation` (enum),
  `outcome` (enum), `reason_code` (enum, NULL when RAN), `result` (JSONB), flags
  (`interpolated_input`, `clock_drift`, `rate_mismatch`, `abnormal_quiet`),
  `source_validated_ids BIGINT[]`, `input_version`, `config_version`, `constants` (JSONB),
  `superseded_by`, `computed_at`. Same BEFORE-UPDATE guard (only `superseded_by` mutable) +
  DELETE-block triggers as `validated_readings` (0002).
  **Acceptance:** all enums representable; a non-RAN row requires a `reason_code` (CHECK,
  analogous to `non_ok_has_reason`); mutating value/outcome/sensor_time of an existing row is
  blocked (correct-by-append); DELETE revoked. Uniqueness on
  `(sensor_id, calculation, sensor_time, input_version)` among current rows (idempotency,
  FR-16). [DB-DEP live enforcement deferred.]

- **S204 — Audit: extend `decision_log` enum [DB-DEP].**
  Add `ANALYSIS_RUN | ANALYSIS_SKIP | ANALYSIS_ERROR | RECOMPUTE | REBASELINE` to
  `decision_kind` (one shared cross-agent audit trail, per plan §2b recommendation).
  **Acceptance:** the 5 new kinds representable alongside the DCA's 9; a RECOMPUTE row records
  `old→new`; a REBASELINE row records who/when/why (FR-7, FR-17). [DB-DEP deferred.]

---

## Phase 3 — RMS (FR-5; runs on every eligible block) + test

- **S301 — `compute_rms(block_samples)`.**
  `RMS = √(1/N · Σ xᵢ²)` over the block's **usable** samples. Pure; returns the scalar + N.
  Non-finite/empty input → a **degenerate** signal (no NaN leak), not a raise.
  **Acceptance:** known array → exact RMS (hand-checked); empty/all-zero/single-sample →
  degenerate signal (feeds S304 `DEGENERATE_RESULT`), never NaN-as-value, never raises.

- **S302 — Per-block completeness gate (FR-4.1).**
  `block_coverage(block, profile)` → usable-sample fraction/count vs declared
  `block_len_n`; below `block_completeness_floor` → `INSUFFICIENT_BLOCK_COVERAGE`.
  **Acceptance:** a full block passes; a block with too few samples → the skip signal naming
  achieved-vs-required; uses the profile floor (TODO fixture value in test), not a hardcode.

- **S303 — Test RMS + completeness (FR-5, FR-4.1).**
  **Acceptance:** RMS emitted for every block above the floor (assert RMS is **not** change-
  gated); a sub-floor block → SKIPPED/`INSUFFICIENT_BLOCK_COVERAGE`; exact-floor boundary
  behaviour asserted.

---

## Phase 4 — Learned RMS baseline + change trigger (FR-6, FR-7) + test

- **S401 — `compute_rms_baseline(history, marker, prior_results, profile)`.**
  Baseline = mean/σ of **OK-block RMS** values **after the latest re-baseline marker**,
  **excluding** blocks flagged as events in their own prior `analysis_results` (G: no self-
  poisoning). Returns mean/σ + a **usable** flag (`count ≥ min_blocks AND σ ≥ σ-floor`).
  **Acceptance:** (i) events the agent previously flagged are excluded from mean/σ; (ii)
  blocks before the marker excluded; (iii) `< min_blocks` → not usable; (iv) σ ≈ 0 (identical
  values) → not usable (σ-floor); (v) no divide-by-zero. = FR-7 + baseline-poisoning guard.

- **S402 — `check_rms_change(rms, baseline, profile)`.**
  Usable baseline: `|rms − mean| > k·σ` → triggered; **low-side** (rms < mean − k·σ) →
  triggered **+ `abnormal_quiet` tag**; OR `rms > ceiling` → triggered (high-side). Baseline
  **not usable** → **cold-start: triggered** (run FFT). Within band → not triggered
  (`NO_CHANGE`).
  **Acceptance:** high deviation → triggered (no quiet tag); low deviation → triggered +
  `abnormal_quiet`; ceiling breach with usable baseline → triggered; within band → not
  triggered; cold-start (unusable baseline) → triggered. = FR-6 two-sided + cold-start.

- **S403 — Test baseline + trigger (FR-6, FR-7).**
  **Acceptance:** drives S401→S402: fresh sensor (no baseline) → every block triggers; once
  `min_blocks` OK-blocks with σ≥floor accrue → within-band blocks emit `NO_CHANGE`; a prior
  event RMS does **not** raise the baseline mean (poisoning guard); a quiet block carries
  `abnormal_quiet`. = AC-2, AC-5(cold-start), AC-6(poisoning), AC-19(quiet).

---

## Phase 5 — FFT (FR-6 output) + sample-rate resolution + test

- **S501 — `compute_fft(block_samples, sample_rate)` → top-N peaks.**
  Real FFT; return **top-N dominant frequencies with amplitudes** + resolution metadata
  (not the full spectrum). Pure. Degenerate (empty/all-zero/single-sample) → degenerate
  signal, never NaN/empty-as-RAN.
  **Acceptance:** a synthesized single-tone block → that frequency is the dominant peak
  (within resolution); top-N honoured; metadata (rate, resolution, N) present; degenerate
  input → degenerate signal. = FR-6 output shape.

- **S502 — Sample-rate/length resolution + mismatch (FR-2).**
  Resolve rate/length from **config default**, allow **per-block override**; on disagreement
  **use the block's declared rate** and set `rate_mismatch`. INTERPOLATED block → **ineligible
  for FFT** (FR-3) → `INELIGIBLE_STATUS`.
  **Acceptance:** matching → no flag; block-override differing from config → FFT uses block
  rate + `rate_mismatch=true`; INTERPOLATED block → FFT skipped `INELIGIBLE_STATUS` (not run
  on interpolated data). = FR-2 + AC-8 + FR-3.

- **S503 — Test FFT + mismatch (FR-2, FR-6).**
  **Acceptance:** single-tone recovery; `rate_mismatch` flag on override-vs-config disagreement
  with FFT still produced on the block's rate; INTERPOLATED → INELIGIBLE_STATUS. = AC-8.

---

## Phase 6 — Scalar threshold check (FR-9) + test

- **S601 — `check_threshold(value, profile)` (generic scalar).**
  Emit `ThresholdResult(value, limit, ratio=value/limit, passed)`. Mapped-but-missing limit
  → `LIMIT_NOT_CONFIGURED`. **No** warning band, **no** danger verdict.
  **Acceptance:** value < / = / > limit → correct pass/fail + ratio; missing limit →
  `LIMIT_NOT_CONFIGURED` (distinct from `NO_CALC`); result carries no "approaching"/danger
  field. = FR-9 (strain/load/crack/tilt) + AC-7.

- **S602 — Deflection limit (displacement/LVDT) with reference zero (FR-9).**
  `δ = value − reference_zero`, then `check_threshold(δ, limit=L/800)`. Missing/stale
  reference → `NO_REFERENCE` (δ never computed from raw displacement).
  **Acceptance:** with reference → δ computed and limit-checked; **missing reference →
  SKIPPED/`NO_REFERENCE`**, no δ emitted; crack handled as **absolute width only** (no rate in
  v1, deferred). = FR-9 + AC-7.

- **S603 — Test scalar threshold (FR-9, AC-7).**
  **Acceptance:** displacement over/under L/800 with reference → pass/fail + ratio; missing
  reference → NO_REFERENCE; missing limit → LIMIT_NOT_CONFIGURED; runs **every cycle
  regardless of change** (assert not change-gated); no danger classification. = AC-7.

---

## Phase 7 — Per-(sensor,calc,block) result envelope + isolation + degenerate (FR-13)

- **S701 — `AnalysisResult` dataclass + finiteness guard.**
  One emitted result: sensor/type/sensor_time, calculation, outcome, reason_code, typed
  `result`, the four flags, `source_validated_ids`, `input_version`, `config_version`,
  `constants`. A **finiteness/sanity check** downgrades any non-finite/empty calc output to
  `SKIPPED/DEGENERATE_RESULT` before emission.
  **Acceptance:** a NaN/Inf/empty calc output never emits as `RAN` — it becomes
  `SKIPPED/DEGENERATE_RESULT` with detail; a finite result emits `RAN` with its value. = FR-13
  degenerate rule.

- **S702 — Per-item failure isolation.**
  A guarded `run_one(sensor, calc, block, ...)` turns an unexpected exception into a structured
  `ERROR` result for **that pair only**; callers continue.
  **Acceptance:** an injected exception in one calc on one block → one `ERROR` result; all other
  (sensor, calc, block) pairs still produce results; nothing raises out. = FR-13 isolation +
  AC-16.

---

## Phase 8 — Orchestration (wire Phases 3–7) + work intake + ordering

- **S801 — `analyze_cycle(new_ids, corrected_ids, store, profiles, config_version)`.**
  Resolve each id's sensor/type/config (shared registry); read **current** validated rows +
  history; **group per sensor, order oldest→newest by sensor_time** (same-cycle siblings feed
  each other's baseline); for each (sensor, calc, block): eligibility (FR-3) → gates (FR-4) →
  RMS always (S301) → FFT if triggered (S402/S501) → scalar threshold (S601/S602); isolate per
  item (S702). Emit one `AnalysisResult` per eligible (sensor, calc, block).
  **Acceptance:** **exactly one** result per eligible (sensor, calc, block); ordering is oldest→
  newest (assert a same-cycle earlier OK-block is in a later block's baseline); only non-
  superseded rows consumed; deterministic given fixed inputs. = FR-1, AC-11, AC-18.

- **S802 — Eligibility filter (FR-3, whole-reading status).**
  PENDING → `PENDING_WITHHELD`; CORRUPT/SPIKE → `INELIGIBLE_STATUS`; NO_DATA → missing
  (window/coverage); INTERPOLATED → usable for RMS/threshold (flag `interpolated_input`),
  **ineligible** for FFT; OK → usable.
  **Acceptance:** each status routes exactly as above; an INTERPOLATED block used in RMS sets
  `interpolated_input=true` and is FFT-`INELIGIBLE_STATUS`; PENDING never consumed. = FR-3,
  AC-4.

- **S803 — Window coverage gate + clock-drift propagation (FR-4.2, FR-14).**
  Too few usable blocks in the window → change-trigger "not available" → cold-start (not a
  false `NO_CHANGE`); carry `clock_drift` from any input reading onto the result.
  **Acceptance:** under-populated window → cold-start FFT (not `NO_CHANGE`); a `clock_drift`
  input → result `clock_drift=true` (run-but-flag). = FR-4.2, AC-3, AC-15.

- **S804 — Idempotency + late-arrival recompute (FR-16, FR-8).**
  Before emit, skip a (sensor, calc, block, **input_version**) that already has a current
  result (no-op). For each **corrected id**: recompute that reading's **own** result, emit a
  **new** row, set the old `superseded_by`, log `RECOMPUTE` (old→new). Bounded to the corrected
  reading's own result (documented neighbour-staleness tradeoff).
  **Acceptance:** re-running the same cycle (same input_versions) → **no duplicate** rows;
  a corrected id (new input_version) → supersedes with a RECOMPUTE log, old row preserved;
  recompute does **not** re-judge other blocks. = FR-16, FR-8, AC-9, AC-17.

---

## Phase 9 — Persistence + audit (Supabase) [DB-DEP]

- **S901 — `FakeAnalysisStore` mirroring S203/S204 guarantees.**
  In-memory store: append `analysis_results`, supersede (only `superseded_by`), block delete,
  enforce the current-row uniqueness key, append audit. Mirrors `validated_readings` guarantees
  the way the DCA's `FakeStore` does.
  **Acceptance:** insert assigns id; supersede links old→new and never mutates value/outcome;
  delete blocked; a duplicate (sensor, calc, sensor_time, input_version) among current rows is
  rejected/no-op. = S203 guarantees in-memory.

- **S902 — `persist_analysis_cycle(store, results, audit, config_version)` [DB-DEP].**
  Write one `analysis_results` row per result (RAN/SKIPPED/ERROR), each linking
  `source_validated_ids` + `config_version` + `constants`; append audit rows
  (ANALYSIS_RUN/SKIP/ERROR, RECOMPUTE, REBASELINE). A clean RAN is recorded by its result row,
  not spammed to audit.
  **Acceptance (fake store):** a cycle with 1 RAN FFT + 1 NO_CHANGE skip + 1 threshold pass +
  1 ERROR + 1 recompute produces exactly the expected result + audit rows; every result links
  to its validated source ids and records `config_version` (FR-13/FR-17). [DB-DEP live deferred.]

---

## Phase 10 — Trigger wiring (downstream of DCA, via n8n)

- **S1001 — Service invocation entrypoint.**
  A single callable n8n hits with `{new_ids, corrected_ids, config_version}`; returns a
  structured per-cycle summary (counts by outcome). Malformed input → structured error, never a
  stack trace (FR-13).
  **Acceptance:** given the two ID lists, returns per-(sensor,calc) outcomes; malformed payload
  → structured error; idempotent on redelivery (S804). = FR-13, FR-16.

- **S1002 — n8n workflow definition (glue only, downstream of DCA).**
  n8n fires **on DCA-cycle-complete**, forwards the DCA-provided new/corrected ID lists to
  S1001, retries the **trigger**. No calculation logic in n8n.
  **Acceptance:** workflow doc/export exists; DCA-complete → forward IDs → invoke path
  described; contains **no** calc logic (Const. III); plan §3 "DCA returns IDs, n8n forwards"
  reflected. [n8n/Supabase live verification deferred — none locally.]

---

## Phase 11 — End-to-end test (every spec AC)

- **S1101 — Simulated post-DCA stream harness.**
  Scripted validated-row streams via injected inputs: steady (no change), RMS spike (high),
  abnormal-quiet (low), cold-start, mostly-NO_DATA window, sub-floor block, INTERPOLATED block,
  PENDING input, deflection over/under limit, missing reference, half-config (missing limit),
  no-calc type, multi-block cycle, out-of-order blocks, corrected/superseded id, redelivered
  trigger, degenerate block, clock-drift input.
  **Acceptance:** deterministic and replayable; covers every spec scenario + reviewed decisions.

- **S1102 — E2E asserting AC-1…AC-20.**
  **Acceptance:** drive cycles; assert each AC manifests in `analysis_results` + audit:
  AC-1 FFT on spike · AC-2 NO_CHANGE skip · AC-3 two-level gate/insufficient · AC-4 eligibility ·
  AC-5 cold-start · AC-6 poisoning guard · AC-7 threshold/NO_REFERENCE/LIMIT_NOT_CONFIGURED ·
  AC-8 rate mismatch · AC-9 recompute+supersede · AC-10 NO_CALC · AC-11 multi-block · AC-12
  exhaustive+closed-vocabulary · AC-13 no fatigue/modal · AC-14 conflicting sensors both emitted ·
  AC-15 drift+temp provenance · AC-16 isolation+degenerate · AC-17 idempotency · AC-18 ordering ·
  AC-19 abnormal-quiet · AC-20 reproducible audit (config_version). = **all spec ACs**.

- **S1103 — Constitution check test.**
  **Acceptance:** never-crash (degenerate/malformed → outcome, not raise); reads never mutate
  DCA tables; every result traces to validated source ids; deferred calcs emit nothing
  (FR-10/11). = Const. II/VI + spec deferrals.

---

## Phase 12 — README (module docs)

- **S1201 — Module README.**
  Inputs (which DCA rows it reads, the block vs scalar distinction), outputs (the closed
  outcome/reason vocabulary, per-calc result shapes, the four flags), trigger contract
  (downstream of DCA, two ID lists), baseline/idempotency/recompute rules, and explicit
  out-of-scope (danger scoring → Risk Agent; alerts → Alert Agent; fatigue/modal deferred).
  **Acceptance:** README present; documents inputs, outputs, outcome vocabulary, trigger;
  matches the implemented contract.

- **S1202 — "Add a calculation / sensor-type mapping via config only" guide.**
  Step-by-step: add a `Calculation` mapping + constants to `AnalysisProfile`, **no calc-logic
  change** for re-mapping an existing calc to a new type.
  **Acceptance:** mapping an existing v1 calc to a new type requires only config edits;
  validates "config, not code". (A genuinely new calc kind is a code change — noted honestly.)

---

## Dependency Order

```
P1 (analysis config) ─┐
P2 (vocab + schema)  ─┴─► P3 RMS, P4 baseline/trigger, P5 FFT, P6 threshold (parallel after P1/P2)
                              └─► P7 (result envelope + isolation)
                                    └─► P8 (orchestration: intake, ordering, idempotency, recompute)
                                          └─► P9 (persistence) ─► P10 (n8n) ─► P11 (E2E) ─► P12 (README)
```
- P4 (baseline) consumes P3 (RMS is the baseline metric); P5 (FFT) is gated by P4's trigger.
- P8 wires all calcs + P7 isolation; needs P1/P2 config+vocab.
- P9 mirrors the DCA FakeStore; P11 requires P8 (+P10 for the trigger path).

## Coverage (tasks ↔ acceptance criteria / decisions)

| AC / Decision | Tasks |
|---------------|-------|
| AC-1 FFT on RMS spike | S401, S402, S501, S801, S1102 |
| AC-2 NO_CHANGE skip | S402, S403, S1102 |
| AC-3 two-level gate / insufficient | S302, S803, S1102 |
| AC-4 status eligibility | S802, S1102 |
| AC-5 cold-start FFT | S402, S403, S1102 |
| AC-6 baseline poisoning guard | S401, S403, S1102 |
| AC-7 threshold / NO_REFERENCE / LIMIT_NOT_CONFIGURED | S103, S601, S602, S603, S1102 |
| AC-8 rate mismatch | S502, S503, S1102 |
| AC-9 recompute + supersede | S804, S902, S1102 |
| AC-10 NO_CALC | S102, S103, S1102 |
| AC-11 multi-block | S801, S1102 |
| AC-12 exhaustive + closed vocabulary | S201, S701, S801, S1102 |
| AC-13 no fatigue/modal in v1 | S102, S1103 |
| AC-14 conflicting sensors both emitted | S801, S1102 |
| AC-15 drift + temp provenance | S803, S1102 |
| AC-16 isolation + degenerate | S701, S702, S1102 |
| AC-17 idempotency | S804, S901, S1102 |
| AC-18 ordering | S801, S1102 |
| AC-19 abnormal-quiet | S402, S403, S1102 |
| AC-20 reproducible audit (config_version) | S203, S902, S1102 |
| Closed outcome vocabulary | S201, S701 |
| Reads DCA tables unchanged / new table only | S203, S801, S1103 |
| Const. II/VI traceable + append-only | S203, S901, S902 |
| Deferred fatigue/modal/crack-rate | S102, S602, S1103 |

## Open (non-blocking) — carried config TODOs + cross-agent items

- **All physical/safety constants** (`TODO`/`NaN` in S101): per-block floor, window min-blocks,
  k, σ-floor, RMS ceiling, baseline window, FFT top-N + peak rule, per-type design limits,
  span L, reference zeros, late-arrival lookback. Logic buildable; only constants change.
- **Cross-agent: block-waveform storage (plan §2c)** — where accelerometer samples FFT runs on
  actually live (raw-via-`source_raw_ids` / validated-block sidecar / object store). Blocks on
  the DCA's unbuilt block ingestion; **resolve before S501/S801 read the waveform**.
- **Trigger ID-list ownership (plan §3):** confirm **DCA returns** new/corrected IDs, n8n
  forwards (S1002).
- **`config_version` mechanics (FR-17):** how config is versioned/stamped (S203/S902).
- **[DB-DEP] / n8n-live:** S203/S204 schema, S902 persistence, S1002 n8n path need live
  Supabase + n8n to verify end-to-end; built against fakes now, live deferred (flagged, not faked).
```
