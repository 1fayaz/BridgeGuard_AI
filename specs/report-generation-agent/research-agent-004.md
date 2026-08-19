# Findings: Report Generation Agent (Agent 004)

**Type:** Research findings — NOT a design. No architecture, no code.
**Date:** 2026-07-04
**Anchors:** `CLAUDE.md` (Neon/Postgres, n8n glue, trace-from-day-one, gate real-world actions);
`.specify/memory/constitution.md` v2.1.0 (Principles I, II, IV, VI, VII);
`skills/bridgeguard-skills-README.md` (`pdf-report` = ReportLab multi-page; `visual-output` =
"static chart images for PDF embedding"); `specs/risk-reasoning-agent/spec.md` (the upstream
verdict this agent renders); `db/migrations/0006_risk_assessments.sql` (the row it reads);
precedent `research-agents-sdk.md` (DCA, Option A) + `research-agent-003.md` (Risk, the Agent case).

> Scope note: this agent turns a **completed, persisted risk assessment** into a professional,
> government-ready **PDF** (cover, exec summary, sensor tables, charts, math results, the Risk
> Agent's verbatim explanation). It fuses nothing and judges nothing — the judgment already
> happened upstream (Agent 003). This doc only investigates the five questions below; it does
> not decide the design.

---

## Framing: this is the DCA/SA case, not the Risk case (Option A)

The book's decision — *use a model only for genuinely ambiguous, compound judgment; use
deterministic code everywhere a rule suffices (Principle IV)* — put the DCA and SA on the
deterministic-**service** side (Option A) and put Risk (003) alone on the model-**Agent** side.
**Report generation lands squarely back on the deterministic-service side:** every input is
already computed, validated, and judged; rendering them into a fixed template is mechanical.
The interesting questions here are therefore not "how is the model shaped" but "does it need a
model at all," and "does putting files on disk need isolation."

---

## 2. Does this agent need ANY model call? (answered first — it gates everything else)

**Read: NO model call. This is pure deterministic templating — Option A, same as DCA/SA.** The
`pdf-report` skill's own description is a fixed structure (cover → exec summary → tables → charts
→ math → recommendations → appendix → sign-off), and **every value it prints already exists**:

- score, severity, recommendation, `contributing_factors`, `confidence`/`data_completeness`,
  provenance, `trace_id` — from the `risk_assessments` row (0006);
- the **explanation is copied VERBATIM** — Principle I + FR-9 make it a safety output logged
  word-for-word; the report **must not** re-summarize or re-word it (re-wording = a new,
  ungoverned narrative that bypasses the numeric-provenance guardrail Agent 003 already passed);
- sensor tables + math results — from SA `analysis_results` / DCA `validated_readings`.

There is **no ambiguous judgment left to make**, so Principle IV *forbids* an LLM here (using a
model where a template suffices is a violation, not a nicety). **Consequence:** if no model call,
this is **NOT an Agents-SDK Agent** — it is a deterministic Python service n8n invokes, exactly
like the DCA and SA. No frontier tier, no output guardrail, no `needs_approval` **on this agent**
(publication/dispatch is a *downstream* real-world action — see Q3 + Principle I).
**Unknown:** whether the exec-summary page wants a 1-line human-readable status *derived* from the
band (a deterministic lookup like the recommendation table — still no model), vs. copying only.

## 1. Sandboxed execution (E2B/Cloudflare) vs. plain in-process @function_tool?

**Read: ReportLab + matplotlib run safely IN-PROCESS; no E2B/Cloudflare sandbox needed.** Apply
the book's **harness-vs-compute** test — *isolate when you run untrusted/model-authored code or
shell out; stay in-process for a trusted library call over trusted data.*

- The agent runs **our own code** over **our own already-validated rows**. It does **not**
  execute model-generated code, evaluate expressions, or shell out — the E2B/sandbox case
  (arbitrary/LLM-authored code) simply does not arise here.
- ReportLab and matplotlib(`Agg`) are ordinary Python libraries writing bytes to a path we
  choose; that is *compute*, not an untrusted *harness*. Sandboxing it would add ops complexity
  for no threat-model gain.
- The only real I/O concerns are mundane and handled in-process: **write to a controlled
  artifact location** (not user-supplied paths), cap page/row counts so a giant appendix can't
  exhaust memory, and treat PDF bytes as an **append-only artifact** (Principle II — never
  overwrite a prior report; new render = new versioned object, mirroring supersede-not-overwrite).
**Unknowns:** where rendered PDFs live (Neon large-object / bytea vs. object storage + a URL row)
and its retention — a plan.md decision, parallel to the trace-store question in 003 §5.

## 4. Static charts server-side without a browser → matplotlib (confirm fit)

**Read: matplotlib with the `Agg` backend is the right server-side renderer; confirmed fit.** The
`visual-output` skill names **Recharts/Plotly/D3 for the DASHBOARD** — those are browser/JS
renderers (React components, client HTML), wrong for a headless PDF pipeline. The same skill
explicitly also lists *"static chart images for PDF embedding"* as a distinct output, which is
the matplotlib job:

- matplotlib is pure-Python, **headless** (no browser/Node), renders PNG/SVG to a buffer that
  ReportLab embeds directly, and shares the stack's NumPy/Pandas world (README §Tech Stack).
