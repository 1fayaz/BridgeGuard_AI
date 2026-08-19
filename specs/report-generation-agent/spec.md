# Report Generation Agent — Specification

**Status:** Clarified (Specify + clarification interview folded in; the assemble-not-re-decide
invariant is baked in — FR-1). Seven interview decisions incorporated (see the decisions below);
residual config/design items are deferred under **Open Items**.
**Date:** 2026-07-04
**Anchors:** `CLAUDE.md` (constitution); `.specify/memory/constitution.md` v2.1.0
(Principles I, II, IV, VI, VII); `skills/bridgeguard-skills-README.md` (`pdf-report` report
structure; `visual-output` "static chart images for PDF embedding"); `specs/risk-reasoning-agent/spec.md`
(the finalized verdict this agent renders — its output contract §123–147);
`specs/report-generation-agent/research-agent-004.md` (research).

> **Behaviour only.** This spec describes WHAT the agent does and WHY — no databases, PDF/chart
> libraries, async mechanisms, SDK classes, or file layout. Those are design decisions made later
> (`plan.md`). The research doc names the candidate technologies; this spec names none.

---

## Goal

This agent is the **presentation layer** of BridgeGuard. It consumes the **already-finalized**
output of the upstream pipeline — the Risk Reasoning Agent's risk assessment, and through it the
Structural Analysis and Data Collection results it was built from — and **renders a professional,
government-ready report document (PDF)**: cover page, executive summary, sensor tables, charts,
mathematical results, the risk score and severity, and the risk verdict's plain-language
explanation.

It exists because the judgment is already done. Every number has been computed (Data Collection →
Structural Analysis), and the danger verdict and its written WHY have been decided and audited (Risk
Reasoning Agent, which already passed a numeric-provenance guardrail on its own explanation). This
agent's single job is to **assemble those finalized facts into a readable, accountable document** —
faithfully, reproducibly, and without adding, changing, recomputing, or rewording a single value or
sentence.

**It assembles; it does not re-decide.** This is the spine of the whole spec (FR-1). The agent is
**deterministic templating, not judgment** — Principle IV forbids a model here, because there is no
ambiguous decision left to make. It takes **no real-world action**: rendering a document harms
nothing; *publishing/submitting* it to an authority is a separate, downstream, gated concern
(Principle I; Out of Scope).

---

## Settled in clarification interview (baked into the FRs below)

- **Not-final policy → render, marked not-final.** A `CRITICAL` / `PENDING_HUMAN_REVIEW`
  assessment is **rendered immediately**, conspicuously stamped *awaiting human review*, with its
  recommendation shown as pending — it is **not** held until cleared. Rationale: the human doing
  the review should have the full document in front of them. Mandate #3 is honoured by the
  not-final mark, not by withholding the document (FR-7).
- **Withheld assessment → `RENDERED`, marked withheld.** When the upstream assessment withheld its
  score, a **real report is still produced** (outcome `RENDERED`) stating the withheld state and
  the verbatim withheld reason — not a lighter no-document status. Every assessment yields a
  document; a withheld one yields an honest withheld document (FR-8).
- **Executive summary → verbatim explanation + a deterministic band-derived headline.** A **fixed
  severity→headline lookup** (config, no model — e.g. `CRITICAL → "Immediate closure recommended"`)
  is permitted as a headline **alongside** the verbatim explanation. The headline is deterministic
  configuration, not generated prose, so it does not breach assemble-only (FR-2/FR-3).
- **Publication → out of scope; a separate downstream agent owns it.** This agent **renders and
  stops**. Submitting/dispatching the report to an authority — and the `needs_approval` gate on
  that dispatch — belongs to a downstream Publish/Alert agent, not here (FR-13).
- **Missing mandatory-section content → render with the section marked unavailable.** If a required
  section's upstream content cannot be read, the report is **still produced** with that section
  conspicuously marked *data unavailable* (never fabricated); the rest renders. A partial-but-honest
  document is more useful to an engineer than none (FR-6).
- **Historical reprint → allowed, labelled historical.** A report **may** be rendered for a
  **superseded** (historical) assessment for a regulatory reprint, conspicuously labelled
  *historical — superseded by a later assessment*. This is the one case the agent reads a
  non-current row, and it is labelled as such (FR-4).
