# Risk Reasoning Agent — Specification

**Status:** Clarified (behaviour-only; research-agent-003 + three mandated requirements baked in; clarification interview folded in)
**Date:** 2026-06-29

> **Three non-negotiable requirements (explicitly mandated for this spec):**
> 1. **Every risk score MUST include a plain-language explanation** — a bare number is a
>    defect (FR-1).
> 2. **Every numeric claim in that explanation MUST be traceable to a real calculation
>    result** — no invented numbers (FR-7).
> 3. **Any `CRITICAL`-band output MUST be marked for human review and is NOT final** until a
>    human has reviewed it — no downstream agent (including the Alert Agent) may treat a
>    Critical assessment as final on the agent's say-so alone (FR-11).
**Anchors:** `CLAUDE.md`; `.specify/memory/constitution.md` v2.0.0 (Principles I, IV, VI, VII);
`skills/bridgeguard-skills-README.md` (`math-analysis` 0–100 weighted risk score + bands;
`structural-research` IRC/AASHTO/Eurocode lookups); `specs/structural-analysis-agent/spec.md`
(upstream contract + its Out-of-Scope §517–519, which hands danger-judgment to this agent);
`specs/risk-reasoning-agent/research-agent-003.md` (research).

> **Behaviour only.** This spec describes WHAT the agent does and WHY — no SDK class names,
> databases, model IDs, or file layout. Those are design decisions made later (`plan.md`).

---

## Goal

This agent is the **judgment layer** of BridgeGuard. It consumes the Structural Analysis
Agent's (SA) calculation results, the relevant historical baseline/comparison data, and the
applicable engineering standards, and produces **two inseparable outputs**: a **0–100 risk
score with a severity band**, and a **plain-language written explanation** of *why* — the
contributing factors and the reasoning — that a government engineer will read and act on.

It exists because the upstream agents deliberately stop short of judgment: the SA spec emits
"numbers, ratios, and pass/fail-vs-limit facts, **never a danger verdict**" and names this
agent as the consumer (SA §25–27, §517–519). This is the **one agent in BridgeGuard that is
genuinely a model-calling Agent** — Principle IV reserves the LLM for exactly this kind of
compound, ambiguous judgment and human-facing narrative, where every upstream agent was
deterministic.

It produces a **recommendation only**. It never takes — and never gates — a real-world action
(Principle I); that human-approval gate lives downstream on the Alert Agent.

---

## Settled in clarification interview (baked into the FRs below)

- **Trigger + scope:** runs **once per bridge, on SA-cycle-complete** for that bridge; one
  assessment = **whole-bridge** risk at that moment, fusing all that bridge's sensors' current
  calc results (FR-3a).
- **Score construction:** deterministically **normalise each SA result's value/limit ratio to
  0–100, weight, and combine** — not the README's fixed 4 sensor-categories, and not a model
  estimate. Weights are engineer-supplied config (TODO) (FR-2).
- **Guardrail failure mode:** on a numeric-provenance tripwire, **regenerate the explanation
  once**; if it still cites an untraceable number, **fail-closed** to `PENDING_HUMAN_REVIEW`
  with the score withheld (FR-7).
