# Risk Reasoning Agent — Tasks

**Status:** Draft for review (do not implement until approved)
**Date:** 2026-06-29
**Spec:** `specs/risk-reasoning-agent/spec.md` (13 FR / 12 AC, 3 mandated requirements)
**Plan:** `specs/risk-reasoning-agent/plan.md` (it IS a model-calling Agent — the one in BridgeGuard)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` v2.0.0

## Confirmed decisions (acceptance checks reference these + spec ACs)

- **This IS an OpenAI Agents SDK Agent, frontier tier** — the deliberate inverse of the DCA/SA
  deterministic services. **n8n triggers it downstream of SA**, **once per bridge per
  SA-cycle-complete**; **Supabase** is the store.
- **The score is deterministic code** (`score_bridge`): normalise each SA result's value/limit
  **ratio** to 0–100, weight, combine. The **model EXPLAINS** it — never invents the number (FR-2).
- **Three read-only `@function_tools`**, not one mega-tool, not a handoff:
  `get_calculation_results`, `get_historical_baseline`, `get_engineering_standard`. Control
  returns to the reasoner after each; SA does not hand off to this agent (FR-3).
- **No `needs_approval` here** — emitting a recommendation harms nothing; the HITL gate is on the
  **Alert Agent's** dispatch tool. This agent's Principle-I contribution is the
  `PENDING_HUMAN_REVIEW` mark, a *flag* not a gate (FR-5/FR-11).
- **Numeric-provenance output guardrail** = extract every number in the explanation → match
  against the run's legitimate-number set (RAN `analysis_results` values + the deterministic
  score/factors + the pinned standard) → on a miss **regenerate once, then fail closed** to
  `PENDING_HUMAN_REVIEW` score-withheld (FR-7, mandate #2).
- **Coverage floor gates scoring** (FR-6): below the floor (too few `RAN` results / standard
  missing) → withhold the score, write a real row marked `PENDING_HUMAN_REVIEW`, never a
  confident guess, never a crash.
- **Confidence is deterministic, annotation-only** — gates degraded/withhold but **does not move
  the score** (FR-6a).
- **`CRITICAL` → `PENDING_HUMAN_REVIEW`, not final until human-reviewed** (FR-11, mandate #3);
  non-Critical carries an explicit `review_status` too. The clearing workflow is **out of scope**.
- **Dual audit:** a structured `risk_assessments` row (score, severity, recommendation, **verbatim
  explanation**, consulted IDs, model+version, trace_id, factors, review_status) **and** the
  always-on SDK trace; reproducible from pinned inputs; append-+-supersede, never in-place (FR-9/10).
- **Score+explanation are one deliverable** — emit both or neither; a bare number is a defect (FR-1).
- **All score weights, the coverage-floor value, band thresholds, the completeness formula, and the
  guardrail match tolerance stay `TODO`-marked config** (do not guess safety numbers).

## Conventions

- Each task is < 1 hour and **independently verifiable**; acceptance checks are concrete (tied to
  an FR/AC or a decision above), never "works correctly".
- **[DB-DEP]** = needs live Supabase to fully verify; built/verified against an in-memory fake
  now, live verification honestly deferred (no Supabase locally).
- **[LLM-DEP]** = needs a live frontier model + SDK to fully verify; built/verified against a
  **fake/stubbed model** now (deterministic canned drafts), live verification honestly deferred
  (no API key / SDK runtime asserted locally). The guardrail, scorer, gating, and persistence are
  all testable **without** a live model — only the genuine reasoning step is [LLM-DEP].
- Constitution gates: never crash → always emit a structured assessment, incl. the withheld row
  (FR-8); reads never mutate SA/DCA tables; every emitted number traces to a retrieved value
  (Const. II/VI, FR-7); the score is deterministic (no LLM arithmetic, Principle IV).
- **Reuse proven patterns:** the DCA/SA `statuses.py` enum style, `FakeStore` mirror, and the
  append-+-supersede triggers from `validated_readings` (0002) / `analysis_results` (0005).

---

## Phase 1 — Config (score weights, bands, floors — config not code)

- **R101 — `ScoreConfig` shape (weights, normalisation, band table).**
  Fields: per-factor `weights` (map factor→weight; **TODO**), per-factor normalisation params
  (how a value/limit **ratio** maps to 0–100; **TODO**), `band_thresholds` (the `SAFE | WATCH |
  WARNING | CRITICAL` cut-points; **TODO**), `score_weights_version` (concrete, for audit). NaN
  sentinel for every safety number, same discipline as SA's `AnalysisProfile`.
  **Acceptance:** constructs with all fields; `score_weights_version` is concrete; every weight /
  threshold / normalisation constant is a clearly-flagged `TODO`/`NaN` sentinel a reviewer sees is
  unset; an `is_fully_configured` property is False while any safety number is unset. (do-not-guess)

- **R102 — `CoverageConfig` shape (floor + completeness formula params).**
  Fields: `coverage_floor` (min fraction of expected `RAN` results to score vs. withhold; **TODO**),
  completeness-formula params (**TODO**), `require_standard_present` (=True, non-physical default).
  **Acceptance:** constructs; `coverage_floor` is a `TODO`/`NaN` sentinel; `require_standard_present`
  defaults True; below-floor and at-floor are distinguishable by a pure predicate (no hardcode).

- **R103 — Band mapping `severity_for(score, config)` (FR-4).**
  Pure function: 0–100 → exactly one of `SAFE | WATCH | WARNING | CRITICAL` via the config table;
  near-boundary is reported (a `near_boundary` flag) but **does not** move the band.
  **Acceptance:** scores in each band map to exactly that band; a boundary value maps
  deterministically to one side; a near-boundary score sets `near_boundary` without changing the
  band; unset thresholds → structured "not configured", never a guessed band. = FR-4, Edge "borderline".

---

## Phase 2 — Output vocabulary + schema [DB-DEP]

- **R201 — `risk_statuses.py` (closed vocabulary).**
  `Severity` enum (`SAFE | WATCH | WARNING | CRITICAL`) and `ReviewStatus` enum (`FINAL |
  PENDING_HUMAN_REVIEW`), mirroring the DCA/SA `statuses.py` style and the SQL enums (R203).
  **Acceptance:** all 4 severities + both review statuses representable; a withheld assessment
  carries `severity = None` + `review_status = PENDING_HUMAN_REVIEW`; matches the spec output contract.

- **R202 — Output payload shape (typed assessment + contributing factors).**
  Frozen dataclasses: `ContributingFactor` (which SA result / `source_analysis_id`, its ratio, its
  weight, direction it pushed); `RiskAssessment` (bridge_id, cycle_id, `risk_score` (None when
  withheld), `severity` (None when withheld), `recommendation`, `explanation` verbatim,
  `contributing_factors` tuple, `confidence`/`data_completeness`, `review_status`, provenance:
  `source_analysis_ids`, `baseline_ref`, `standard_code`+`standard_version`, `score_weights_version`,
  `model_id`+`model_version`, `trace_id`).
  **Acceptance:** constructs typed; a withheld assessment is representable with `risk_score=None`,
  `severity=None`, a populated `explanation`, and `review_status=PENDING_HUMAN_REVIEW`; a scored
  assessment carries score + severity + ≥1 factor; the factor set carries each number's provenance.

- **R203 — `risk_assessments` table (append-+-supersede) [DB-DEP].**
  Columns per plan §3b: `id`, `bridge_id`, `cycle_id`, `assessed_at`, `risk_score` (NULL when
  withheld), `severity` (enum, NULL when withheld), `recommendation`, `explanation`,
  `contributing_factors` (JSONB), `confidence`/`data_completeness`, `review_status` (enum),
  `source_analysis_ids BIGINT[]`, `baseline_ref`, `standard_code`, `standard_version`,
  `score_weights_version`, `model_id`, `model_version`, `trace_id`, `superseded_by`. Same
  BEFORE-UPDATE guard (only `superseded_by` mutable) + DELETE-block triggers as `validated_readings`.
  **Acceptance:** enums representable; a `CRITICAL` row requires `review_status=PENDING_HUMAN_REVIEW`
  (CHECK); a withheld row allows NULL score+severity but requires a non-null `explanation` +
  `PENDING_HUMAN_REVIEW` (CHECK); mutating score/severity/explanation of an existing row is blocked
  (correct-by-append); DELETE revoked; uniqueness on `(bridge_id, cycle_id)` among current rows
  (idempotency). [DB-DEP live enforcement deferred.]

- **R204 — Audit: extend `decision_log` enum [DB-DEP].**
  Add `RISK_ASSESSMENT | RISK_WITHHELD | RISK_GUARDRAIL_FAIL` to `decision_kind` (one shared
  cross-agent audit trail, per plan §3b).
  **Acceptance:** the 3 new kinds representable alongside the DCA's/SA's existing kinds; a
  `RISK_WITHHELD` row records the gap reason; a `RISK_GUARDRAIL_FAIL` row records that the
  untraceable-number tripwire fired. [DB-DEP deferred.]

---

## Phase 3 — Deterministic scorer (FR-2) + test

- **R301 — `normalise_ratio(value, limit, params)` → 0–100 (pure).**
  Map one SA result's value/limit **ratio** to a 0–100 factor contribution per the config
  normalisation params. Non-finite / missing-limit input → a structured "not scorable" signal
  (no NaN leak), not a raise.
  **Acceptance:** a ratio at the limit, well under, and well over map to hand-checked 0–100 values;
  missing limit / non-finite → not-scorable signal (feeds R303 gap handling), never NaN-as-score,
  never raises; uses config params (TODO fixture value in test), not a hardcode. = FR-2.

- **R302 — `score_bridge(ran_results, config)` → score + factors (pure).**
  Combine the normalised per-result contributions with the configured weights into one 0–100
  whole-bridge score; return the score **and** the `ContributingFactor` list (each factor's
  source_analysis_id, ratio, weight, direction). Deterministic; identical inputs → identical score.
  **Acceptance:** a fixed result set yields a hand-checked weighted score and a factor per scored
  result; reordering inputs does not change the score (order-independent combine); the score is
  reproducible across repeated calls; weights come from config, not hardcoded. = FR-2, AC-2.

- **R303 — Test scorer + reproducibility (FR-2, AC-2).**
  **Acceptance:** drives R301→R302: a mix of high/low ratios → expected score + bands via R103;
  a not-scorable result is excluded from the score and recorded as a gap (not silently dropped);
  identical pinned inputs → identical score (AC-2). The model is **not** involved — assert the
  score is pure code (Principle IV — arithmetic out of the model).

---

## Phase 4 — Coverage gate + confidence (FR-6, FR-6a) + test

- **R401 — `coverage_check(analysis_results, expected, config)` (FR-6).**
  Compute the fraction of expected SA results that are `RAN` (excluding `SKIPPED`/`ERROR`) and
  whether the standard is present; below `coverage_floor` (or standard missing) → **withhold**
  signal (score gated off); at/above → **score** signal. Pure.
  **Acceptance:** all-RAN + standard present → score; mostly `SKIPPED`/`ERROR` → withhold naming the
  gap; standard missing → withhold even with full calc coverage; exact-floor boundary asserted; uses
  config floor (TODO fixture), not a hardcode. = FR-6.

- **R402 — `data_completeness(analysis_results, expected, config)` (FR-6a).**
  Pure deterministic completeness/confidence measure (present-vs-expected + input flags); returns a
  scalar annotation. **Does not** feed `score_bridge`.
  **Acceptance:** full coverage → high completeness; missing/flagged inputs → reduced completeness;
  the value is annotation-only — assert R302's score is **unchanged** when only completeness changes
  (FR-6a: confidence never moves the score).

- **R403 — Test coverage gate + confidence (FR-6, FR-6a, AC-6).**
  **Acceptance:** below-floor input → withheld assessment with reduced confidence naming the gap,
  `review_status=PENDING_HUMAN_REVIEW`, no fabricated number, no crash; above-floor → scored;
  confidence annotates but does not alter the score. = AC-6.

---

## Phase 5 — The three read-only tools (FR-3) [DB-DEP]

- **R501 — `get_calculation_results(bridge_id, cycle_id)` (@function_tool, read-only).**
  Reads **current non-superseded** `analysis_results` for the bridge+cycle; returns each result's
  calc, outcome, reason_code, `result` payload, the four flags, and `source_validated_ids`. Never
  writes. Missing/empty → structured "no results" (not a raise).
  **Acceptance (fake store):** returns the bridge's current results; superseded rows excluded;
  empty cycle → structured empty, no raise; the call performs **no** mutation (assert store
  unchanged). = FR-3 (tool 1), Const. III read-only. [DB-DEP live deferred.]

- **R502 — `get_historical_baseline(bridge_id, window)` (@function_tool, read-only).**
  Reads rolling baseline / prior `risk_assessments` for trend context. Read-only. Missing → "no
  baseline" signal (cold-start trend), not a raise.
  **Acceptance (fake store):** returns baseline rows for the window; no-history bridge → "no
  baseline" signal; no mutation. *(Open Item: exact baseline contract shape.)* = FR-3 (tool 2).

- **R503 — `get_engineering_standard(bridge_type)` (@function_tool, read-only) + pinning.**
  Returns the applicable standard's limits **with value + version**, captured for pinning at
  decision time. Unknown/ambiguous bridge type → structured "standard unavailable" (drives the
  degraded path, FR-6), never a guessed limit.
  **Acceptance (fake source):** known type → limits + `standard_code` + `standard_version`;
  unknown type → "standard unavailable" signal (no guess); the returned version is captured for the
  assessment's provenance (FR-10). *(Open Item: curated store vs. live retrieval.)* = FR-3 (tool 3),
  FR-10, Edge "standard unavailable". [DB-DEP/source-dep live deferred.]

- **R504 — Test the three tools read-only + structured-empty (FR-3, AC-3).**
  **Acceptance:** each tool returns its typed result against the fake store/source; each leaves all
  stores unmutated (assert before==after); each returns a structured signal (not a raise) on
  missing data. = AC-3 (three distinct read-only fetches, mutates nothing).

---

## Phase 6 — Numeric-provenance output guardrail (FR-7, mandate #2) + test

- **R601 — `extract_numbers(explanation_text)` (pure).**
  Pull every numeric literal from the draft explanation (integers, decimals, ratios, percentages),
  with enough context to compare against the legitimate set.
  **Acceptance:** a narrative with N numbers yields exactly those N values; formatted numbers
  (commas, units, %, "mm") are captured; prose without numbers → empty set. = FR-7 support.

- **R602 — `build_legitimate_set(ran_results, score, factors, standard)` (pure).**
  Assemble the set of numbers the explanation is **allowed** to cite: every `RAN`
  `analysis_results` value, the deterministic score + each factor's ratio/weight, and the pinned
  standard's limits. (The score is in the set by construction — it is computed in code.)
  **Acceptance:** the deterministic score and each factor number are present; an SA result's RMS /
  ratio / limit is present; a number from **no** input is absent; uses the config match tolerance
  (TODO fixture), not a hardcode. = FR-7 support.

- **R603 — `provenance_guardrail(draft, legitimate_set, tolerance)` (the SDK output guardrail).**
  Return pass / tripwire: every extracted number must match a legitimate number within tolerance;
  any unmatched number → tripwire. Pure decision function (wired into the SDK guardrail slot in R703).
  **Acceptance:** a draft whose every number traces → pass; a draft with an invented "deflection was
  48 mm" → tripwire naming the offending number; a number within rounding tolerance of a real value
  → pass; tolerance comes from config. = FR-7, AC-7 (positive + negative).

- **R604 — Test guardrail regenerate-once-then-fail-closed (FR-7, AC-7).**
  **Acceptance:** drives the loop with a fake model: (i) clean draft → emitted; (ii) one bad draft
  then a clean regenerate → emitted after exactly **one** regeneration; (iii) two bad drafts →
  **fail closed** to a withheld assessment (`risk_score=None`, `review_status=PENDING_HUMAN_REVIEW`,
  explanation naming the failure), `RISK_GUARDRAIL_FAIL` audited; the untraceable number is **never**
  emitted. = AC-7, mandate #2.

---

## Phase 7 — The Agent (assemble scorer + tools + model + guardrail) [LLM-DEP]

- **R701 — Reasoning prompt + agent definition (frontier tier).**
  Define the Agent: frontier model (`model_id` from deployment config, pinned/recorded), the three
  `@function_tools` (R501–R503), and a prompt that instructs the model to **explain** the
  already-computed score and reconcile conflicting factors — explicitly **not** to invent the number.
  **Acceptance:** the agent is constructed with exactly the three read-only tools and no
  action/dispatch tool (no `needs_approval` tool present — FR-5); the prompt states the score is a
  fixed input to explain; `model_id`/`model_version` are recorded for audit (FR-9). [LLM-DEP — built
  against a fake model; live run deferred.]

- **R702 — `FakeReasoningModel` (deterministic stub for tests).**
  A stub returning canned explanation drafts keyed by scenario (clean / one-bad-then-clean /
  two-bad / conflicting-factors), so Phases 3–9 are fully testable without a live model.
  **Acceptance:** the stub yields deterministic drafts per scenario; swapping it for the real model
  changes only the draft text, not the control flow (scorer/guardrail/gating/persistence unchanged).

- **R703 — `assess_bridge(bridge_id, cycle_id, store, score_config, coverage_config, model)` (orchestrator).**
  Wire the per-assessment flow (plan §6): (1) three tool fetches; (2) coverage gate (R401) — below
  floor → withheld row, stop; (3) `score_bridge` (R302) + `severity_for` (R103); (4) model drafts
  explanation + factors; (5) guardrail loop (R603/R604) regenerate-once-then-fail-closed; (6)
  `CRITICAL` or withheld → `review_status=PENDING_HUMAN_REVIEW` (R801); (7) build `RiskAssessment`.
  Per-assessment failure isolation → structured status, never a raise (FR-8).
  **Acceptance:** a normal scenario → scored assessment with score+explanation+factors+review_status;
  exactly one assessment per (bridge, cycle); the score is the deterministic value (not the model's);
  an injected tool/model exception → a structured withheld/error assessment, nothing raises out
  (FR-8). = FR-1, FR-3a, AC-1, AC-11. [LLM-DEP fake model.]

---

## Phase 8 — Critical / review-status + caveat propagation (FR-11, FR-8 flags) + test

- **R801 — `apply_review_status(assessment)` (FR-11, mandate #3).**
  Set `review_status = PENDING_HUMAN_REVIEW` whenever `severity == CRITICAL` **or** the score is
  withheld; otherwise `FINAL`. Pure, applied before emission.
  **Acceptance:** a `CRITICAL` assessment → `PENDING_HUMAN_REVIEW`; a withheld assessment →
  `PENDING_HUMAN_REVIEW`; a `SAFE`/`WATCH`/`WARNING` scored assessment → `FINAL` (but the field is
  always explicitly set, never absent). = FR-11, AC-12.

- **R802 — Caveat propagation into the explanation context (FR-8 flags, AC-8).**
  Carry each input's SA flags (`clock_drift`, `interpolated_input`, `rate_mismatch`,
  `abnormal_quiet`) into the reasoning context and require them surfaced as caveats in the
  explanation; assert they are not silently dropped.
  **Acceptance:** an input with `clock_drift` set → the assembled context flags it and the
  (fake-model) explanation includes the caveat; a frequency-based factor resting on a drifted block
  is marked less trustworthy; no flag is dropped. = AC-8.

- **R803 — Test critical-not-final + downstream-holds (FR-11, AC-12).**
  **Acceptance:** a `CRITICAL` assessment is emitted as a recommendation with
  `review_status=PENDING_HUMAN_REVIEW`; a simulated downstream consumer **rejects/holds** it as
  non-final (does not act); an assessment emitted as `CRITICAL` + `FINAL`, or missing the flag,
  fails the test. = AC-12, mandate #3.

---

## Phase 9 — Persistence + audit (Supabase) [DB-DEP]

- **R901 — `FakeRiskStore` mirroring R203/R204 guarantees.**
  In-memory store: append `risk_assessments`, supersede (only `superseded_by`), block delete,
  enforce the `(bridge_id, cycle_id)` current-row uniqueness, append audit. Mirrors the
  `validated_readings`/`analysis_results` guarantees the way the DCA/SA fakes do.
  **Acceptance:** insert assigns id; supersede links old→new and never mutates
  score/severity/explanation; delete blocked; a duplicate `(bridge_id, cycle_id)` among current rows
  is rejected/no-op (idempotency). = R203 guarantees in-memory.

- **R902 — `persist_assessment(store, assessment, audit)` [DB-DEP].**
  Write one `risk_assessments` row (scored **or** withheld), linking `source_analysis_ids` +
  `baseline_ref` + `standard_code`/`version` + `score_weights_version` + `model_id`/`version` +
  `trace_id`; append the matching audit row (`RISK_ASSESSMENT` / `RISK_WITHHELD` /
  `RISK_GUARDRAIL_FAIL`). The **verbatim** explanation is stored, not a summary (FR-9).
  **Acceptance (fake store):** a scored `WARNING` assessment, a withheld (below-floor) assessment,
  and a guardrail-fail assessment each produce exactly the expected row + audit kind; every row
  links its pinned provenance and stores the explanation verbatim. = FR-9, AC-9. [DB-DEP live deferred.]

- **R903 — Reproducibility from pinned inputs (FR-10, AC-10) test [DB-DEP].**
  **Acceptance (fake store):** an assessment is re-derivable from its recorded `source_analysis_ids`
  + `standard_code`/`version` + `score_weights_version` even after a standard version is bumped or an
  SA result is superseded; a re-assessment for the same `(bridge, cycle)` **supersedes** (appends +
  links old), never overwrites. = AC-10.

---

## Phase 10 — SDK tracing + trigger wiring (downstream of SA, via n8n)

- **R1001 — Tracing on from first run (Principle VII) [LLM-DEP].**
  Assert SDK tracing is enabled for the agent's run and the resulting `trace_id` is captured onto
  the `risk_assessments` row (links the structured record to the forensic trace — plan §5).
  **Acceptance:** a run produces a `trace_id`; the persisted assessment carries it; tracing is not
  conditionally disabled in any path (incl. withheld/guardrail-fail). [LLM-DEP — trace backend live
  verification deferred; presence of `trace_id` wiring asserted against the fake.]

- **R1002 — Service invocation entrypoint.**
  A single callable n8n hits with `{bridge_id, cycle_id}`; returns a structured per-assessment
  summary (score/severity/review_status or withheld-reason). Malformed input → structured error,
  never a stack trace (FR-8).
  **Acceptance:** given a bridge+cycle, returns the assessment summary; malformed payload →
  structured error; idempotent on redelivery (R901 uniqueness). = FR-8, FR-3a.

- **R1003 — n8n workflow definition (glue only, downstream of SA).**
  n8n fires **on SA-cycle-complete for a bridge**, invokes R1002 with `{bridge_id, cycle_id}`,
  retries the **trigger**. No scoring/reasoning logic in n8n.
  **Acceptance:** workflow doc/export exists; SA-complete → invoke path described per bridge;
  contains **no** scoring/judgment logic (Const. III); plan §6 reflected. [n8n/Supabase live
  verification deferred — none locally.]

---

## Phase 11 — End-to-end test (every spec AC)

- **R1101 — Scenario harness (fake store + fake model).**
  Scripted inputs covering: all-RAN normal, conflicting factors (high vibration + in-limit
  deflection), below-coverage-floor, standard-unavailable, all-four input flags present, a
  `CRITICAL`-band score, a borderline/near-boundary score, an invented-number draft (→ guardrail),
  one-bad-then-clean draft (→ regenerate-once), two-bad drafts (→ fail-closed), a re-assessment of
  the same `(bridge, cycle)`, and a malformed/partial input (never-crash).
  **Acceptance:** deterministic and replayable; covers every spec scenario + reviewed decisions.

- **R1102 — E2E asserting AC-1…AC-12.**
  **Acceptance:** drive assessments; assert each AC manifests in `risk_assessments` + audit:
  AC-1 score+explanation inseparable · AC-2 deterministic reproducible score · AC-3 three read-only
  fetches mutate nothing · AC-4 severity mapping · AC-5 recommendation-only / no gate · AC-6 degraded
  path · AC-7 guardrail (regenerate-once-then-fail-closed) · AC-8 caveat propagation · AC-9 dual audit
  · AC-10 reproducible + supersede · AC-11 never-crash 4-scenario · AC-12 Critical not-final until
  reviewed. = **all spec ACs**.

- **R1103 — Constitution check test.**
  **Acceptance:** never-crash (malformed/partial → withheld/error assessment, not raise); reads
  never mutate SA/DCA tables; every emitted number traces to a retrieved value (FR-7); the score is
  pure code (no LLM arithmetic); no `needs_approval`/dispatch tool present (gate is downstream).
  = Const. I/II/III/IV/VI.

---

## Phase 12 — README (module docs)

- **R1201 — Module README.**
  Inputs (the three read-only sources + what each provides), outputs (score+explanation, the closed
  severity/review-status vocabulary, contributing factors, provenance fields), the deterministic-
  score-the-model-explains split, the guardrail (regenerate-once-then-fail-closed), the coverage
  gate, trigger contract (downstream of SA, per bridge per cycle), and explicit out-of-scope
  (no real-world action → Alert Agent owns the gate; no calc re-running → SA; the human-review-
  clearing workflow).
  **Acceptance:** README present; documents inputs, outputs, the score/explain split, the guardrail,
  and the trigger; matches the implemented contract.

- **R1202 — "Tune weights / floor / bands via config only" guide.**
  Step-by-step: change `ScoreConfig` weights/normalisation, `CoverageConfig` floor, and the band
  table **without** touching scorer or agent code.
  **Acceptance:** changing a weight / floor / band threshold requires only config edits; validates
  "safety numbers are config, not code" (and that they remain `TODO` until an engineer supplies them).

---

## Dependency Order

```
P1 (config) ─┐
P2 (vocab + schema) ─┴─► P3 scorer, P4 coverage/confidence, P6 guardrail (parallel after P1/P2)
                          P5 (three tools) ─┐
                                            ▼
                          P7 (the Agent: scorer + tools + model + guardrail loop)
                                            └─► P8 (review-status + caveats)
                                                  └─► P9 (persistence) ─► P10 (tracing + n8n)
                                                        └─► P11 (E2E) ─► P12 (README)