- It keeps the chart-image path **deterministic and reproducible** (same inputs → same PNG),
  which the dashboard's interactive JS charts are not — right for an auditable government artifact.
- **Division of labour to record:** Recharts/Plotly = live dashboard (Agent = the Next.js
  frontend); matplotlib = static PDF chart images (this agent). They are not substitutes.
**Unknown:** whether chart images are generated *here* from the source rows, or SA/`visual-output`
pre-renders and this agent only embeds — affects who owns the chart-provenance link.

## 3. Async or sync? (5–30 s assembly)

**Read: fire-and-notify (async), not a blocking trigger — but confirm against n8n's model.** A
5–30 s render is far too long to hold a synchronous trigger/HTTP call open reliably:

- Consistent with the established pattern: n8n is **glue that invokes and moves on** (DCA/SA
  workflows POST to a service entrypoint and branch on a structured `ok`). A long render should
  be **enqueued**: n8n triggers → the service renders in the background → on completion it
  **notifies** (writes a `report_ready` row / emits an event / calls a webhook), rather than n8n
  blocking for 30 s.
- This mirrors the service's existing "**never raise, always return a structured status**"
  contract (DCA `CycleSummary`, Risk `AssessmentSummary`): here a `ReportSummary { ok, report_ref
  | error }`. A render failure is a logged status + retry, never a crash or a half-file.
- The artifact write must be **atomic** (render to temp, then publish) so a consumer never sees a
  partial PDF — the report analogue of append-+-supersede.
**Unknowns:** the exact enqueue mechanism (n8n's own queue vs. a jobs table the service polls) and
whether "report ready" feeds the dashboard, an email/publish step, or both — plan.md.

## 5. What does the agent receive as input — a row ID, or a full payload?

**Read: pass the `risk_assessment` **ID (the scope key)**, and the agent QUERIES the rest itself
— do not pass a fat denormalized payload.** Both precedents point the same way (Principle II/III):

- **Provenance & reproducibility (Principle II, FR-10):** the report must trace every printed
  number to its system-of-record row. If n8n hands over a copied payload, the report could render
  numbers that **drift** from (or were never in) the pinned rows. Reading by ID from
  `risk_assessments` (+ its `source_analysis_ids` → SA rows → DCA rows) means the PDF is a faithful
  render of the audited record, reproducible later from the **same** IDs even after supersession.
- **Modularity (Principle III):** the trigger contract stays a thin scope key
  (`{ bridge_id, cycle_id }` or the `risk_assessments.id`), exactly like the DCA/Risk service
  entrypoints — n8n carries no report data and derives nothing.
- **Read-only, current-only:** like Agent 003's tools, this agent only *reads* and consumes the
  **current** (`superseded_by IS NULL`) rows, recording which versions it rendered.
**Minimal trigger:** the `risk_assessments` row id (or `{bridge_id, cycle_id}`, which the 0006
partial-unique index resolves to exactly one current row). **Unknowns:** whether a report may be
requested for a *superseded/historical* assessment (regulatory re-print) and how the appendix's
raw-data depth is bounded.

---

## Cross-cutting: `needs_approval` and the "publication" real-world action

CLAUDE.md lists **"report publication"** alongside closure/alert as a gated real-world action.
Worth separating cleanly (as 003 did for closure): **rendering a PDF harms nothing** (it is an
artifact, like emitting a recommendation) and must not be blocked — so **no `needs_approval` on
the render**. If a downstream step *publishes/submits* the report to a municipality, **that**
dispatch is the gated action, and — per Principle I / the Alert-Agent chokepoint finding (003 §2)
— it belongs on the publishing tool, not here. **Unknown to verify:** whether publication is this
agent's concern at all or a separate Alert/Publish agent's (likely the latter, keeping this agent
a pure renderer).

---

## Summary

| | Status |
|---|---|
| **What's settled (read)** | (2) No model call → **deterministic service, NOT an Agents-SDK Agent** (Option A, Principle IV); (1) ReportLab+matplotlib run **in-process, no E2B/sandbox** (trusted lib over trusted data — not the untrusted-code harness case); (4) **matplotlib/`Agg`** for static PDF charts (Recharts/Plotly are dashboard-only); (3) **async fire-and-notify** with an atomic artifact write; (5) pass the **row ID; agent queries the rest** for faithful, reproducible provenance. |
| **Main options** | Chart images rendered here vs. embedded-from-upstream; PDF stored as Neon bytea vs. object-store + URL row; enqueue via n8n queue vs. a jobs table; report allowed for historical/superseded assessments or current-only. |
| **Biggest unknowns** | (1) artifact store + retention (parallel to 003's trace-store question); (2) exact async enqueue/notify mechanism; (3) whether publication/`needs_approval` is in-scope (likely a downstream Publish/Alert agent); (4) appendix raw-data depth bound; (5) exec-summary: verbatim-only vs. a deterministic band-derived status line. |

**Sources:** `skills/bridgeguard-skills-README.md` (`pdf-report`, `visual-output`);
`.specify/memory/constitution.md` v2.1.0 (I, II, IV, VI, VII); `CLAUDE.md`;
`db/migrations/0006_risk_assessments.sql`; `specs/risk-reasoning-agent/spec.md` +
`research-agent-003.md`; `specs/data-collection-agent/research-agents-sdk.md`; ReportLab +
matplotlib(`Agg`) headless-rendering docs.