- **Degraded vs. withhold:** emit a scored degraded assessment **only above a configured
  coverage floor** (min fraction of the bridge's mapped calcs that RAN, + standard present);
  below it, **withhold the score and route to human review** (FR-6). Floor is config (TODO).
- **Standards source:** **deferred to `plan.md`**; the spec requires only that the standard's
  **value + version is pinned and recorded** at decision time (FR-10).
- **Critical review mechanism:** this agent **only emits** the `PENDING_HUMAN_REVIEW` mark +
  explanation; the human-review action and the cleared→`FINAL` transition are a **separate
  concern, out of scope here** (FR-11, Out of Scope).
- **Audit shape:** the spec **fixes the structured record's fields + verbatim explanation + the
  always-on trace** as behaviour; **where** the row/traces are stored is a `plan.md` decision
  (FR-9).
- **Confidence:** a **deterministic data-completeness measure that annotates** the assessment
  and gates the degraded/withhold decision (FR-6) but **does not alter the score**; the exact
  completeness formula is config/plan detail (FR-6a).

---

## Core Concepts

- **Score and explanation are one deliverable, never separable.** Per Principle I, "a risk
  score or alert without its WHY is a defect." This agent must emit both or neither; a bare
  number is an invalid output.

- **The score is computed deterministically; the model EXPLAINS and contextualises it.** The
  numeric 0–100 score comes from the documented weighted formula (`math-analysis`), not from
  the model's free estimation. The model's job is the **judgment and narrative**: interpreting
  compound/conflicting signals, weighing them against standards, and writing the defensible
  WHY. The model never invents the arithmetic (research §4; Principle IV — deterministic where
  deterministic is possible).

- **Every number in the explanation must trace to a real input.** Each value the narrative
  cites — a risk contribution, an RMS figure, a deflection ratio, a standard's limit — must
  correspond to a value actually returned by a data source this run. An invented number in a
  government report is the system's worst failure mode (research §4; Principle I/VI).

- **Recommendation, not action.** The agent may output "Critical — recommend closure." That is
  a recommendation and emitting it is safe. It does **not** dispatch alerts, change signage, or
  gate anything; the Alert Agent owns the human-approval chokepoint on the real-world action
  (research §2; Principle I).

- **Three read-only data sources, fetched not assumed.** The agent obtains its inputs through
  three distinct read-only retrievals — calculation results, historical baseline, engineering
  standard — and reasons over what it actually retrieved. It does not fabricate a missing input
  (Principle III modular contracts; research §1).

- **Severity bands are fixed configuration.** The 0–100 → band mapping (Safe / Watch / Warning
  / Critical) is the `math-analysis` table, held as configuration, not invented per-run.

---

## What this agent receives (input contract)

Per assessment (one bridge / structural scope, at one point in time):

| Input | Source | Meaning |
|---|---|---|
| **Calculation results** | SA `analysis_results` | The current RAN results for the scope: RMS values, FFT peaks, deflection/threshold ratios + pass/fail, each with its `outcome` (`RAN \| SKIPPED \| ERROR`), `reason_code` when skipped, flags (`interpolated_input`, `clock_drift`, `rate_mismatch`, `abnormal_quiet`), and `source_validated_ids` provenance. |
| **Historical baseline / comparison** | store (sensor-comparison data) | Rolling baselines and prior assessments for the same scope — to judge *trend* (degrading vs. stable) and *deviation from normal*, not just absolute current values. |
| **Engineering standard** | standards lookup (IRC / AASHTO / Eurocode, `structural-research`) | The applicable design limits / thresholds / pre-failure signatures for this bridge type, pinned at decision time. |
| **Assessment scope + context** | trigger | Which bridge / structure, which time point, and the bridge type (drives which standard applies). |

The agent **reads** these; it never mutates upstream records. It does **not** re-run
calculations, re-validate sensor data, or re-derive the SA's facts (Principle III — it trusts
its upstream contracts).

---

## What this agent emits (output contract)

One **risk assessment** record per run, carrying **all** of:

- **`risk_score`** — integer 0–100 (the deterministic result: each SA result's value/limit
  ratio normalised to 0–100, weighted, and combined — FR-2). Withheld when below the coverage
  floor (FR-6).
- **`severity`** — one band: `SAFE (0–30) | WATCH (31–60) | WARNING (61–80) | CRITICAL (81–100)`
  (`math-analysis` bands; a closed set).
- **`recommendation`** — the plain-language recommended posture (e.g. routine monitoring →
  recommend closure), aligned to the band. A recommendation, never an action.
- **`explanation`** — the written WHY: the contributing factors, their weights, the standards
  compared against, trend context, and conflicts/uncertainties. This is a first-class safety
  output, logged verbatim.