- **Fidelity match → exact match (default 0.0), tolerance a config TODO.** A printed value must
  **equal** its source value exactly (fail-safe: can only reject drift, never accept it) — the same
  strict default the Risk Agent's guardrail chose. Display formatting is fine; the *bound* value is
  exact. A configured rounding tolerance stays a `TODO` sentinel until an engineer supplies it — not
  guessed now (FR-5).

---

## Core Concepts

- **Assemble, never re-decide (the central invariant).** Every number and every word of narrative
  in the report is **copied from an upstream agent's already-finalized, persisted output**. The
  agent **never** recalculates a score, re-runs a calculation, re-derives a ratio, re-maps a
  severity band, or re-words an explanation. If a value is not present in the finalized upstream
  record, it does **not** appear in the report — it is never invented, interpolated, or inferred.
  This is the report's equivalent of the pipeline's raw-data-immutability rule (Principle II): the
  finalized verdict is the "raw" this layer renders, and it is rendered intact.

- **The risk explanation is copied VERBATIM.** The Risk Reasoning Agent's `explanation` is a
  first-class safety output that already passed that agent's numeric-provenance guardrail
  (Principle I / Risk FR-7). This agent reproduces it **word-for-word**. It does **not** summarize,
  paraphrase, shorten, "improve," or re-word it — a re-worded narrative would be a **new, ungoverned
  statement** that never passed any guardrail, which is exactly the failure this agent must not
  introduce.

- **Deterministic templating; no model call.** The report structure is a fixed template; every
  slot is filled from a queried value. Given the same finalized inputs, the agent produces the
  same document. No LLM is in the path (Principle IV — using a model where a template suffices is a
  violation, not a nicety). This places the agent on the **deterministic-service** side, the same
  as the Data Collection and Structural Analysis agents — **it is not a model-calling Agent.**

- **Reads finalized, current facts from the system of record — by identity, not by payload.** The
  agent is triggered with a **scope key** (the identity of one risk assessment) and **queries** the
  finalized rows itself: the risk assessment, and through its recorded provenance the structural
  and data-collection facts it cites. It consumes only **current (non-superseded)** rows and
  records which versions it rendered, so the document is a faithful, reproducible render of the
  audited record — not a snapshot of data copied into a trigger that could drift from the
  system of record.

- **Finality is honoured, never overridden.** A report reflects the assessment's `review_status`.
  A `PENDING_HUMAN_REVIEW` or `CRITICAL` verdict is rendered **marked as not-yet-final** — the
  document must not present a verdict the pipeline itself holds as unsettled as though it were
  settled (Risk FR-11 / mandate #3 flows through into the report). A **withheld** assessment (no
  score) is rendered **honestly as withheld**, stating what was missing — never as a fabricated
  or blank "all clear."

- **Fidelity is a gate, not a nicety.** Before a report is emitted, every value it prints must
  match a value in the finalized source rows it was assembled from. A printed number that traces
  to **no** source value is an assembly defect — the report **fails closed** rather than publish a
  document containing an untraceable number (the report-layer analogue of the Risk Agent's
  numeric-provenance guardrail). *(Exact-match vs. rounding tolerance — Open Items.)*

- **Charts are deterministic renders of source data, not new analysis.** Any chart embedded in the
  report is a static visual of values already in the finalized rows (a time series of readings, a
  risk gauge of the existing score, a comparison against the pinned standard). Producing a chart is
  **rendering**, not computing — the agent derives no new quantity for a chart that isn't already
  an upstream fact. *(Interactive dashboard charts are a different concern — Out of Scope.)*

- **The report artifact is append-only.** A newly rendered report **never overwrites** a prior
  report for the same assessment; a re-render produces a **new versioned artifact**, with the prior
  retained (Principle II / VI — a report a regulator may have relied on is permanent). This mirrors
  the pipeline's append-+-supersede discipline.

- **Rendering is fire-and-notify, and never crashes.** Assembling a multi-page document with charts
  can take seconds to tens of seconds; the agent runs the render **asynchronously** and **notifies**
  on completion rather than blocking its trigger. It **always** returns a structured status
  (rendered / withheld / error) and **never** propagates an unhandled exception; a partial document
  is never published (the artifact write is atomic — a consumer sees a complete report or none).

- **Report structure, letterhead, and formatting are configuration, not code.** The section
  layout, the government letterhead/branding, the sign-off block, and per-section templates are
  **configuration**. Changing the report's appearance or adding a section must not require changing
  the assembly logic. *(Template/versioning specifics — Open Items / `plan.md`.)*

