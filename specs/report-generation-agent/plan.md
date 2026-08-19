# Report Generation Agent — Technical Plan

**Status:** Draft for review (built on the clarified `spec.md` + research-agent-004)
**Date:** 2026-07-04
**Spec:** `specs/report-generation-agent/spec.md` (behaviour-only, 13 FR / 15 AC, assemble-only spine)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.1.0** (Neon/Postgres,
standard indexes only; SDK alias-import adapter; agree on stack)
**Research:** `specs/report-generation-agent/research-agent-004.md`;
prior art: `specs/data-collection-agent/plan.md` + `specs/structural-analysis-agent/plan.md` (the
two deterministic-service decisions this agent **follows**), and
`specs/risk-reasoning-agent/plan.md` (Agent 003 — the model-calling counterpoint this agent is
downstream of and deliberately *unlike*).

> Planning under the **CLAUDE.md / constitution v2.1.0 stack** (Neon/Postgres, standard Postgres
> indexes only — no TimescaleDB; n8n glue; SDK alias-imported through one adapter). This is
> **Agent 004**, downstream of the Risk Reasoning Agent (Agent 003), which is downstream of the
> Structural Analysis Agent (002) and the Data Collection Agent (001).
>
> **Settled in spec + interview (baked in below):** it **assembles, never re-decides** — every
> number and sentence is copied from finalized upstream output (FR-1); the risk explanation is
> **verbatim**, plus one fixed severity→headline lookup (FR-2); **deterministic templating, no
> model** (FR-3); read-by-identity, current-by-default, historical only when labelled (FR-4);
> **exact-match (0.0) fidelity gate**, fail-closed (FR-5); charts render facts / missing →
> section-marked-unavailable (FR-6); `CRITICAL`/`PENDING_HUMAN_REVIEW` → **render marked
> `NOT_FINAL`**, not held (FR-7); withheld assessment → **`RENDERED` marked `SCORE_WITHHELD`**
> (FR-8); append-only versioned artifacts (FR-9); idempotent per assessment version (FR-10);
> reproducible audit (FR-11); **async fire-and-notify, atomic, never crashes** (FR-12);
> **publication out of scope** — a downstream Publish/Alert agent owns dispatch + its
> `needs_approval` gate (FR-13).

---

## 1. Is the Report Generation Agent an Agent, or a deterministic service?

**Recommendation: it is a deterministic Python service — NOT an OpenAI Agents SDK Agent.** This is
the DCA/SA decision (Option A), not the Risk Agent's. Reached from this agent's own facts
(research §2; constitution Principle IV).

Rationale (Principle IV forbids the LLM where a rule/template suffices; research §2):
- **There is no ambiguous judgment left to make.** Every value the report prints has already been
  computed (DCA → SA), and the danger verdict + its written WHY have already been decided and
  audited by Agent 003 — which already passed its own numeric-provenance guardrail on that
  explanation. Filling a fixed template from those finalized rows is **mechanical**, not
  interpretive.
- **Using a model here would be a violation, not a nicety.** Principle IV: "using an LLM where a
  deterministic rule suffices is a violation and MUST be rejected in review." A model that
  re-worded the explanation or re-summarized the score would create a **new, ungoverned** statement
  that never passed any guardrail — precisely the failure FR-1/FR-2 exist to prevent.
- **So this agent is a pure deterministic renderer**, the same shape as the DCA and SA services:
  n8n invokes it, it reads finalized rows, it emits a structured status. No model loop, no
  frontier tier, no output guardrail-as-SDK-primitive (the fidelity gate is plain code, §4), no
  handoff.

### Service shape (the pieces the spec left to plan)

- **One entrypoint the trigger hits** — `run_report(scope_key)` (mirrors the DCA's `run_cycle`,
  the Risk service's `run_assessment`): validate the scope key → read finalized rows by identity →
  assemble → fidelity-gate → render (async) → persist artifact + audit → return a structured
  `ReportSummary`. It **never raises** (FR-12).
- **The render is plain library calls, in-process** (research §1): ReportLab builds the PDF;
  matplotlib(`Agg`) renders static chart images into buffers ReportLab embeds. **No sandbox
  (E2B/Cloudflare)** — this runs *our* code over *our* already-validated rows; the untrusted-code
  harness case does not arise (research §1). Concerns are mundane and handled in-process:
  controlled artifact path, capped page/row counts, atomic write.
- **The fidelity gate is a plain pure function, not an SDK guardrail** — there is no model output
  to guard; it verifies each assembled value against the finalized source rows in code (§4).

### SDK / packaging note (constitution v2.1.0)

This agent **calls no model, so it imports no SDK** — the `agents`-package collision the
constitution's alias-import rule addresses **does not arise here**. (The rule binds only agents
that construct an SDK `Agent`; this service does not.) The repo package stays `agents.report_generation`,
plain Python, exactly like `agents.data_collection` and `agents.structural_analysis`.