- **`contributing_factors`** — the structured list the score was built from (each factor, its
  input value, its source ID, its weight/contribution) — the machine-checkable backing for the
  narrative.
- **`provenance`** — the input IDs consulted (`analysis_results` IDs, baseline reference,
  standard + version), the model + version, and the trace ID (FR-9).
- **`confidence` / `data_completeness`** — how much of the intended input was actually present
  (drives a degraded-assessment path when inputs are missing — FR-6).
- **`review_status`** — a closed-set flag on the assessment's finality: `FINAL` (may be
  consumed as-is downstream) or `PENDING_HUMAN_REVIEW` (must be reviewed before any downstream
  agent treats it as final). **Every `CRITICAL`-band assessment is emitted
  `PENDING_HUMAN_REVIEW`** (FR-11).

---

## User Scenarios

- **All inputs healthy — a confident scored assessment.** Current calc results, a usable
  baseline, and the matching standard are all retrieved. The agent computes the score, maps it
  to a band, and writes an explanation citing the actual contributing numbers and how they
  compare to the standard. Score + explanation emitted together.

- **Compound / conflicting signals — the judgment case.** One calc shows a confirmed vibration
  change while a deflection ratio sits just under its limit and the trend is mildly degrading.
  No single rule decides this. The agent weighs the combination, produces a score, and the
  explanation states explicitly *which* factors pulled the score up or down and how it resolved
  the conflict.

- **Critical — recommend closure, marked NOT final.** The combined evidence crosses into the
  Critical band. The agent emits "Critical — recommend closure" with a full explanation **and
  stamps the assessment `review_status = PENDING_HUMAN_REVIEW`**. It does **not** alert anyone
  or gate anything — but the not-final mark means no downstream agent (the Alert Agent
  included) may treat this Critical verdict as settled until a human has reviewed it. The
  recommendation flows onward carrying that pending-review state; a human engineer reviews it,
  and any real-world action is separately approved at the Alert Agent's gate.

- **A cited number wouldn't trace to a real input — output rejected.** The drafted explanation
  references a value that does not match any retrieved calc/baseline/standard result. The
  output guardrail tripwires; the assessment is **not** emitted as-is (it is regenerated or
  fails to a safe "needs human review" state) — an unverifiable number never reaches a report
  (FR-7).

- **Missing / degraded input — an honest degraded assessment, never a guess.** The standards
  lookup is unavailable, or the calc results for the scope are mostly `SKIPPED`/`ERROR`/absent.
  The agent does **not** invent the missing input or emit a falsely-confident score. It emits a
  **degraded** assessment that states what was missing and lowers/flags confidence accordingly
  — or withholds a score and routes to human review if too little is present to judge safely
  (FR-6).

- **Stale / superseded inputs — assess current facts only.** The SA may have superseded a
  result (late-arrival recompute). The agent consumes only **current** results and records
  which input versions it used, so the assessment is reproducible against exactly those inputs
  (FR-9).

---

## Functional Requirements

A build that ignores any of these should **visibly fail** a corresponding test.

- **FR-1 — Score and explanation are emitted together or not at all.** Every emitted assessment
  carries **both** a `risk_score` (+ `severity`) **and** a written `explanation`. A score with
  no explanation, or an explanation with no score, is an invalid output and must be rejected. A
  build that can emit a bare number fails. *(Principle I.)*

- **FR-2 — The score is computed deterministically; the model does not invent it.** The 0–100
  value is produced deterministically by **normalising each SA result's value/limit ratio to
  0–100, weighting each, and combining** (not the README's fixed sensor-categories, and not a
  model estimate). The per-factor weights are **engineer-supplied configuration** (TODO
  sentinels until supplied — do not invent safety weights). The model contributes the judgment
  framing and narrative, **not** the arithmetic. A build where the score is the model's
  free-form numeric guess (not the deterministic computation) fails. *(Principle IV; research
  §3–4.)*