---

## What this agent receives (input contract)

Per report, the trigger carries a **scope key only** — the identity of **one finalized risk
assessment** (one whole-bridge assessment at one Structural-Analysis cycle). Concretely: the risk
assessment's identity, or equivalently the `(bridge_id, cycle_id)` that resolves to exactly one
current assessment. The trigger carries **no report data** — it names *what* to render, and the
agent queries *the content* from the system of record (Principle III; research §5).

From the system of record, keyed off that assessment, the agent **reads** (never writes, never
re-derives):

| Source (finalized upstream output) | What the report renders from it |
|---|---|
| **Risk assessment** (Risk Reasoning Agent) | `risk_score`, `severity`, `recommendation`, the **verbatim `explanation`**, `contributing_factors`, `confidence`/`data_completeness`, `review_status`, and provenance (`source_analysis_ids`, `baseline_ref`, `standard_code`+`standard_version`, `score_weights_version`, `model_id`+`model_version`, `trace_id`) |
| **Structural analysis results** (via `source_analysis_ids`) | the sensor calculation results — RMS/FFT/threshold values, ratios, pass/fail-vs-limit facts — for the sensor tables and the math-results section |
| **Data-collection / validated readings** (via the analysis results' provenance chain) | recent sensor readings for the time-series tables and charts, and the raw-data appendix |
| **Engineering standard** (pinned in the assessment) | the standard code + version the verdict was compared against, for the comparison section |

The agent consumes only **current (non-superseded)** rows and records the exact versions rendered
(FR-11), so the report is reproducible from the same identities even after an input is later
superseded or a standard is later revised.

---

## Invocation & Work Intake

- **Triggered per finalized assessment, downstream of the Risk Reasoning Agent.** When a risk
  assessment is available for a bridge+cycle, a deterministic trigger (workflow glue) invokes this
  agent with that assessment's scope key. One trigger → one report for one assessment.

- **The agent queries its content; the trigger defines only the scope.** It does not scan for work
  or hold a cursor; the trigger's scope key is the unit of work, and everything printed is read
  from the finalized rows that key resolves to.

- **Fire-and-notify.** The agent acknowledges the trigger and renders asynchronously; on completion
  it emits a structured result (and a "report ready" signal) rather than holding the trigger open
  for the duration of the render. A render failure is a logged status + safe retry, never a crash
  or a half-written artifact.

- **Idempotent re-trigger.** A trigger may fire more than once for the same assessment
  (at-least-once delivery, retry). A re-trigger for an assessment whose **current version** has
  **already been rendered** is a **no-op** — it does not produce a duplicate artifact. A render for
  a **newer** assessment version (the assessment was re-assessed and superseded upstream) produces
  a **new versioned report** that supersedes the prior one; it never overwrites it.

---

## Report Outcome Vocabulary (closed set)

Every invocation resolves to exactly one **outcome**; `RENDERED` carries one or more **document
marks** describing what kind of report it is, and `WITHHELD`/`ERROR` carry exactly one **reason
code** (a build using an unlisted outcome/mark/reason, or emitting no outcome for a trigger, fails).

**Outcomes:** `RENDERED` (a report artifact was produced from finalized inputs) · `WITHHELD` (no
document produced, for a named reason) · `ERROR` (an unexpected failure was isolated into a
structured status — never a crash).

The clarification interview settled that **every readable assessment yields a document** — so most
degraded situations are `RENDERED` **with a conspicuous mark**, not `WITHHELD`. `WITHHELD` is
reserved for the cases where there is genuinely nothing to render.

**`RENDERED` document marks (closed set; a report carries the marks that apply, `FINAL` when none
do):**
- `FINAL` — a complete report of a `FINAL` assessment; no other mark applies.
- `NOT_FINAL` — the assessment is `CRITICAL` / `PENDING_HUMAN_REVIEW`; the report is produced now
  but conspicuously stamped *awaiting human review*, recommendation shown as pending (settled:
  render-marked, not hold-until-cleared).
- `SCORE_WITHHELD` — the upstream assessment withheld its score; the report states the withheld
  state and the **verbatim withheld reason**, shows **no** fabricated score/band (settled:
  `RENDERED`-marked, not a `WITHHELD` outcome). Co-occurs with `NOT_FINAL`.
- `HISTORICAL` — the report was rendered for a **superseded** assessment (regulatory reprint) and
  is conspicuously labelled *historical — superseded by a later assessment* (settled: allowed,
  labelled).
- `SECTION_UNAVAILABLE` — a required section's upstream content could not be read; that section is
  conspicuously marked *data unavailable* and the rest of the report renders (settled:
  render-with-section-marked, not withhold-whole-report).

**`WITHHELD` reason codes (no document produced):**
- `ASSESSMENT_NOT_FOUND` — no assessment exists for the scope key (nothing whatsoever to render).
- `PROVENANCE_MISMATCH` — a value assembled for the report did **not** trace to a finalized source
  row (fidelity gate tripped); the report **fails closed** rather than publish an untraceable
  number. This is the one degraded case that withholds the document, because publishing an
  untraceable number is a worse failure than publishing nothing.

---

## User Scenarios

- **A finalized, FINAL assessment — a complete report.** A bridge's risk assessment is present and
  `FINAL`. The agent reads it and its provenance chain, renders the cover, executive summary
  (carrying the **verbatim** explanation), sensor tables, charts, math results, risk breakdown,
  standards comparison, recommendations, and appendix, and emits `RENDERED`. Every printed number
  matches a source row.

- **A Critical, pending-review assessment — rendered, but stamped NOT final.** The assessment is
  `CRITICAL` / `PENDING_HUMAN_REVIEW`. The report is produced (or held — the Clarify question) but,
  if produced, it is **conspicuously marked not-yet-final / awaiting human review** and does not
  present the closure recommendation as a settled decision. The document never launders a
  pending verdict into a final one (mandate #3 flows through).

- **A withheld assessment — an honest withheld report, never a fake score.** The upstream
  assessment withheld its score (below coverage floor, or a guardrail fail). The report renders the
  **withheld state honestly** — the executive summary states that a score could not be produced and
  what was missing (the verbatim withheld explanation) — and shows no fabricated number or blank
  "all clear."

- **A printed number wouldn't trace to a source row — report withheld.** During assembly a value
  destined for the report matches **no** finalized source value (a template/query defect, a stale
  join). The **fidelity gate tripwires**; the agent emits `WITHHELD/PROVENANCE_MISMATCH` and does
  **not** publish a document containing an untraceable number — the report-layer echo of the Risk
  Agent's guardrail.

- **The assessment was re-assessed after the first report — a new versioned report.** The Risk
  Agent superseded the assessment (re-assessment). A re-trigger renders a **new report version**
  against the current assessment and links it as superseding the prior report; the earlier report
  is retained, not overwritten (a regulator can see both).

- **A redelivered trigger for an already-rendered assessment — no duplicate.** The same trigger
  fires twice for the same current assessment version. The second is a **no-op**; no duplicate
  artifact is created.

- **Chart data missing for a section — the section is marked unavailable, not faked.** The readings
  needed for a time-series chart are absent. The agent renders the report with that chart section
  **explicitly marked unavailable**, rather than drawing an empty or invented chart.

---

## Functional Requirements

A build that ignores any of these should **visibly fail** a corresponding test.

- **FR-1 — Assemble-only: every value and every sentence comes from finalized upstream output;
  nothing is recomputed or reworded.** For every number, ratio, score, severity, recommendation,
  and narrative in the report, the source is an **already-finalized, persisted upstream record**
  read this run. The agent **never** recalculates a score, re-runs a calculation, re-derives a
  ratio, re-maps a severity band, or paraphrases an explanation. A value not present in the
  finalized upstream record **does not appear** in the report. A build that computes, derives,
  infers, or rewords **any** reported value — rather than copying it — fails. *(Principle II/IV;
  the spine of this agent.)*

- **FR-2 — The risk explanation is reproduced VERBATIM; only a fixed band-derived headline may be
  added.** The Risk Reasoning Agent's `explanation` is copied into the report **word-for-word**, not
  summarized, paraphrased, shortened, or edited. The **one** permitted piece of non-copied summary
  text is a **deterministic severity→headline lookup** from fixed configuration (e.g. `CRITICAL →
  "Immediate closure recommended"`), rendered as a headline **alongside** — never in place of — the
  verbatim explanation; because it is a fixed config lookup keyed only on the already-decided
  severity, it introduces no new judgment and no generated prose. A build that alters the explanation
  text — even to "improve" it — or that produces the headline from anything other than a fixed
  severity-keyed lookup (a model, a computed phrase), fails. *(Principle I; Risk FR-7 — the WHY
  already passed its guardrail and must not be replaced by an ungoverned restatement; settled in
  interview.)*

- **FR-3 — Deterministic templating; no model call.** The report is produced by filling a fixed
  template from queried values, with **no LLM anywhere in the path**. Given the same finalized
  inputs and the same template config, the output is the same document. A build that invokes a
  model to generate, summarize, or narrate report content fails. *(Principle IV; this is why the
  agent is a deterministic service, not an Agents-SDK Agent — research §2.)*

- **FR-4 — Content is read by identity from the system of record; renders the current version, or a
  historical one only when explicitly labelled.** The trigger carries a **scope key**; the agent
  queries the finalized assessment and its provenance chain itself and **records which versions it
  rendered** — never rendering numbers copied into the trigger (which could drift from the system of
  record). By default it renders the **current (non-superseded)** assessment. It **may** render a
  **superseded (historical)** assessment for a regulatory reprint, but only when the report is
  **conspicuously labelled `HISTORICAL`** (*superseded by a later assessment*) — a historical row is
  never rendered as though it were current. A build that renders from trigger-carried data, or that
  renders a superseded row **without** the historical label, fails. *(Principle II/III; research §5;
  settled in interview.)*

- **FR-5 — Fidelity gate: every printed value matches a finalized source row exactly; a mismatch
  fails closed.** Before emission, each value assembled for the report is verified to **equal** a
  value in the finalized source rows it was drawn from. The match is **exact (default tolerance
  0.0)** — the strictest, fail-safe rule (it can only reject drift, never accept it), matching the
  Risk Agent's guardrail default; display formatting (units, thousands separators, rounding *for
  display*) is fine, but the **bound** value is compared exactly. Any value that matches **no**
  source row is an assembly defect: the report is **withheld** (`WITHHELD/PROVENANCE_MISMATCH`)
  rather than published with an untraceable number. A build that emits a report containing a value
  absent from its finalized inputs, or that binds a printed value to a source value only
  approximately without a configured tolerance, fails. *(Principle I/VI; the report-layer analogue
  of Risk FR-7. Settled in interview: exact-match default; a rounding tolerance stays a config
  `TODO` until an engineer supplies it — Open Items.)*

- **FR-6 — Charts render existing facts only; missing content marks a section unavailable, it does
  not fabricate or withhold the whole report.** Every embedded chart is a static visual of values
  already present in the finalized rows; the agent derives **no** new analytical quantity to plot
  that is not already an upstream fact. When the content a required section (chart, table, or
  math-results block) needs cannot be read, that **section is conspicuously marked *data
  unavailable*** (`RENDERED` with the `SECTION_UNAVAILABLE` mark) and the **rest of the report still
  renders** — a partial-but-honest document, never a fabricated section and never a withheld whole
  report. A build that computes a new analysis result in order to chart it, fabricates chart/section
  data, or withholds the entire report because one section's content is missing, fails. *(Principle
  IV; Out of Scope — analysis is SA's job; settled in interview.)*

- **FR-7 — Finality is honoured: a not-final verdict is rendered now, but never as settled.** The
  report reflects the assessment's `review_status`. A `PENDING_HUMAN_REVIEW` or `CRITICAL`
  assessment **is rendered immediately** (settled: render-marked, **not** held until cleared),
  carrying the `NOT_FINAL` mark — **conspicuously stamped *awaiting human review*** — with its
  recommendation presented as a recommendation-pending-review, not a settled decision. The reviewing
  human thus has the full document in hand. A build that renders such a verdict as a final, settled
  report (no `NOT_FINAL` mark), or that **withholds** the document until review clears (defeating the
  reviewer's need for it), fails. *(Risk FR-11 / mandate #3 flows through the presentation layer;
  settled in interview.)*

- **FR-8 — A withheld assessment yields an honest RENDERED report marked score-withheld, never a
  fabricated number.** When the upstream assessment withheld its score, the agent **still produces a
  report** (outcome `RENDERED`, marks `SCORE_WITHHELD` + `NOT_FINAL`) that states — using the
  **verbatim** withheld explanation — that a score could not be produced and what was missing, and
  shows **no** invented score, band, or blank "all clear." A build that fabricates a placeholder
  score for a withheld assessment, or that produces no document at all for one (a `WITHHELD` outcome
  rather than a `RENDERED`-marked report), fails. *(Principle I; Risk FR-6; settled in interview:
  every readable assessment yields a document.)*

- **FR-9 — Report artifacts are append-only; a re-render never overwrites a prior report.** A new
  render for an assessment produces a **new versioned artifact**; any prior report for that
  assessment is retained and the new one is linked as superseding it. A build that overwrites or
  deletes a previously produced report fails. *(Principle II/VI.)*

- **FR-10 — Idempotent per assessment version.** A re-trigger for an assessment whose **current
  version** has already been rendered is a **no-op** (no duplicate artifact). A render for a
  **newer** assessment version supersedes the prior report. A build that produces duplicate reports
  for an identical re-trigger, or fails to re-render when the assessment was genuinely superseded,
  fails.

- **FR-11 — Reproducible audit trail (which assessment version + config, rendered when).** Each
  render records the **assessment identity and version** it rendered, the **source row versions**
  consulted, the **report template/config version**, and when it ran — so a report is reproducible
  from exactly those identities even after an input is later superseded or a standard/limit is
  retuned. A build whose report cannot be reproduced because the inputs/version it rendered weren't
  captured fails. *(Principle VI; mirrors the pipeline's config-version discipline.)*

- **FR-12 — Always structured, async, and never crashes.** For every trigger the agent returns a
  structured outcome (`RENDERED` / `WITHHELD`+reason / `ERROR`) and **never** propagates an
  unhandled exception; the render runs **asynchronously** (fire-and-notify) and the artifact write
  is **atomic** — a partial or corrupt document is never published. A build that blocks its trigger
  for the full render, crashes on missing/partial upstream input, or can publish a half-written
  file, fails. *(Principle IV/V; research §3.)*

- **FR-13 — No real-world action; rendering is not publication.** Producing a report document is
  **not** a real-world action and carries **no** `needs_approval` gate on this agent. Rendering
  does **not** dispatch, submit, email, or publish the report to any authority. If a downstream
  step submits/publishes the report, **that** dispatch is the gated real-world action and lives on
  the downstream publishing tool — not here (Principle I; the Alert/closure/publish chokepoint,
  research cross-cutting). A build in which this agent itself submits a report to an external party
  fails. *(Settled in interview: publication is **out of scope** — a separate downstream Publish/
  Alert agent owns dispatch and its `needs_approval` gate; this agent renders and stops.)*

---

## Edge Cases & Rules

- **Assessment is `PENDING_HUMAN_REVIEW` / `CRITICAL`.** Rendered **immediately**, carrying the
  `NOT_FINAL` mark / *awaiting human review* stamp (FR-7) — never held until cleared, never presented
  as a settled verdict.
- **Assessment withheld its score.** A `RENDERED` report marked `SCORE_WITHHELD` + `NOT_FINAL`,
  using the verbatim withheld explanation (FR-8); no fabricated number, and never a no-document
  outcome.
- **A value won't trace to a source row.** Fidelity gate trips → `WITHHELD/PROVENANCE_MISMATCH`
  (FR-5); no untraceable number is ever published.
- **Assessment superseded between trigger and render.** Render the **current** version and record
  which (FR-4); a re-assessment produces a new report version (FR-9/FR-10).
- **Redelivered / double-fired trigger.** Idempotent (FR-10): no duplicate artifact for an
  already-rendered current version.
- **Chart / section data missing.** The section is marked **unavailable** (`SECTION_UNAVAILABLE`,
  FR-6), not drawn from invented data; the rest of the report still renders.
- **Very large raw-data appendix.** Bounded to a configured depth so a huge history can't produce
  an unusable document or exhaust memory. *(Bound — Open Items.)*
- **Report requested for a historical / superseded assessment (regulatory reprint).** Permitted
  (FR-4): the report is rendered for the superseded assessment and **conspicuously labelled
  `HISTORICAL`** (*superseded by a later assessment*) — never presented as current.
- **Standard revised after the assessment.** The report renders the **pinned** standard code +
  version the assessment used (read from the assessment), not the current one — reproducibility
  (FR-11), consistent with the Risk Agent pinning its inputs.
- **Explanation contains formatting/units.** Reproduced exactly (FR-2); the agent does not
  normalize units, round, or reformat numbers inside the verbatim narrative.

---

## Out of Scope

- **Deciding anything about the bridge** — computing or re-computing a score, re-mapping a severity
  band, judging danger, or writing/re-wording the risk narrative: the **Risk Reasoning Agent's**
  job. This agent renders that agent's finalized verdict; it forms no verdict of its own.
- **Running or re-running engineering calculations** (FFT/RMS/deflection/threshold) — the
  **Structural Analysis Agent's** job. This agent renders calc *results*, never computes them.
- **Validating or cleaning sensor data** — the **Data Collection Agent's** job. This agent trusts
  and renders the validated readings it is given.
- **Publishing, submitting, emailing, or dispatching the report** to a municipality or any external
  party, and applying the human-approval gate to that dispatch — a **downstream Publish/Alert
  concern** (Principle I). This agent produces the document and stops.
- **Interactive / live dashboard charts** — the Next.js dashboard (Recharts/Plotly/D3) owns those;
  this agent renders **static** charts embedded in the document.
- **Maintaining the engineering-standards corpus** — it renders the pinned standard the assessment
  used; curating standards is separate.
- **Clearing a `PENDING_HUMAN_REVIEW` assessment or transitioning it to `FINAL`** — the downstream
  human-review workflow (out of scope for the Risk Agent too). This agent only *reflects* the
  current `review_status`.

This agent only **assembles and renders** finalized facts into an accountable document — never what
those facts *mean*, whether they are *correct*, or what to *do* about them.

---

## Acceptance Criteria

Each is testable against a scenario above.

- **AC-1.** Given a `FINAL` assessment with a full provenance chain, the agent produces a complete
  report document whose score, severity, recommendation, factors, standard, and math results are
  each **equal to** the corresponding finalized source value (no derived or altered number), and
  emits `RENDERED`. *(assemble-only)*
- **AC-2.** The risk `explanation` in the report is **byte-for-byte identical** to the assessment's
  stored explanation; a build that summarizes or re-words it fails. *(verbatim WHY)*
- **AC-2a.** The executive summary may carry **one** severity headline, and it is produced **only**
  by a fixed severity→headline config lookup (same input severity ⇒ same headline), rendered
  alongside the verbatim explanation; a headline produced by a model or a computed phrase, or one
  replacing the verbatim explanation, fails. *(deterministic band-derived headline)*
- **AC-3.** No model/LLM is invoked in producing a report; given identical finalized inputs and
  template config, two renders yield the **same** document content. *(deterministic templating)*
- **AC-4.** The agent renders from rows it **queried by the trigger's scope key** and records the
  versions rendered; by default it uses only **current (non-superseded)** rows. A report built from
  trigger-carried data, or from a superseded row rendered **without** the `HISTORICAL` label, fails.
  *(read-by-identity, current-by-default)*
- **AC-4a.** A report explicitly requested for a **superseded** assessment is rendered and
  **conspicuously labelled `HISTORICAL`** (*superseded by a later assessment*); an unlabelled
  historical render fails. *(regulatory reprint)*
- **AC-5.** When an assembled value matches **no** finalized source row **under exact-match (0.0)**,
  the agent emits `WITHHELD/PROVENANCE_MISMATCH` and **no** document containing that value is
  published. Conversely, a report whose every value equals its source passes the fidelity gate.
  *(fidelity gate, exact-match — positive+negative)*
- **AC-6.** A chart is rendered only from values already in the finalized rows; when a required
  section's content is absent that **section is marked `SECTION_UNAVAILABLE`** while the rest of the
  report still renders; a build that computes a new quantity to chart, fabricates chart data, or
  withholds the whole report over one missing section, fails. *(charts render, don't compute;
  section-unavailable)*
- **AC-7.** A `CRITICAL` / `PENDING_HUMAN_REVIEW` assessment is **rendered immediately** carrying the
  `NOT_FINAL` mark, its recommendation presented as pending review; a report presenting such a
  verdict as settled/final, **or withholding the document until review clears**, fails. *(finality
  honoured — rendered-marked, mandate #3 through the report)*
- **AC-8.** A withheld (no-score) assessment yields a `RENDERED` report marked `SCORE_WITHHELD` +
  `NOT_FINAL` that **states the withheld state and what was missing** (verbatim withheld
  explanation) and shows **no fabricated score/band**; a no-document outcome for a readable withheld
  assessment fails. *(honest withheld report)*
- **AC-9.** A re-render for an assessment produces a **new versioned artifact** with the prior
  report **retained** and linked as superseded — never overwritten. *(append-only artifacts)*
- **AC-10.** A trigger redelivered for an **already-rendered current version** produces **no
  duplicate** report; a render against a **newer (superseded-upstream) version** produces a new
  report that supersedes the prior. *(idempotency)*
- **AC-11.** Each render records the **assessment identity+version, the source-row versions, and the
  template/config version**, such that the report is **reproducible** from those identities after an
  input is later superseded or a standard/limit retuned. *(reproducible audit)*
- **AC-12.** On malformed/partial input (missing assessment, unreadable provenance, absent section
  data) the agent returns a **structured outcome and never throws**; the render is **asynchronous**
  and no **partial** document is ever published. *(never-crash; async; atomic)*
- **AC-13.** This agent performs **no** external dispatch/publication of the report and carries **no**
  `needs_approval` gate on rendering; a build in which it submits a report to an external party fails.
  *(recommendation-only posture; gate is downstream)*

---

## State

The agent is **stateless / triggered-per-assessment**: it keeps no rolling state between triggers,
and its work is defined entirely by the trigger's scope key. Every value it renders is **read from
the system of record** each run (the finalized assessment and its provenance chain). The two
persistent things it relies on are **(a)** the upstream append-only records it reads (owned by the
Risk / Structural-Analysis / Data-Collection agents) and **(b)** its own **append-only report
artifacts**, which it re-reads for **idempotency** (has this assessment version already been
rendered?) and **supersession** (linking a re-render to the prior report). It maintains no cursor,
no cache of report content, and no derived analytical state — consistent with its assemble-only
nature.

---

## Resolved in the clarification interview (no longer open)

The seven behavioural questions the Specify draft flagged are **settled** and folded into the FRs
(see **Settled in clarification interview** above): (1) not-final → **render marked `NOT_FINAL`**,
not hold (FR-7); (2) withheld assessment → **`RENDERED`** marked `SCORE_WITHHELD` (FR-8); (3)
exec-summary → verbatim explanation **plus a fixed band-derived headline** (FR-2); (4) publication →
**out of scope**, a downstream agent owns it (FR-13); (5) missing section → **render, section marked
`SECTION_UNAVAILABLE`** (FR-6); (6) historical reprint → **allowed, labelled `HISTORICAL`** (FR-4);
(7) fidelity match → **exact (0.0)** default (FR-5). What remains below is **not** behavioural
ambiguity — it is config values and `plan.md` design decisions.

## Open Items (config + design; resolve before/at design — not part of "done")

**Config TODOs (supplied later; placeholders until then — do not guess):**
- **Severity→headline lookup table** — the fixed phrases for the exec-summary headline per band
  (FR-2). A wording/policy choice, but a fixed table, not generated text.
- **Fidelity rounding tolerance** — stays exact-match (0.0) until an engineer supplies a tolerance
  (FR-5); do not loosen a safety-relevant match without sign-off (mirrors the Risk Agent's
  guardrail-tolerance TODO).
- **Appendix raw-data depth bound** — how much raw history the appendix includes before it is
  truncated-with-a-note (Edge Cases / FR-6).
- **Report template + letterhead + sign-off config** — the section layout, government branding, and
  sign-off block as configuration, and how the **template version** is stamped for reproducibility
  (FR-11).

**Deferred to `plan.md` (design decisions, not spec behaviour):**
- **Report artifact store + retention** — where rendered PDFs live and for how long (parallel to the
  Risk Agent's trace-store Open Item); the append-only/versioning guarantee (FR-9) holds regardless.
- **Async enqueue + "report ready" notify mechanism** — how the render is queued and how completion
  is signalled to a consumer / the dashboard (research §3; FR-12).
- **Trigger contract** — the exact scope-key shape (assessment id vs. `(bridge_id, cycle_id)`), how
  a **historical reprint** is requested (which distinguishes it from a normal current render, FR-4),
  and delivery guarantees (FR-10, Invocation & Work Intake).
- **PDF/chart rendering libraries** — named in the research (ReportLab; matplotlib/`Agg`) but chosen
  in `plan.md`; the spec is library-agnostic.
- **Provenance-chain read path** — how the agent walks assessment → `source_analysis_ids` → SA rows
  → DCA rows to assemble the sensor tables/appendix, and how much of that chain each section needs.