### `needs_approval`?

**No `needs_approval` anywhere on this agent** (FR-13; Principle I; research cross-cutting).
Rendering a document harms nothing — it is an artifact, like the Risk Agent emitting a
recommendation. The real-world action the constitution names ("report **publication**") is a
*downstream* concern: a separate **Publish/Alert agent** submits the report to an authority, and
**that** dispatch tool carries the `needs_approval` gate. This agent produces the document and
stops. *(Cross-agent Open Item: confirm the Publish/Alert agent is the single un-bypassable
dispatch chokepoint — same shape as the Risk plan's Alert-Agent confirmation.)*

### Tracing / audit (Principle VI/VII)

**There is no model run to SDK-trace** (Principle VII's "trace every *model-calling* run" is
satisfied vacuously — no model is called; the constitution explicitly says purely deterministic
steps satisfy auditability via the decision log instead). Auditability (VI) is met by the
structured `report_artifacts` row + a `decision_log` entry (§5) — the same way the DCA/SA
deterministic services audit.

---

## 2. No model tier — and why that is the right call

Unlike Agent 003 (frontier tier, justified once for compound judgment), this agent has **no model
and therefore no tier decision**. The "LLM budget discipline" (Principle IV) resolves to **zero
spend**: the cheapest, most predictable, most reproducible renderer is deterministic code, and it
is also the *only* one that cannot drift from the finalized record. The single place a reader might
expect generated prose — the executive summary — is instead a **verbatim copy** of the Risk
Agent's explanation plus a **fixed severity→headline lookup** (config, not a model; FR-2). No part
of the report is model-authored.

---

## 3. Reading the finalized rows & writing the artifact record (Neon/Postgres)

**Key finding:** this agent **reads** the finalized `risk_assessments` row (0006) and, through its
pinned provenance, the SA `analysis_results` and DCA `validated_readings` it cites — and **writes
one new table of its own** (`report_artifacts`) plus an audit row. It mutates no upstream record
(Principle II/III).

### 3a. What this agent READS (by identity, current-by-default, exact-match bound)

- **`risk_assessments` (0006), the assessment the scope key resolves to** — the primary input. It
  supplies the printed verdict directly: `risk_score`, `severity`, `recommendation`, the
  **verbatim `explanation`**, `contributing_factors` (JSONB), `confidence`/`data_completeness`,
  `review_status`, and the pinned provenance (`source_analysis_ids`, `baseline_ref`,
  `standard_code`+`standard_version`, `score_weights_version`, `model_id`+`model_version`,
  `trace_id`). By default the agent reads the **current** row (the 0006 partial-unique index gives
  exactly one per `(bridge_id, cycle_id)`); a **historical reprint** reads a *superseded* row **by
  id** and stamps the report `HISTORICAL` (FR-4).
- **`analysis_results` (SA, 0005 — via `source_analysis_ids`)** — the calc results (RMS/FFT/
  threshold values, ratios, pass/fail-vs-limit) for the sensor tables and math-results section.
  Read-only; current versions only (recorded).
- **`validated_readings` (DCA, 0002 — via the analysis rows' `source_validated_ids`)** — recent
  readings for the time-series tables/charts and the raw-data appendix. Read-only; **appendix depth
  bounded** by config (Open Item), so a huge history cannot produce an unusable document.
- The **engineering standard** is read **from the assessment's pinned `standard_code`+`version`**,
  not re-fetched live — the report shows what the verdict was compared against, reproducibly (FR-11).

Every value assembled from these is bound to its source **exactly (tolerance 0.0)** before it may
print (FR-5, §4).

### 3b. What this agent WRITES (one new table + audit, append-only)

A new migration (proposed **`0008_report_artifacts.sql`** — 0006/0007 are the Risk Agent's;
`0005` is SA's still-unbuilt `analysis_results`), mirroring the **append-+-supersede, never
in-place** discipline proven in `validated_readings` / `risk_assessments`:

- **`report_artifacts`** — one row per rendered report. Columns (behaviour → schema):
  - `bridge_id`, `cycle_id`, `assessment_id` + `assessment_version` (**which** assessment row,
    and its version, was rendered — FR-4/FR-10/FR-11);
  - `rendered_at`;
  - `outcome` (enum **closed set**: `RENDERED | WITHHELD | ERROR` — FR-12);
  - `marks` (the `RENDERED` document marks that apply: `NOT_FINAL | SCORE_WITHHELD | HISTORICAL |
    SECTION_UNAVAILABLE`; empty ⇒ a clean `FINAL` report — spec Outcome Vocabulary). Modelled as a
    small enum array or a set of booleans (schema sign-off, Open Item);
  - `withheld_reason` (enum, NULL unless `outcome = WITHHELD`: `ASSESSMENT_NOT_FOUND |
    PROVENANCE_MISMATCH` — the only two no-document cases);
  - **the artifact itself** — `artifact_ref` (a pointer to the stored PDF bytes) **or** inline
    bytes; **where** the PDF lives (Neon `bytea` vs. object storage + URL) is a design Open Item
    (§ below). The append-only/versioning guarantee holds regardless of store;
  - **provenance / reproducibility (FR-11):** `source_analysis_ids BIGINT[]` (the versions
    rendered), `standard_code`+`standard_version` (as pinned by the assessment), `template_version`
    (which report template/letterhead config produced this document);
  - **correction chain:** `superseded_by` + the same BEFORE-UPDATE guard / DELETE-block triggers as
    `risk_assessments`, so a **re-render appends a new row and links the old** (FR-9), never an
    in-place edit; DELETE blocked (a report a regulator may have relied on is permanent, Principle
    VI).
- **Idempotency (FR-10):** a partial unique index on `(assessment_id, assessment_version)` among
  **current** (non-superseded) rows — a redelivered trigger for an already-rendered version is a
  no-op; a render against a newer assessment version supersedes the prior report. (Standard
  Postgres partial unique index — no extension needed, consistent with v2.1.0.)

### 3c. A withheld/degraded report is a first-class RENDERED row, not a missing one

Per the interview: a **withheld-score** assessment still produces a `RENDERED` row marked
`SCORE_WITHHELD`+`NOT_FINAL` (FR-8); a **missing-section** report is `RENDERED` marked
`SECTION_UNAVAILABLE` (FR-6); a **not-final** verdict is `RENDERED` marked `NOT_FINAL` (FR-7); a
**historical** reprint is `RENDERED` marked `HISTORICAL` (FR-4). The **only** no-document outcomes
are `WITHHELD/ASSESSMENT_NOT_FOUND` (nothing to render) and `WITHHELD/PROVENANCE_MISMATCH` (the
fidelity gate — §4). Every readable assessment yields an auditable document (Principle VI).

---

## 4. Fidelity gate: the report-layer anti-drift control (FR-5)

**A plain pure function that rejects any printed value not matching a finalized source row** — the
report-layer analogue of the Risk Agent's numeric-provenance guardrail, but over *assembly output*
instead of *model output*, so it needs no SDK primitive.

```
assemble the report model (every slot filled from a queried source value)
        │
        ▼
fidelity gate: for every value bound into the document →
        match it EXACTLY (tolerance 0.0) against the finalized source rows it was drawn from
        │
   ┌────┴──────────────────────────┐
  all match                   ≥1 untraceable
   │                               │
 render + persist          FAIL CLOSED → WITHHELD/PROVENANCE_MISMATCH
 (RENDERED + marks)        (no document containing the untraceable value is ever written)
```

- **Exact-match, default tolerance 0.0** (settled): the strictest, fail-safe rule — it can only
  reject drift, never accept it, matching the Risk Agent's guardrail default. **Display** formatting
  (units, thousands separators, rounding *for display*) is applied *after* the bound value passes;
  the *bound* comparison is exact. A rounding tolerance stays a config `TODO` until an engineer
  supplies it (Open Item) — never guessed.
- **Why fail-closed here** (unlike the missing-section case, which renders marked-unavailable): a
  *missing* section is an honest gap a reader can see; an **untraceable printed number** is a
  silent falsehood in a government document — the one failure worse than producing nothing. So this
  is the single degraded case that withholds the whole document.
- This is the test target of AC-5 (positive + negative).

---

## 5. Audit & reproducibility (Principle VI, FR-9/FR-11)

**Structured record + decision-log entry — no SDK trace, because no model runs** (research §2;
constitution VII's trace mandate is model-scoped):
- **(a) Structured `report_artifacts` row** — the permanent, queryable system-of-record: which
  assessment id+version was rendered, the source-row versions consulted, the `template_version`,
  the outcome + marks, and the artifact pointer. The row **alone** answers *what report was
  produced, when, from which finalized inputs* (AC-11).
- **(b) `decision_log` entry** — recommend extending the shared `decision_kind` enum (0004/0007
  precedent) with `REPORT_RENDERED`, `REPORT_WITHHELD`, `REPORT_ERROR`, keeping one reconstructable
  audit story across all four agents (consistent with the DCA/SA/Risk choice).
- **Reproducibility (AC-11):** because the render pins `assessment_id`+`assessment_version`, the
  source-row versions, the pinned `standard_version`, and `template_version`, a report is
  re-derivable from exactly those identities even after an input is later superseded or a
  standard/limit retuned — the same discipline the Risk Agent applies to its inputs.

*(Open Item: report artifact store + retention — where the PDF bytes live (Neon `bytea` vs. object
storage) and for how long, in a government context. Parallel to the Risk plan's trace-retention
item; the append-only/versioning guarantee (FR-9) is required regardless of where.)*

---

## 6. How it's triggered (n8n, downstream of Risk — async fire-and-notify)

**Decision: downstream of the Risk Agent, fired per finalized assessment; the render runs
asynchronously and notifies on completion — n8n does not block for the render** (FR-12; research §3;
mirrors the DCA→SA→Risk edges, plus the async wrinkle a 5–30 s render demands).

```
… Risk Agent writes risk_assessments (append/supersede) + decision_log
        │  n8n: on risk-assessment-available for bridge B, cycle C
        ▼
n8n: trigger Report Generation service with the scope key (assessment id, or (B, C))
        ▼
Report Generation service (deterministic, async):
  1. validate scope key → resolve the assessment row (current, or a labelled historical by id)
  2. read finalized rows by identity: risk_assessments → source_analysis_ids → validated_readings
  3. assemble the report model (verbatim explanation + fixed band headline + tables + chart data)
  4. fidelity gate (FR-5): every value exact-matches a source row, else WITHHELD/PROVENANCE_MISMATCH
  5. render (async): matplotlib(Agg) chart images → ReportLab PDF; missing section → mark unavailable
  6. determine marks: NOT_FINAL (pending/critical) · SCORE_WITHHELD · HISTORICAL · SECTION_UNAVAILABLE
  7. atomic write: render to temp, then publish the artifact + report_artifacts row + decision_log
  8. NOTIFY (report-ready): emit a structured ReportSummary / signal — n8n does not hold the call
→ downstream Publish/Alert agent (separate) may submit the report; owns the needs_approval dispatch
```

**Why async fire-and-notify** (research §3):
- A multi-page render with charts takes seconds to tens of seconds — too long to hold a synchronous
  trigger/HTTP call reliably. n8n **enqueues and moves on** (glue), the service renders in the
  background and **notifies** on completion, rather than n8n blocking for 30 s.
- The artifact write is **atomic** (render to temp, then publish) so a consumer never sees a
  **partial** PDF — the report analogue of the pipeline's append-+-supersede atomicity.
- A render failure is a logged `ERROR` status + safe retry, never a crash or a half-file (FR-12).

**Responsibility split (for review):**
- **n8n owns:** detecting a finalized assessment, invoking the service with the scope key, retrying
  the *trigger*, and routing the report-ready signal. Glue, not logic.
- **The service owns:** the reads, the assembly, the fidelity gate, the render, all
  `report_artifacts` + audit writes, idempotency/supersession, the atomic write. It never writes
  the Risk/SA/DCA tables, and **never dispatches/publishes** to an external party.
- **The downstream Publish/Alert agent owns:** submitting the report to an authority, behind
  `needs_approval` (FR-13; out of scope here).

*(Open Item: the async enqueue + "report ready" notify mechanism — n8n's own queue vs. a jobs table
the service polls; and how the signal reaches the dashboard / a downstream Publish step.)*

---

## Constitution Check

| Principle (CLAUDE.md / v2.1.0) | How this plan complies |
|---|---|
| I — Safety First / human signs off physical actions; score has a WHY | Takes no physical action; no `needs_approval` here (the gate is on the downstream Publish/Alert dispatch tool). Renders the score **with** its verbatim WHY (FR-1/FR-2). A `NOT_FINAL` verdict is rendered marked not-yet-final, never as settled (FR-7); mandate #3 flows through the presentation layer. |
| II — Data Integrity: raw immutable, every number traceable | Reads (never mutates) Risk/SA/DCA tables; `report_artifacts` pins `assessment_id`+version → `source_analysis_ids` → validated → raw; append+supersede, DELETE blocked; the **exact-match fidelity gate** (FR-5) is the report-layer traceability control. |
| III — Modularity: no agent calls another's internals | Reads the Risk Agent's published `risk_assessments` table by identity; no handoff, no internal calls; publication is a separate downstream agent. |
| IV — Reliability Over Cleverness: deterministic where possible | **No model at all** — pure deterministic templating; the one summary line is a fixed severity→headline lookup, not generated prose. Using an LLM here would be the violation Principle IV forbids. |
| V — Testability: 4-scenario | AC-12: returns a structured outcome on missing assessment / unreadable provenance / absent section data / malformed scope key, never throws; render is async; no partial document. |
| VI — Auditability | Structured `report_artifacts` row + `decision_log` entry; reproducible from pinned assessment/source/template versions. (No SDK trace — no model run; VII is model-scoped.) |
| VII — Tech Stack / trace from day one | Deterministic Python service (Option A, like DCA/SA); Neon/Postgres with **standard indexes only** (partial unique index for idempotency — no TimescaleDB); n8n trigger; ReportLab + matplotlib(`Agg`) for the PDF. **Imports no SDK** (calls no model) — the alias-import adapter rule does not apply. |

---

## Open Items To Resolve Before Build

**Config TODOs (supplied later; placeholders until then — do not guess):**
1. **Severity→headline lookup table (config):** the fixed exec-summary headline phrase per band
   (FR-2) — a wording/policy choice, but a fixed table keyed on the already-decided severity, not
   generated text.
2. **Fidelity rounding tolerance (config):** stays exact-match (0.0) until an engineer supplies a
   tolerance (FR-5); do not loosen a safety-relevant match without sign-off (mirrors the Risk
   Agent's guardrail-tolerance TODO).
3. **Appendix raw-data depth bound (config):** how much raw history the appendix includes before
   truncation-with-a-note (FR-6, Edge Cases).
4. **Report template + letterhead + sign-off config:** the section layout, government branding, and
   sign-off block as configuration, and how `template_version` is stamped for reproducibility (FR-11).

**Design decisions (this plan proposes; sign off before build):**
5. **`report_artifacts` schema sign-off:** the `marks` representation (enum array vs. booleans), the
   `outcome`/`withheld_reason` enums, the `(assessment_id, assessment_version)` idempotency rule,
   and the append+supersede triggers.
6. **Artifact store + retention (design):** where the rendered PDF bytes live — Neon `bytea` vs.
   object storage + a URL row — and the government retention policy. The append-only/versioning
   guarantee (FR-9) holds regardless.
7. **Async enqueue + "report ready" notify mechanism (design):** n8n's own queue vs. a jobs table
   the service polls; how completion is signalled to the dashboard / a downstream Publish step
   (research §3; FR-12).
8. **Trigger contract (design):** the exact scope-key shape (assessment id vs. `(bridge_id,
   cycle_id)`), and **how a historical reprint is requested** so it is distinguishable from a normal
   current render (FR-4, FR-10).
9. **PDF/chart libraries (design, named in research):** ReportLab (PDF) + matplotlib/`Agg` (static
   charts) — new dependencies to add to `pyproject.toml` at build time; the plan is otherwise
   library-agnostic. Neither is installed today.
10. **Provenance-chain read path (design):** how the service walks assessment → `source_analysis_ids`
    → SA rows → `source_validated_ids` → DCA rows to assemble the sensor tables/appendix, and how
    much of that chain each section requires (informs the read queries + the `[DB-DEP]` fakes).
11. **Audit home:** extend `decision_log` (recommended) vs. a separate `report_log`; and the
    `REPORT_RENDERED`/`REPORT_WITHHELD`/`REPORT_ERROR` kinds.

**Cross-agent / governance:**
12. **Publish/Alert chokepoint confirmation (cross-agent):** verify the downstream Publish/Alert
    agent is the **single** un-bypassable `needs_approval` point for report **submission**, so
    FR-13's "gate lives downstream" holds in code (Principle I; mirrors the Risk plan's Alert-Agent
    item).
13. **Dashboard consumption (cross-agent):** whether the Next.js dashboard reads `report_artifacts`
    to surface/download reports, and how the report-ready signal reaches it (shared with item 7).