- **FR-3 — Three read-only data sources, each a distinct retrieval.** The agent obtains
  calculation results, historical baseline, and the applicable engineering standard as three
  separate read-only fetches, and reasons only over what it retrieved. It does not mutate any
  upstream record and does not fabricate an input it failed to retrieve. A build that writes
  upstream, or proceeds on an assumed-but-unfetched input, fails. *(Principle III; research §1.)*

- **FR-3a — One whole-bridge assessment per SA-cycle-complete.** The agent runs **once per
  bridge** each time the Structural Analysis Agent completes a cycle for that bridge; **one
  assessment = the whole bridge** at that moment, fusing **all** of that bridge's sensors'
  current calc results. It is not per-sensor and not on a wall-clock schedule. A build that
  emits a per-sensor risk score, or that re-runs on an unrelated cadence, fails. *(Settled in
  interview; bounds the frontier-model cost envelope — research §3.)*

- **FR-4 — Severity band from a fixed mapping.** The score maps to exactly one of `SAFE | WATCH
  | WARNING | CRITICAL` via the fixed `math-analysis` band table (config, not per-run
  invention). A build using ad-hoc or model-chosen band boundaries fails.

- **FR-5 — Emits recommendations only; takes and gates no real-world action.** The agent may
  output any severity including "Critical — recommend closure," but it **never** dispatches
  alerts/notifications, changes signage, or applies `needs_approval` to its own output — it has
  no real-world action to gate. The human-approval gate lives downstream on the Alert Agent's
  dispatch. A build where this agent triggers or blocks a physical action fails. *(Principle I;
  research §2.)*

- **FR-6 — Missing/degraded input never becomes a confident guess; coverage floor gates
  scoring.** The agent emits a **scored (degraded) assessment only when coverage is at or above
  a configured floor** — a minimum fraction of the bridge's mapped calculations that actually
  `RAN`, **and** the applicable standard present. Above the floor it scores, names any gaps, and
  reflects reduced `confidence`. **Below the floor** (a data source unavailable, or calc inputs
  largely `SKIPPED`/`ERROR`/absent), it **withholds the score and routes to human review**
  (`PENDING_HUMAN_REVIEW`, score withheld) — it never invents a missing input, never emits a
  falsely-confident score on a near-blind bridge, and never crashes on incomplete input. The
  coverage floor is **configuration** (TODO sentinel until supplied). A build that scores below
  the floor, fabricates a missing standard/value, or crashes on partial input, fails. *(Settled
  in interview; Principle IV "always return a status"; Principle I.)*

- **FR-6a — Confidence is deterministic, annotation-only, and does not move the score.**
  `confidence` / `data_completeness` is a **deterministic** measure of how much expected input
  was present (it gates the FR-6 degraded/withhold decision and annotates the assessment) but it
  **does not alter the `risk_score`** — the score stays a pure function of the present factors,
  preserving FR-2's determinism and FR-10's reproducibility. The exact completeness formula is
  config/`plan.md` detail. A build where low completeness silently discounts the numeric score
  fails. *(Settled in interview.)*

- **FR-7 — Numeric-provenance output guardrail (anti-hallucination), regenerate-once then
  fail-closed.** Before an assessment is emitted, **every numeric claim in the explanation** must
  be verified to match a value actually returned by one of the three data sources this run
  (checked against source IDs). A number with no matching retrieved value **tripwires** the
  guardrail: the agent **regenerates the explanation once** (same inputs); if it still cites an
  untraceable number, the assessment **fails closed** to `PENDING_HUMAN_REVIEW` with the
  **score withheld** — it is **never** emitted with the unverifiable number. A build that emits
  an explanation citing a number absent from its inputs, or that retries unboundedly instead of
  failing closed after one regeneration, fails. *(Settled in interview; mandated requirement #2;
  Principle I "the WHY is part of the output"; VI; research §4.)*

- **FR-8 — Every assessment is structured, never crashes, and is independently testable.** For
  every run the agent returns a structured assessment (or a structured degraded/needs-review
  status) and never propagates an unhandled exception. The output contract is explicit and
  contract-bound (Principle III). A build that throws on bad/partial input instead of returning
  a status fails. *(Principle IV/V.)*

