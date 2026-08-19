# Risk Reasoning Agent — Technical Plan

**Status:** Draft for review (built on the clarified `spec.md` + research-agent-003)
**Date:** 2026-06-29
**Spec:** `specs/risk-reasoning-agent/spec.md` (behaviour-only, 13 FR / 12 AC, 3 mandated reqs)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.0.0** (agree on stack)
**Research:** `specs/risk-reasoning-agent/research-agent-003.md`;
prior art: `specs/structural-analysis-agent/plan.md` and `specs/data-collection-agent/plan.md`
(the two deterministic-service decisions this agent is the deliberate *counterpoint* to).

> Planning under the **CLAUDE.md / constitution v2.0.0 stack** (OpenAI Agents SDK, MCP,
> Supabase/Postgres, n8n glue). This is **Agent 003**, downstream of the Structural Analysis
> Agent (SA, Agent 002), which is downstream of the Data Collection Agent (DCA, Agent 001).
>
> **Settled in spec + interview (baked in below):** one whole-bridge assessment per
> SA-cycle-complete; deterministic ratio-normalised 0–100 score the model *explains* (never
> estimates); numeric-provenance output guardrail = regenerate-once-then-fail-closed; coverage
> floor gates scoring vs. withhold; confidence is annotation-only; `CRITICAL` →
> `PENDING_HUMAN_REVIEW`, not final until human-reviewed; dual audit (structured row + verbatim
> explanation + always-on trace). Three mandated requirements: score+WHY inseparable (FR-1),
> every narrative number traceable (FR-7), Critical not-final-until-reviewed (FR-11).

---

## 1. Is the Risk Reasoning Agent an Agent, or a deterministic service?

**Recommendation: it IS a model-calling OpenAI Agents SDK Agent with a frontier-tier model —
the one such agent in BridgeGuard.** This is the deliberate inverse of the DCA and SA decisions,
reached from this agent's own facts (research §framing; constitution Principle IV).

Rationale (Principle IV reserves the LLM for *exactly* this; research §framing, §3):
- **The work is compound, ambiguous judgment.** Fusing heterogeneous inputs (vibration spectra,
  deflection ratios, trend vs. baseline, a standard's limits) into a single defensible verdict
  with a human-facing narrative is the open-ended interpretation Principle IV reserves the LLM
  for — the conflicting-factors case (spec Edge Cases) has no rule-expressible answer the way
  SA's calc-selection did.
- **But the *number* is still deterministic.** The 0–100 score is a pure weighted function of the
  retrieved ratios (FR-2), computed in code, not estimated by the model. The model's job is the
  **WHY** — interpret, contextualise against the standard, write the defensible explanation. This
  keeps arithmetic out of the model (the SA/DCA safety property) while using the model only where
  it is genuinely needed (research §4; Principle IV).
- **So this agent is a model loop wrapped around a deterministic scorer**, not a free-estimating
  model and not a pure service.

### Agent shape (the three questions the spec left to plan)

- **Three read-only `@function_tools`, not one mega-tool, not a handoff target** (research §1):
  - `get_calculation_results(bridge_id, cycle_id)` → SA `analysis_results` for the scope.
  - `get_historical_baseline(bridge_id, window)` → rolling baseline / prior assessments.
  - `get_engineering_standard(bridge_type)` → applicable design limits, pinned by value+version.
  Each is independently traceable and mockable (Principle III); control returns to the reasoner
  after each fetch (textbook tool shape, not a control transfer). **SA does NOT hand off to this
  agent** — SA is a deterministic service with no model loop to transfer; the edge is
  `SA writes analysis_results → n8n trigger → this agent reads` (research §1).
- **The deterministic scorer is plain code, NOT a tool the model can skew.** The score is
  computed from the retrieved ratios by an in-process pure function (`score_bridge(...)`), and
  the model receives the score as a fixed fact to explain. The model cannot change the number;
  it can only refuse/withhold (degraded path) or explain it.
- **The numeric-provenance check is an SDK output guardrail** (FR-7; research §4) — see §4.

### `needs_approval`?

**No `needs_approval` on this agent** (research §2; Principle I). A "Critical — recommend
closure" output is *still a recommendation*; emitting it harms nothing and must not be blocked.
The human-in-the-loop gate lives **downstream on the Alert Agent's dispatch tool** (the thing
that notifies authorities / changes signage). This agent's contribution to Principle I is the
**`PENDING_HUMAN_REVIEW` mark on Critical** (FR-11) — a *flag*, not an approval gate — which
stops a downstream agent treating a grave verdict as final on this agent's say-so. *(Open Item:
confirm the Alert Agent is the single un-bypassable approval chokepoint.)*