```
- P3 (scorer) and P6 (guardrail) are pure and testable before the model exists (fake model in P7).
- P7 assembles P3 + P5 + P6 + the model; P8 applies FR-11 before persistence.
- P9 mirrors the DCA/SA FakeStore; P11 requires P7–P9 (+P10 for the trigger/trace path).

## Coverage (tasks ↔ acceptance criteria / decisions)

| AC / Decision | Tasks |
|---------------|-------|
| AC-1 score+explanation inseparable | R202, R703, R1102 |
| AC-2 deterministic reproducible score | R301, R302, R303, R1102 |
| AC-3 three read-only fetches, mutate nothing | R501, R502, R503, R504, R1102 |
| AC-4 severity mapping | R103, R1102 |
| AC-5 recommendation-only / no gate downstream | R701, R1103, R1102 |
| AC-6 degraded path (coverage floor) | R401, R402, R403, R1102 |
| AC-7 numeric-provenance guardrail (regen-once-then-fail-closed) | R601, R602, R603, R604, R1102 |
| AC-8 caveat propagation | R802, R1102 |
| AC-9 dual audit (row + verbatim + trace) | R902, R1001, R1102 |
| AC-10 reproducible + supersede | R903, R1102 |
| AC-11 never-crash 4-scenario | R703, R1002, R1103, R1102 |
| AC-12 Critical not-final until reviewed | R801, R803, R1102 |
| Score is deterministic (no LLM arithmetic) | R301, R302, R303, R1103 |
| No `needs_approval` here / gate downstream | R701, R1103 |
| Reads SA/DCA tables unchanged / new table only | R203, R501, R1103 |
| Const. II/VI traceable + append-only | R203, R901, R902 |
| `PENDING_HUMAN_REVIEW` flag (mandate #3) | R801, R803 |

## Open (non-blocking) — carried config TODOs + cross-agent items

- **All score weights / normalisation / band thresholds / coverage floor / completeness formula /
  guardrail match tolerance** (`TODO`/`NaN` in R101/R102): logic buildable; only constants change.
  Do not guess safety numbers.
- **Standards source + pinning (plan §3a, R503):** curated local store vs. live retrieval, and the
  concrete value+version pinning mechanism (FR-10). Resolve before R503 reads a real standard.
- **Historical-baseline contract shape (plan §3a, R502):** the schema/window of the baseline input.
- **Model ID + tier (R701/R1001):** the exact frontier model ID, pinned and recorded per assessment.
- **Alert-Agent chokepoint confirmation (cross-agent):** verify the Alert Agent is the single
  un-bypassable `needs_approval` point so FR-5's "gate downstream" holds in code (Principle I).
- **Trace retention / PII (governance):** retention + storage location for full prompt+response
  traces in a government context, relative to the Supabase row (FR-9).
- **Human-review-clearing workflow is OUT OF SCOPE here (FR-11 / spec Out of Scope):** who clears
  `PENDING_HUMAN_REVIEW` and the cleared→`FINAL` transition — named, not built in this agent.
- **[DB-DEP] / [LLM-DEP] / n8n-live:** R203/R204 schema, R902 persistence, R1003 n8n path need live
  Supabase + n8n; R701/R703/R1001 need a live frontier model + SDK runtime to verify end-to-end.
  Built against fakes now, live verification deferred (flagged, not faked).
```