- **FR-9 — Dual audit: structured decision record + full model trace.** Each assessment writes
  a **structured audit record** (the system-of-record row): score, severity, recommendation,
  the input IDs consulted (`analysis_results` IDs + baseline reference + standard & version),
  the **model + version**, the **trace ID**, the `contributing_factors`, and the `explanation`
  **verbatim** — "not optional, not sampled, not disabled in production." Separately, the full
  model run (prompt + response + each tool call/result) is **traced** from the first run, no
  exceptions. The structured record alone must answer *what was decided, when, on the basis of
  what data*. **This spec fixes the record's fields + verbatim explanation + always-on tracing
  as behaviour**; **where** the structured row and the traces are stored is a `plan.md` decision.
  A build that logs a score without its inputs, model version, and verbatim explanation fails.
  *(Settled in interview; Principles VI, VII; research §5.)*

- **FR-10 — Reproducible against pinned inputs.** The standard's value and the calc/baseline
  inputs used are **pinned at decision time** (the standard's **value + version** recorded; calc
  inputs current-only by ID), so the same assessment can be reconstructed from the recorded
  input IDs even if a standard is later revised or a calc result is later superseded. **The
  standards *source* (curated local store vs. live retrieval vs. MCP) is deferred to `plan.md`**;
  this spec requires only that whatever the source, the value+version is pinned and recorded. A
  build whose assessment cannot be reproduced from its recorded inputs fails. *(Settled in
  interview; Principle VI; research §5; mirrors SA's config-version discipline.)*

- **FR-11 — `CRITICAL` outputs are marked NOT final until human-reviewed.** Every assessment
  carries a `review_status` of `FINAL` or `PENDING_HUMAN_REVIEW`, and **every `CRITICAL`-band
  assessment MUST be emitted `PENDING_HUMAN_REVIEW`**. This mark is part of the output contract
  (Principle III): a downstream consumer — **including the Alert Agent** — MUST NOT treat a
  `PENDING_HUMAN_REVIEW` assessment as a final, actionable verdict until a human has reviewed
  it. This is distinct from, and in addition to, the Alert Agent's `needs_approval` gate on the
  physical action (FR-5): FR-11 governs *the finality of the recommendation itself*, FR-5
  governs *acting on it*. **This agent's responsibility ends at emitting the
  `PENDING_HUMAN_REVIEW` mark + explanation**; the human-review action, who clears it, and the
  cleared→`FINAL` transition are a **separate concern, out of scope here** (a downstream
  human-review workflow). A build that emits a `CRITICAL` assessment marked `FINAL`, omits the
  `review_status` flag, or lets a downstream agent consume a Critical verdict as settled without
  the review step, fails. *(Mandated requirement #3; settled in interview; Principle I — the
  human stays in the loop on the gravest verdict, not merely on the final button-press.)*

---

## Edge Cases & Rules

- **Conflicting factors (e.g. high vibration but in-limit deflection).** Not an error — the
  judgment case. The agent produces a single reconciled score and the explanation states which
  factors pulled which way and how the conflict was resolved (the reason this is an LLM agent,
  not a rule).

- **Input mostly `SKIPPED`/`ERROR` from the SA.** Treated as missing data (FR-6): degraded
  assessment with named gaps and reduced confidence, or human-review routing — never a
  confident score on near-empty inputs.

- **`clock_drift` / `interpolated_input` / `rate_mismatch` flags on the SA results.** The agent
  must **carry these caveats into its reasoning and explanation** (a frequency-based factor
  resting on a drifted block is less trustworthy), not silently treat flagged inputs as clean.

- **Standard unavailable or ambiguous for the bridge type.** The agent does not guess a limit;
  it flags the missing/ambiguous standard in the degraded path (FR-6) and the explanation says
  the comparison could not be made.

- **A number in the draft explanation doesn't match any input.** Guardrail tripwire (FR-7) —
  regenerate **once**, then fail closed to `PENDING_HUMAN_REVIEW` with the score withheld; never
  emit the unverifiable number.

- **Borderline score at a band boundary.** The band comes from the fixed mapping (FR-4); the
  explanation must surface that the score is near a boundary so a human reads it with that
  context — but the agent does not nudge the number to change the band.

- **Critical recommendation.** Emitted freely (FR-5) but stamped `PENDING_HUMAN_REVIEW`
  (FR-11); routed to the Alert Agent; this agent neither alerts nor gates. No downstream agent
  treats it as final until human-reviewed, and the human approves any action downstream
  (Principle I).

- **Repeated / re-triggered assessment for the same scope+inputs.** Should be reproducible
  (FR-10): the same pinned inputs yield a consistent assessment; a new assessment supersedes
  rather than silently overwriting the prior record (auditability).

---

## Out of Scope

- **Taking or gating any real-world action** — dispatching alerts/notifications, changing
  signage, executing a closure, or applying the human-approval gate: the **Alert Agent** owns
  the `needs_approval` dispatch chokepoint (Principle I; research §2). This agent only
  *recommends*.
- **Running or re-running engineering calculations** (FFT, RMS, deflection, fatigue, modal) —
  the **Structural Analysis Agent's** job. This agent consumes calc *results*, never computes.
- **Validating or cleaning sensor data** — the **Data Collection Agent's** job. This agent
  trusts the validated/analysed inputs it is given.
- **Authoring the formatted PDF/government report or charts** — `pdf-report` / `visual-output`
  skills, downstream. This agent produces the score + explanation that those consume.
- **Maintaining the engineering-standards corpus** — it *looks up* standards; curating IRC/
  AASHTO/Eurocode content is a separate concern.
- **Inventing the weighted-score formula or band thresholds** — those are `math-analysis`
  configuration; this spec consumes them, it does not define them.
- **The human-review-clearing workflow** — this agent only *emits* the `PENDING_HUMAN_REVIEW`
  mark (FR-11). **Who** clears it, the review UI/queue, the authorisation to clear, and the
  cleared→`FINAL` state transition are a separate downstream concern. This spec defines only the
  flag's emission and that no downstream consumer treats a marked verdict as final until it is
  cleared.

This agent only **judges and explains** — it turns trustworthy numbers into an accountable,
human-readable risk verdict, and stops at the recommendation.

---

## Acceptance Criteria

Each is testable against a scenario above.

- **AC-1.** Every emitted assessment contains **both** a 0–100 `risk_score` (+ a `severity`
  band) **and** a written `explanation`; an attempt to emit a bare score is rejected as a
  defect. *(score+WHY inseparable)*
- **AC-2.** The `risk_score` equals the **deterministic weighted-formula** result over the
  retrieved inputs — not a model free-estimate; given identical pinned inputs the score is
  reproducible. *(deterministic score)*
- **AC-3.** The agent retrieves calculation results, historical baseline, and the engineering
  standard as **three distinct read-only fetches**, reasons only over what it retrieved, and
  **mutates no upstream record**. *(three tools, read-only)*
- **AC-4.** The score maps to exactly one of `SAFE | WATCH | WARNING | CRITICAL` via the fixed
  band table. *(severity mapping)*
- **AC-5.** A Critical assessment is **emitted as a recommendation** and the agent **does not**
  alert, change signage, or gate any action — the assessment flows to the Alert Agent for
  human approval. *(recommendation-only; gate downstream)*
- **AC-6.** With a missing data source or largely `SKIPPED`/`ERROR` calc inputs, the agent
  emits a **degraded** assessment naming the gap with reduced confidence (or routes to human
  review) — never a fabricated input and never a falsely-confident score, and never a crash.
  *(degraded path)*
- **AC-7.** An explanation drafted with a numeric claim that matches **no** retrieved input
  **tripwires the output guardrail** and is **not emitted** as-is: the agent regenerates **once**,
  and if the second draft still cites an untraceable number it **fails closed** to
  `PENDING_HUMAN_REVIEW` with the score withheld. Conversely, an explanation whose every number
  traces to a real input passes. *(anti-hallucination guardrail)*
- **AC-8.** SA result flags (`clock_drift`, `interpolated_input`, `rate_mismatch`,
  `abnormal_quiet`) present on an input are **reflected as caveats** in the reasoning/
  explanation, not silently dropped. *(caveat propagation)*
- **AC-9.** Each assessment writes a **structured audit record** with score, severity,
  recommendation, the consulted input IDs, model + version, trace ID, contributing factors, and
  the **verbatim explanation**; and the full model run is **traced**. The structured record
  alone answers *what/when/on-what-data*. *(dual audit)*
- **AC-10.** An assessment is **reproducible from its recorded input IDs** even after a standard
  is revised or a calc result is superseded (inputs pinned at decision time); a re-assessment
  **supersedes** rather than overwrites. *(reproducibility)*
- **AC-11.** The agent **returns a structured status on malformed/partial input and never
  throws** (the four-scenario constitution test: normal / missing / corrupt / offline inputs).
  *(never-crash; Principle V)*
- **AC-12.** A `CRITICAL`-band assessment is emitted with `review_status =
  PENDING_HUMAN_REVIEW`; a non-Critical assessment carries an explicit `review_status` too. A
  test asserting a downstream consumer **rejects/holds** a `PENDING_HUMAN_REVIEW` Critical
  verdict as non-final (rather than acting on it) passes; emitting a `CRITICAL` marked `FINAL`,
  or omitting the flag, fails. *(Critical not-final until human-reviewed — mandated #3)*

---

## Open Items

The clarification interview settled the agent's *behaviour* (trigger cadence = one whole-bridge
assessment per SA-cycle-complete, FR-3a; deterministic ratio-normalised score the model explains,
FR-2; guardrail = regenerate-once-then-fail-closed, FR-7; coverage floor gates scoring, FR-6;
confidence is annotation-only, FR-6a; Critical → `PENDING_HUMAN_REVIEW`, FR-11). What remains is
**not** behavioural ambiguity — it is config values an engineer must supply, and downstream
contracts to pin at design/plan time. None of these should be guessed in a safety-critical system.

**Config TODOs (a structural engineer supplies; placeholders until then — do not invent):**
- **Score weights + per-factor normalisation:** the weights combining each SA result's
  value/limit ratio into the 0–100 score (`math-analysis` config, FR-2).
- **Coverage floor value:** the minimum fraction of expected SA results that must be present
  (`RAN`, not `SKIPPED`/`ERROR`) before a score is emitted vs. withheld to `PENDING_HUMAN_REVIEW`
  (FR-6).
- **Completeness/confidence formula:** how `data_completeness` / `confidence` is computed from
  present-vs-expected inputs and input flags (FR-6a — annotation only, does not move the score).
- **Band thresholds:** the score cut-points for `SAFE | WATCH | WARNING | CRITICAL` (FR-4).
- **Guardrail match tolerance:** exact-match vs. rounding tolerance when binding a narrative
  number to a tool result (FR-7) — the *failure mode* is settled; the numeric tolerance is config.

**Deferred to plan.md (design decisions, not spec behaviour):**
- **Standards source + pinning mechanism:** whether `get_engineering_standard` reads a curated
  local store or live retrieval, and the concrete mechanism for pinning a standard's value/version
  at decision time (FR-10 requires reproducibility; *how* is plan-level).
- **Historical-baseline contract shape:** the exact schema/window of the `sensor-comparison`
  baseline input this agent reads.
- **Alert-Agent chokepoint confirmation:** verify the Alert Agent is the **single**
  un-bypassable approval point for real-world actions, so FR-5's "gate lives downstream" holds in
  code (Principle I; research §2).
- **Trace retention / PII:** retention policy and storage location for full prompt+response
  traces in a government context, relative to the Supabase structured record (research §5).