### Tracing (Principle VII)

**SDK tracing ON from the first run, no exceptions** — this is the first agent where there *is*
a model run to trace. The full prompt, model response, and every tool call/result are the
forensic-replay layer. This is one half of the dual audit (§5); the other half is the structured
decision row.

---

## 2. Model tier — frontier, and why it's affordable here

**Frontier reasoning tier** (research §3; Principle IV "LLM budget discipline"):
- The output is a **safety-critical, government-facing, regulator-defensible** judgment. Mid-tier
  risks subtle misweighting of compound risk and weaker standards-reasoning — unacceptable when
  lives and legal accountability are downstream.
- **Cost is bounded by cadence:** **one assessment per bridge per SA-cycle-complete** (FR-3a) —
  not per sensor, not per reading. Frontier spend is small in aggregate.
- **If cost ever bites:** keep frontier for the scoring rationale + narrative; push mechanical
  sub-steps to deterministic code (already true of the scorer). **Never** downgrade the judgment
  itself. *(Exact model ID is a deployment config value, pinned and recorded per FR-9/FR-10.)*

---

## 3. Reading & writing the Supabase schema

**Key finding:** this agent **reads** the SA's `analysis_results` (proposed migration `0005…`
in the SA plan) + a baseline source + a standards source, and **writes one new table of its
own** (`risk_assessments`) plus an audit row. It mutates no upstream record (Principle II/III).

### 3a. What this agent READS

- **`analysis_results` (SA, current non-superseded rows for the bridge+cycle)** — the primary
  input. Consumes per result: `calculation`, `outcome` (`RAN | SKIPPED | ERROR`), `reason_code`,
  the `result` JSONB (RMS scalar / FFT peaks / threshold value+limit+ratio+pass-fail), the flags
  (`interpolated_input`, `clock_drift`, `rate_mismatch`, `abnormal_quiet`), and
  `source_validated_ids` (provenance chain back to validated → raw). `SKIPPED`/`ERROR` rows count
  against the **coverage floor** (FR-6); `RAN` rows feed the score (FR-2) and the guardrail's
  set of legitimate numbers (FR-7).
- **Historical baseline / comparison** — *(Open Item: exact source + shape.)* Rolling baselines
  / prior `risk_assessments` for the same bridge, to judge **trend** (degrading vs. stable), not
  just absolute current values. Read-only.
- **Engineering standard** — *(Open Item: curated local store vs. live retrieval.)* The
  applicable IRC/AASHTO/Eurocode limits for the bridge type, **pinned by value + version at
  decision time** so an assessment stays reproducible after the standard is revised (FR-10).

### 3b. What this agent WRITES (one new table + audit, append-only)

A new migration set (proposed `0006…`), mirroring the **append-+-supersede, never in-place**
discipline proven in `validated_readings` / `analysis_results`:

- **`risk_assessments`** — one row per whole-bridge assessment. Columns (behaviour → schema):
  - `bridge_id`, `cycle_id` (the SA cycle this assessed), `assessed_at`;
  - `risk_score` (0–100; **NULL when withheld** in the degraded/guardrail-fail path — FR-6/FR-7);
  - `severity` (enum **closed set**: `SAFE | WATCH | WARNING | CRITICAL`; NULL when withheld);
  - `recommendation` (text);
  - `explanation` (text, **verbatim** — Principle I makes the WHY part of the deliverable, FR-9);
  - `contributing_factors` (JSONB — per-factor: which SA result, its ratio, its weight, direction
    it pushed; this is also the guardrail's traceable-number set);
  - `confidence` / `data_completeness` (annotation only — does NOT move the score, FR-6a);
  - **`review_status`** (enum: `FINAL | PENDING_HUMAN_REVIEW`; **always `PENDING_HUMAN_REVIEW`
    when `severity = CRITICAL`** or when score withheld — FR-11);
  - **provenance (FR-10 reproducibility):** `source_analysis_ids BIGINT[]`, `baseline_ref`,
    `standard_code` + `standard_version` (pinned), `score_weights_version` — the assessment must
    be re-derivable from these even after inputs are superseded/revised;
  - **audit:** `model_id`, `model_version`, `trace_id` (links to the SDK trace, §5);
  - **correction chain:** `superseded_by` + the same BEFORE-UPDATE guard / DELETE-block triggers
    as `validated_readings`, so a re-assessment **appends a new row and links the old** (FR-10 /
    AC-10), never an in-place edit.
- **Audit logging (dual — §5).** Recommend extending the DCA/SA `decision_log` `decision_kind`
  enum with `RISK_ASSESSMENT`, `RISK_WITHHELD`, `RISK_GUARDRAIL_FAIL`, reusing one
  reconstructable audit story across all three agents (consistent with the SA plan's choice).

### 3c. Score-withheld is a first-class row, not a missing row

Both the degraded path (FR-6, below coverage floor) and the guardrail fail-closed (FR-7) write a
**real `risk_assessments` row** with `risk_score = NULL`, `severity = NULL`, `review_status =
PENDING_HUMAN_REVIEW`, a populated `explanation` naming the gap, and the consulted IDs. Withholding
is an auditable decision, never silence (Principle VI; AC-6/AC-7).

---

## 4. Anti-hallucination: the numeric-provenance output guardrail (FR-7, mandate #2)

**An SDK output guardrail that rejects any numeric claim in the explanation not traceable to a
real retrieved value** — the highest-value safety control in this agent (research §4).

```
model drafts explanation
        │
        ▼
output guardrail: extract every number in the narrative →
        match each against the run's legitimate-number set
        (RAN analysis_results values + the deterministic score/factors + the pinned standard)
        │
   ┌────┴─────────────────────────┐
  all match                  ≥1 untraceable
   │                              │
 emit (FINAL or            regenerate explanation ONCE
 PENDING per FR-11)               │
                          ┌───────┴────────┐
                      now all match    still untraceable
                          │                  │
                        emit         FAIL CLOSED → write withheld row
                                     (score NULL, PENDING_HUMAN_REVIEW)
```

- **Legitimate-number set** = the values actually returned by the three tools this run, plus the
  deterministic score and its `contributing_factors` (which are themselves derived from those
  values). The score is computed in code (§1), so it is by construction traceable.
- **Match tolerance** is config *(Open Item: exact-match vs. rounding tolerance)* — but the
  *failure mode is settled*: regenerate once, then fail closed. Never emit an untraceable number.
- This operationalises Principle I ("a WHY citing a number that doesn't exist is *also* a defect")
  and is the test target of AC-7.

---

## 5. Audit & reproducibility (Principle VI/VII, FR-9/FR-10)

**Two records, two roles** (research §5):
- **(a) Full SDK trace** — prompt, model response, each tool call/result. Forensic replay. On
  from the first run (VII). `trace_id` is stored on the `risk_assessments` row to link the two.
- **(b) Structured `risk_assessments` row + `decision_log` entry** — the permanent, queryable
  system-of-record: score, severity, recommendation, **verbatim explanation**, consulted input
  IDs, model+version, trace ID, contributing factors, `review_status`. The structured record
  **alone** answers *what / when / on-what-data* (AC-9).
- **Reproducibility (AC-10):** because inputs are pinned (`source_analysis_ids`, `baseline_ref`,
  `standard_code`+`version`, `score_weights_version`), an assessment is re-derivable even after a
  standard is revised or an SA result is superseded. A re-assessment supersedes; never overwrites.

*(Open Item: trace retention / PII policy + storage location for full prompt+response traces in a
government context, relative to the Supabase structured row.)*

---

## 6. How it's triggered (n8n, downstream of SA — per bridge, on SA-cycle-complete)

**Decision: downstream of SA, fired once per bridge after that bridge's SA cycle commits its
`analysis_results` — not co-scheduled, not in-process** (FR-3a; mirrors the DCA→SA edge).

```
… DCA cycle commits validated_readings
        │  n8n: on DCA-cycle-complete → SA service
        ▼
SA service writes analysis_results (append/supersede) + audit
        │  (SA cycle commits for a bridge)
        ▼
n8n: on SA-cycle-complete for bridge B → trigger Risk Reasoning Agent (passes bridge_id, cycle_id)
        ▼
Risk Reasoning Agent (model loop):
  1. get_calculation_results(B, cycle)  ─┐
  2. get_historical_baseline(B, window)  ├─ three read-only tool fetches (traced)
  3. get_engineering_standard(B.type)   ─┘
  4. coverage check (FR-6): below floor → write withheld row (PENDING_HUMAN_REVIEW); stop
  5. score_bridge(...) → deterministic 0–100 + severity band (FR-2/FR-4)  [plain code]
  6. model drafts explanation + contributing_factors over the retrieved facts + score
  7. output guardrail (FR-7): regenerate-once-then-fail-closed on any untraceable number
  8. severity == CRITICAL or withheld → review_status = PENDING_HUMAN_REVIEW (FR-11)
  9. write risk_assessments (append/supersede) + decision_log; trace_id linked
→ downstream (Alert Agent) reads risk_assessments; owns the needs_approval dispatch gate
```

**Why downstream, not the same cycle** (same reasoning as the DCA→SA edge):
- **Correctness:** reads *current, committed* `analysis_results` (non-superseded only); running
  inside the SA cycle would race SA's own writes.
- **Decoupling / re-runnability:** a separate trigger is independently retryable; idempotency on
  `(bridge_id, cycle_id)` among current rows makes an at-least-once n8n redelivery safe.

**Responsibility split (for review):**
- **n8n owns:** detecting SA-cycle-complete per bridge, invoking the agent with `(bridge_id,
  cycle_id)`, retrying the *trigger*. Glue, not logic.
- **The agent owns:** all three reads, the deterministic scoring, the model reasoning, the
  guardrail, all `risk_assessments` + audit writes, idempotency/supersession. It never writes
  SA's or the DCA's tables, and never dispatches a real-world action.

---

## Constitution Check

| Principle (CLAUDE.md / v2.0.0) | How this plan complies |
|---|---|
| I — Safety First / human signs off physical actions; score has a WHY | Takes no physical action; no `needs_approval` here (gate is on the Alert Agent's dispatch tool). Score + verbatim explanation are one inseparable deliverable (FR-1). `CRITICAL` → `PENDING_HUMAN_REVIEW`, not final until human-reviewed (FR-11). |
| II — Data Integrity: raw immutable, every number traceable | Reads (never mutates) SA/DCA tables; `risk_assessments` pins `source_analysis_ids` → analysis → validated → raw; append+supersede, DELETE blocked; numeric-provenance guardrail (FR-7). |
| III — Modularity: no agent calls another's internals | Reads SA's published `analysis_results` table via a tool; no handoff, no internal calls; SA doesn't hand off to it. |
| IV — Reliability Over Cleverness: deterministic where possible | Score is deterministic code; LLM used only for the genuinely ambiguous judgment + narrative; arithmetic kept out of the model. |
| V — Testability: 4-scenario | AC-11: returns structured status on normal / missing / corrupt / offline inputs, never throws. |
| VI — Auditability | Dual audit: structured `risk_assessments` row + verbatim explanation + `decision_log`; reproducible from pinned IDs. |
| VII — Tech Stack / trace from day one | OpenAI Agents SDK Agent, frontier model, three `@function_tools`, MCP-eligible tools, Supabase tables, n8n trigger; **SDK tracing on from first run**. |

---

## Open Items To Resolve Before Build

1. **Score weights + per-factor normalisation (config, do not guess):** the weights combining each
   SA result's value/limit ratio into the 0–100 score, and each factor's normalisation
   (`math-analysis` config). `score_weights_version` stamps them for reproducibility (FR-2/AC-10).
2. **Coverage-floor value + completeness formula (config, do not guess):** the minimum fraction of
   the bridge's expected `RAN` results (+ standard present) to emit a scored assessment vs.
   withhold; and how `data_completeness`/`confidence` is computed (annotation only — FR-6/FR-6a).
3. **Band thresholds (config):** the 0–100 cut-points for `SAFE | WATCH | WARNING | CRITICAL`
   (FR-4) — `math-analysis` table, held as versioned config.
4. **Guardrail match tolerance (config):** exact-match vs. rounding tolerance binding a narrative
   number to a retrieved value (FR-7) — failure mode (regenerate-once-then-fail-closed) is settled.
5. **Standards source + pinning mechanism (design):** `get_engineering_standard` = curated local
   store vs. live retrieval, and the concrete value+version pinning at decision time (FR-10).
6. **Historical-baseline contract shape (design):** the schema/window of the `sensor-comparison`
   baseline input this agent reads.
7. **`risk_assessments` schema sign-off:** the `contributing_factors` JSONB shape, the `severity`/
   `review_status` enums, the score-withheld NULL convention, and the `(bridge_id, cycle_id)`
   idempotency rule.
8. **Audit home:** extend `decision_log` (recommended) vs. a separate `risk_log`; and the
   `RISK_ASSESSMENT`/`RISK_WITHHELD`/`RISK_GUARDRAIL_FAIL` kinds.
9. **Model ID + tier pinning (deployment config):** the exact frontier model ID, recorded per
   assessment (`model_id`/`model_version`) for audit/reproducibility.
10. **Alert-Agent chokepoint confirmation (cross-agent):** verify the Alert Agent is the **single**
    un-bypassable `needs_approval` point for real-world actions, so FR-5's "gate lives downstream"
    holds in code (Principle I; research §2).
11. **Trace retention / PII (governance):** retention policy + storage location for full
    prompt+response traces in a government context, relative to the Supabase structured row.
12. **Human-review-clearing workflow is OUT OF SCOPE here (FR-11 / spec Out of Scope):** who clears
    `PENDING_HUMAN_REVIEW` and the cleared→`FINAL` transition is a separate downstream concern —
    named, not built in this agent.
