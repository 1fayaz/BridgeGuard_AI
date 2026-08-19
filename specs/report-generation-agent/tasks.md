# Report Generation Agent — Tasks

**Status:** Draft for review (do not implement until approved)
**Date:** 2026-07-04
**Spec:** `specs/report-generation-agent/spec.md` (13 FR / 15 AC, assemble-only spine)
**Plan:** `specs/report-generation-agent/plan.md` (it is a **deterministic service — NOT an Agents-SDK
Agent**; the DCA/SA counterpart, downstream of the Risk Agent)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.1.0** (Neon/Postgres, standard
indexes only; no model here, so the SDK alias-import rule does not apply)

## Confirmed decisions (acceptance checks reference these + spec ACs)

- **This is a deterministic Python service, no model** — the inverse of Agent 003; same Option A as
  the DCA/SA. **n8n triggers it downstream of the Risk Agent**, **per finalized assessment**; the
  render runs **async fire-and-notify**. **Neon/Postgres** is the store.
- **Assemble, never re-decide (FR-1):** every printed number and sentence is **copied** from a
  finalized upstream row — never recomputed, re-derived, re-mapped, or reworded.
- **The risk explanation is VERBATIM (FR-2)**; the **only** non-copied text is a fixed
  **severity→headline** config lookup (no model, no computed phrase).
- **Read by identity, current-by-default (FR-4):** the trigger carries a scope key; the service
  queries `risk_assessments` (0006) → `analysis_results` (SA 0005) → `validated_readings` (DCA 0002).
  A **historical** (superseded) assessment renders only when the report is labelled `HISTORICAL`.
- **Fidelity gate = exact-match (0.0), fail-closed (FR-5):** every bound value must equal a source
  value; a mismatch → `WITHHELD/PROVENANCE_MISMATCH`, no document written. (Display formatting is
  applied after the exact bind.)
- **Every readable assessment yields a `RENDERED` document with marks** (FR-6/7/8): `NOT_FINAL` ·
  `SCORE_WITHHELD` · `HISTORICAL` · `SECTION_UNAVAILABLE`. The **only** no-document outcomes are
  `WITHHELD/ASSESSMENT_NOT_FOUND` and `WITHHELD/PROVENANCE_MISMATCH`.
- **Append-only versioned artifacts (FR-9), idempotent per assessment version (FR-10)**; reproducible
  from pinned assessment/source/template versions (FR-11).
- **Never crashes; async; atomic write (FR-12).** **No publication here** — a downstream Publish/Alert
  agent owns dispatch + its `needs_approval` gate (FR-13).
- **All config values** — the severity→headline table, the fidelity tolerance, the appendix depth
  bound, the report template/letterhead — stay **`TODO`-marked config** (do not guess).

## Conventions

- Each task is < 1 hour and **independently verifiable**; acceptance checks are concrete (tied to an
  FR/AC or a decision above), never "works correctly". Same granularity as the DCA/SA/Risk builds.
- **[DB-DEP]** = needs live Neon to fully verify; built/verified against an in-memory fake now, live
  verification honestly deferred (no Neon instance locally). Same pattern the DCA/SA/Risk fakes use.
- **[RENDER-DEP]** = needs the real PDF/chart libraries (**ReportLab**, **matplotlib/`Agg`**) to
  produce actual bytes; **neither is installed today**. Built/verified against a **fake renderer**
  (a `RenderPort` seam that records the assembled report model) + structural assertions now; live
  byte generation deferred, flagged not faked. The assembly, fidelity gate, marks, persistence,
  idempotency, and service logic are all testable **without** a live renderer — only the genuine PDF
  emission is [RENDER-DEP].
- Constitution gates: never crash → always emit a structured `ReportSummary`, incl. the withheld
  outcomes (FR-12); reads never mutate Risk/SA/DCA tables; **no model in any path** (Principle IV —
  assert the assembly/service graph imports no model/SDK); every printed number binds exactly to a
  source value (FR-5).
- **Reuse proven patterns:** the DCA/SA/Risk `statuses.py` enum style, the `FakeStore` mirror, and
  the append-+-supersede triggers from `validated_readings` (0002) / `risk_assessments` (0006).
- **Task prefix `G`** (Report **G**eneration), to avoid collision with DCA `T`, SA `S`, Risk `R`.

---

## Phase 1 — Config (headline table, template, fidelity tolerance, appendix bound — config not code)

- **G101 — `ReportConfig` shape (template + appendix bound + fidelity tolerance).**
  Fields: `report_template_version` (concrete, for audit), `appendix_max_rows` (**TODO** sentinel —
  raw-data depth bound), `fidelity_tolerance` (=0.0 exact-match default, the fail-safe), plus
  template/letterhead references (**TODO**). NaN/sentinel discipline for any unset value, same as
  the Risk `ScoreConfig`.
  **Acceptance:** constructs; `report_template_version` is concrete; `fidelity_tolerance` defaults
  `0.0`; `appendix_max_rows` and the template refs are clearly-flagged `TODO` sentinels a reviewer
  sees are unset; an `is_fully_configured` property is False while any is unset. (do-not-guess)

- **G102 — `HeadlineTable` (severity→headline lookup, FR-2).**
  A fixed mapping `severity → headline phrase` (config, not code): `SAFE|WATCH|WARNING|CRITICAL →
  TODO phrase`. Pure lookup; a severity with no configured phrase returns a clearly-unset sentinel,
  never a guessed phrase. Withheld (no severity) → a distinct withheld-headline sentinel.
  **Acceptance:** every band maps to exactly its configured phrase (or a flagged `TODO` sentinel);
  the same severity always yields the same headline (deterministic); no model/computation is
  involved (pure dict lookup); an unknown/absent severity is not guessed. = FR-2 (headline half).

---

## Phase 2 — Output vocabulary + schema [DB-DEP]

- **G201 — `report_statuses.py` (closed vocabulary).**
  `ReportOutcome` enum (`RENDERED | WITHHELD | ERROR`); `DocumentMark` enum (`NOT_FINAL |
  SCORE_WITHHELD | HISTORICAL | SECTION_UNAVAILABLE`); `WithheldReason` enum
  (`ASSESSMENT_NOT_FOUND | PROVENANCE_MISMATCH`). Mirrors the DCA/SA/Risk `statuses.py` style + the
  SQL enums (G203).
  **Acceptance:** all three outcomes, all four marks, both withheld reasons representable; a
  `RENDERED` result may carry zero-or-more marks (empty ⇒ clean FINAL); a `WITHHELD` result carries
  exactly one reason; matches the spec Outcome Vocabulary.

- **G202 — Output payload shape (typed `ReportResult` + `ReportSummary`).**
  Frozen dataclasses: `ReportResult` (bridge_id, cycle_id, assessment_id, assessment_version,
  outcome, marks tuple, withheld_reason, artifact_ref, source_analysis_ids, standard_code+version,
  template_version, rendered_at-seam); `ReportSummary` (the plain dict the service returns to n8n:
  ok, outcome, marks, withheld_reason/error). Withheld → artifact_ref None + a reason.
  **Acceptance:** constructs typed; a `RENDERED` result carries an artifact_ref + its marks + pinned
  provenance; a `WITHHELD` result carries no artifact_ref and a reason; `__post_init__` enforces
  the coherent shapes (RENDERED⇒artifact_ref present; WITHHELD⇒reason present, artifact_ref None).
  = spec output contract.

- **G203 — `report_artifacts` table (append-+-supersede) [DB-DEP].**
  Migration **`0008_report_artifacts.sql`** per plan §3b: `id`, `bridge_id`, `cycle_id`,
  `assessment_id`, `assessment_version`, `rendered_at`, `outcome` (enum), `marks` (enum array or
  boolean set — sign-off), `withheld_reason` (enum, NULL unless WITHHELD), `artifact_ref`,
  `source_analysis_ids BIGINT[]`, `standard_code`, `standard_version`, `template_version`,
  `superseded_by`. Same BEFORE-UPDATE guard (only `superseded_by` mutable) + DELETE-block triggers
  as `risk_assessments` (0006). Partial unique index on `(assessment_id, assessment_version)` WHERE
  `superseded_by IS NULL` (idempotency, standard Postgres index — no TimescaleDB).
  **Acceptance:** enums representable; a `WITHHELD` row allows NULL artifact_ref but requires a
  `withheld_reason` (CHECK); a `RENDERED` row requires an artifact_ref (CHECK); mutating
  outcome/marks/artifact of an existing row is blocked (correct-by-append); DELETE revoked;
  uniqueness on `(assessment_id, assessment_version)` among current rows. [DB-DEP live enforcement
  deferred.]

- **G204 — Audit: extend `decision_log` enum [DB-DEP].**
  Migration **`0009_decision_log_report_kinds.sql`**: add `REPORT_RENDERED | REPORT_WITHHELD |
  REPORT_ERROR` to `decision_kind` (one shared cross-agent audit trail, per plan §5). Header notes
  `ALTER TYPE ADD VALUE` cannot run in a transaction block (same as 0007).
  **Acceptance:** the 3 new kinds representable alongside the DCA/SA/Risk kinds; a `REPORT_WITHHELD`
  row records the withheld reason; a `REPORT_RENDERED` row records which assessment version rendered.
  [DB-DEP deferred.]

---

## Phase 3 — The read ports (read finalized rows by identity, current-by-default) [DB-DEP]

- **G301 — `get_risk_assessment(scope_key, *, historical=False)` (read-only).**
  Reads the finalized `risk_assessments` row the scope key resolves to — the **current**
  (non-superseded) row by default; a specific **superseded** row **by id** when `historical=True`.
  Returns the full verdict + provenance; missing → structured `ASSESSMENT_NOT_FOUND` signal (not a
  raise). Never writes.
  **Acceptance (fake store):** current scope → the current row; `historical=True` + id → that
  superseded row; absent → `ASSESSMENT_NOT_FOUND` signal, no raise; the call performs **no**
  mutation (assert store unchanged). = FR-4, Const. III read-only. [DB-DEP live deferred.]

- **G302 — `get_analysis_results(source_analysis_ids)` (read-only).**
  Reads the SA `analysis_results` rows named by the assessment's `source_analysis_ids` (current
  versions), for the sensor tables + math-results section. Missing/empty → structured "results
  unavailable" signal (drives `SECTION_UNAVAILABLE`, not a raise). Never writes.
  **Acceptance (fake store):** returns the referenced current rows; a missing id → the section-gap
  signal (no fabrication); no mutation. = FR-4/FR-6. [DB-DEP live deferred.]

- **G303 — `get_validated_readings(source_validated_ids, *, max_rows)` (read-only).**
  Reads DCA `validated_readings` (via the analysis rows' provenance) for the time-series tables/
  charts + appendix, **bounded to `max_rows`** (appendix depth bound, config). Missing → section-gap
  signal. Never writes.
  **Acceptance (fake store):** returns the referenced readings up to `max_rows` (bound honoured,
  truncation flagged); missing → gap signal; no mutation. = FR-4/FR-6, appendix bound. [DB-DEP.]

- **G304 — Test the three reads read-only + structured-missing (FR-4, AC-4).**
  **Acceptance:** each read returns its typed result against the fake store; each leaves all stores
  unmutated (assert before==after); each returns a structured signal (not a raise) on missing data;
  a superseded row is only returned under `historical=True`. = AC-4 (read-by-identity, current-only).

---

## Phase 4 — Assembly (build the report model from finalized rows) + test

- **G401 — `ReportModel` shape (the assembled, pre-render document model).**
  Frozen dataclass: cover fields (bridge_id, assessment_id, severity, rendered_at-seam),
  exec-summary (the **verbatim** explanation + the headline from G102), the score/severity/
  recommendation block, the sensor/math tables (from G302), the chart-data blocks (from G303), the
  standards-comparison block (pinned code+version), the appendix rows, and a per-section
  `available` flag. Every value slot carries the **source reference** it was copied from (for the
  fidelity gate, G501).
  **Acceptance:** constructs typed from finalized rows; each value slot records its source ref; a
  section with no upstream content is marked `available=False` (not omitted, not faked). = FR-1 shape.

- **G402 — `assemble_report(assessment, analysis, readings, config)` (pure).**
  Build a `ReportModel` by **copying** finalized values into slots: the verbatim explanation, the
  band headline (G102 lookup), the score/severity/recommendation as-is, tables/charts/appendix from
  the reads, the pinned standard. **No recomputation, re-derivation, re-mapping, or rewording** —
  each slot's value is a copy + its source ref. A missing section → `available=False`.
  **Acceptance:** every populated slot's value **equals** its source value (assert equality against
  the input rows); the explanation slot is **byte-identical** to `assessment.explanation`; the
  headline is exactly `HeadlineTable[severity]`; no slot value is computed/derived; a missing-input
  section is `available=False`. = FR-1/FR-2/FR-6, AC-1/AC-2/AC-2a.

- **G403 — Test assembly copies-not-computes + verbatim (FR-1, FR-2, AC-1/AC-2/AC-2a).**
  **Acceptance:** drives G402 over fake finalized rows: score/severity/recommendation/factors/
  standard/math each equal the source (assemble-only); the explanation is byte-for-byte identical;
  the headline is the fixed lookup (and changes only if the config table changes, not the data); a
  build that alters the explanation or computes a slot fails. **No model involved** — assert the
  assembly graph imports no model/SDK (ast import-root check, mirroring Risk R303).

---

## Phase 5 — Fidelity gate (exact-match anti-drift, FR-5) + test

- **G501 — `fidelity_check(report_model, source_index, tolerance)` (pure).**
  For every value slot in the `ReportModel`, verify it **equals** a value in the finalized source
  rows it references, under `tolerance` (default `0.0` exact). Return pass / the list of offending
  (slot, value) pairs that matched no source value. Pure decision function; display formatting is
  **not** applied here (the bound value is compared raw).
  **Acceptance:** a model whose every slot traces → pass; a model with a slot value absent from any
  source row → fail, naming the offending slot+value; a value within `0.0` (exact) of a source value
  → pass; a value differing only by display formatting is compared on its **bound** (raw) value, not
  its formatted string; tolerance comes from config. = FR-5, AC-5 (positive + negative).

- **G502 — Test fidelity fail-closed (FR-5, AC-5).**
  **Acceptance:** an assembled model with a deliberately **injected off-book number** (a value in no
  source row) trips the gate → the service (G901) yields `WITHHELD/PROVENANCE_MISMATCH` and **no
  artifact is written**; a clean model passes and proceeds to render. The fabricated value is
  **never** emitted into a document. = AC-5, the report-layer anti-drift control.

---

## Phase 6 — Rendering (charts + PDF, section-unavailable, atomic) [RENDER-DEP]

- **G601 — `RenderPort` seam + `FakeRenderer` (deterministic stub).**
  Define the render port the service calls (`render(report_model) → artifact bytes/ref`), and a
  `FakeRenderer` that records the `ReportModel` it was handed and returns a deterministic fake ref —
  so Phases 4/5/7/8/9 are fully testable without ReportLab/matplotlib. Mirrors the Risk
  `FakeReasoningModel` seam.
  **Acceptance:** the fake records the exact model handed to it and returns a stable ref; swapping in
  the real renderer changes only the produced **bytes**, not the control flow (assembly/gate/marks/
  persistence unchanged). = [RENDER-DEP] seam.

- **G602 — `chart_images(report_model)` (matplotlib/`Agg`) [RENDER-DEP].**
  Render each chart-data block to a static PNG buffer via matplotlib's headless `Agg` backend (no
  browser). A chart whose data block is `available=False` is **skipped and its section marked
  unavailable**, never drawn empty. Charts plot **only** values already in the model (no new
  quantity computed).
  **Acceptance (against the seam / structural):** each available chart block yields a PNG buffer;
  an unavailable block yields no image and a `SECTION_UNAVAILABLE` mark; no chart derives a new
  analytical quantity (assert only model values are plotted). = FR-6, AC-6. [RENDER-DEP live bytes
  deferred — matplotlib not installed.]

- **G603 — `render_pdf(report_model, chart_images)` (ReportLab) [RENDER-DEP].**
  Assemble the multi-page PDF (cover → exec summary → tables → charts → math → recommendations →
  appendix → sign-off) via ReportLab from the model + chart images; sections marked unavailable
  render a conspicuous "data unavailable" block. **In-process, no sandbox** (plan §1). Caps page/
  row counts (appendix bound).
  **Acceptance (structural / against the seam):** produces an artifact from the model; every printed
  value is one already in the (gate-passed) model; an unavailable section renders the marked block,
  not fabricated content; runs in-process (no E2B/shell-out). = FR-6, research §1. [RENDER-DEP live
  bytes deferred — ReportLab not installed.]

---

## Phase 7 — Marks determination (FR-4/6/7/8) + test

- **G701 — `determine_marks(assessment, sections)` (pure).**
  Compute the `RENDERED` document marks: `NOT_FINAL` when `review_status == PENDING_HUMAN_REVIEW`
  **or** `severity == CRITICAL`; `SCORE_WITHHELD` when the assessment withheld its score (and then
  `NOT_FINAL` too); `HISTORICAL` when a superseded row was rendered; `SECTION_UNAVAILABLE` when any
  required section is `available=False`. Pure; empty set ⇒ a clean `FINAL` report.
  **Acceptance:** a FINAL scored assessment → no marks (clean FINAL); a CRITICAL/PENDING → `NOT_FINAL`;
  a withheld → `SCORE_WITHHELD`+`NOT_FINAL`; a historical render → `HISTORICAL`; a missing section →
  `SECTION_UNAVAILABLE`; marks compose (e.g. historical + not-final). = FR-4/6/7/8.

- **G702 — Test marks + not-final-never-settled (FR-7, AC-7; FR-8, AC-8).**
  **Acceptance:** a `CRITICAL`/`PENDING_HUMAN_REVIEW` assessment → the report carries `NOT_FINAL`
  and the recommendation is presented as pending (never as settled/final); a withheld assessment →
  a `RENDERED` report marked `SCORE_WITHHELD`+`NOT_FINAL` using the **verbatim withheld explanation**,
  no fabricated score; a downstream consumer stand-in **holds** a `NOT_FINAL` report (does not treat
  it as final). = AC-7, AC-8, mandate #3 through the report.

---

## Phase 8 — Persistence + audit (Neon) [DB-DEP]

- **G801 — `FakeReportStore` mirroring G203/G204 guarantees.**
  In-memory store: append `report_artifacts`, supersede (only `superseded_by`), block delete,
  enforce `(assessment_id, assessment_version)` current-row uniqueness, append audit. Mirrors the
  `risk_assessments`/`validated_readings` fakes.
  **Acceptance:** insert assigns id; supersede links old→new and never mutates outcome/marks/
  artifact; delete blocked; a duplicate `(assessment_id, assessment_version)` among current rows is
  rejected/no-op (idempotency). = G203 guarantees in-memory.

- **G802 — `persist_report(store, result, audit)` [DB-DEP].**
  Write one `report_artifacts` row (rendered or withheld), linking `assessment_id`+version +
  `source_analysis_ids` + `standard_code`/version + `template_version`; append the matching audit
  row (`REPORT_RENDERED | REPORT_WITHHELD | REPORT_ERROR`). Auto-supersedes an existing current row
  for the same `(assessment_id, assessment_version)` (idempotent by scope).
  **Acceptance (fake store):** a rendered report, a withheld (`PROVENANCE_MISMATCH`) report, and an
  error each produce exactly the expected row + audit kind; every row links its pinned provenance;
  a re-persist for the same assessment version supersedes (no duplicate). = FR-9/FR-11, AC-9.
  [DB-DEP live deferred.]

- **G803 — Idempotency + reproducibility test (FR-9/FR-10/FR-11, AC-9/AC-10/AC-11) [DB-DEP].**
  **Acceptance (fake store):** a redelivered trigger for an **already-rendered current version** →
  **no duplicate** artifact (no-op); a render against a **newer** assessment version → a new row
  that **supersedes** (append+link old), never overwrites; a rendered report records exactly which
  assessment version + source versions + template version it used, so it is reproducible from those
  identities after an input is later superseded. = AC-9, AC-10, AC-11.

---

## Phase 9 — The service (assemble + gate + render + persist) + never-crash test

- **G901 — `run_report(scope_key, *, store, config, renderer, historical=False)` (orchestrator).**
  Wire the per-report flow (plan §6): (1) resolve the assessment (G301) — absent →
  `WITHHELD/ASSESSMENT_NOT_FOUND`, stop; (2) read analysis + readings (G302/G303); (3) assemble the
  model (G402); (4) fidelity gate (G501) — fail → `WITHHELD/PROVENANCE_MISMATCH`, no artifact, stop;
  (5) render (G602/G603 via the port); (6) determine marks (G701); (7) atomic write: persist artifact
  + `report_artifacts` row + `decision_log` (G802); (8) return a `ReportSummary`. Per-report failure
  isolation → structured status, **never raises** (FR-12).
  **Acceptance:** a normal FINAL scope → `RENDERED` (no marks) + a persisted artifact; a
  pending/critical → `RENDERED`+`NOT_FINAL`; a withheld-score → `RENDERED`+`SCORE_WITHHELD`; an
  off-book number → `WITHHELD/PROVENANCE_MISMATCH` (no artifact); a missing assessment →
  `WITHHELD/ASSESSMENT_NOT_FOUND`; an injected renderer/read exception → a structured `ERROR`
  summary, nothing raises out (FR-12). = FR-1/FR-12, AC-1/AC-12.

- **G902 — Never-crash + atomicity test (FR-12, AC-12).**
  **Acceptance:** the four-scenario constitution set — normal / missing assessment / unreadable
  provenance / malformed scope key — each returns a **structured** `ReportSummary` and **never
  throws**; on a mid-render failure **no partial artifact** is persisted (atomic: the row + artifact
  appear together or not at all). = AC-12 (never-crash; async-shaped; atomic).

---

## Phase 10 — Trigger wiring (n8n, downstream of Risk, fire-and-notify)

- **G1001 — n8n workflow definition (glue only, downstream of Risk).**
  `n8n/report_generation.workflow.json`: fires **on risk-assessment-available** for a bridge,
  invokes `run_report` with the scope key, retries the **trigger**, branches on the structured `ok`,
  and routes the **report-ready** signal. **No assembly/fidelity/marks logic in n8n.** Fire-and-
  notify (does not block for the render).
  **Acceptance:** workflow doc/export exists; risk-assessment-available → invoke path described per
  bridge; invoke carries the scope key + retries; branches only on `ok` (never on marks/outcome
  internals); contains **no** assembly/render/judgment logic (Const. III); `meta` self-declares glue
  only. [n8n/Neon live verification deferred — none locally.] Mirrors the DCA/Risk glue workflows.

---

## Phase 11 — End-to-end test (every spec AC)

- **G1101 — Scenario harness (fake store + fake renderer).**
  Scripted inputs covering: FINAL scored, CRITICAL/pending, withheld-score, historical reprint,
  a missing section, an off-book number (→ fidelity fail-closed), a re-render (supersede), a
  redelivered trigger (idempotent no-op), and a malformed scope key (never-crash). Deterministic and
  replayable (no clock/random); the shared fixture G1102 drives. Mirrors the Risk R1101 harness.
  **Acceptance:** every named scenario present; each yields its documented outcome+marks; replaying
  the catalog twice gives identical summaries.

- **G1102 — E2E asserting AC-1…AC-13 (+ AC-2a, AC-4a).**
  **Acceptance:** drive reports through the real service; assert each AC manifests in
  `report_artifacts` + audit: AC-1 assemble-only equals-source · AC-2 verbatim explanation · AC-2a
  band headline is a fixed lookup · AC-3 no model / deterministic · AC-4 read-by-identity current ·
  AC-4a historical labelled · AC-5 fidelity fail-closed (pos+neg) · AC-6 charts render / section-
  unavailable · AC-7 not-final marked · AC-8 honest withheld report · AC-9 append-only artifacts ·
  AC-10 idempotency · AC-11 reproducible · AC-12 never-crash 4-scenario · AC-13 no dispatch/no
  `needs_approval`. = **all spec ACs**.

- **G1103 — Constitution check test.**
  **Acceptance:** never-crash (malformed/partial → structured outcome, not raise); reads never
  mutate Risk/SA/DCA tables; every printed number binds exactly to a source value (FR-5); **no model
  in any path** (assert the assembly + service import graph pulls in no model/SDK root — ast check,
  mirroring Risk R1103); no dispatch/publication tool and no `needs_approval` present (gate is
  downstream). = Const. I/II/III/IV/VI.

---

## Phase 12 — README (module docs)

- **G1201 — Module README.**
  Inputs (the finalized rows read by identity + what each provides), outputs (the report + the
  closed outcome/mark vocabulary + the `report_artifacts` provenance), the **assemble-not-re-decide**
  invariant, the verbatim-explanation + fixed-headline rule, the fidelity gate (exact-match fail-
  closed), the async fire-and-notify trigger contract (downstream of Risk), and explicit out-of-scope
  (no re-deciding → Risk owns the verdict; no re-calculating → SA; no publishing → downstream
  Publish/Alert agent owns the gate).
  **Acceptance:** README present; documents inputs, outputs, the assemble-only invariant, the
  fidelity gate, and the trigger; matches the implemented contract. (Mirrors the DCA/Risk READMEs.)

- **G1202 — "Change the report template / headline / bounds via config only" guide.**
  Step-by-step: change the report template/letterhead, the severity→headline table, the appendix
  depth bound, and the fidelity tolerance **without** touching assembly, gate, render, or service
  code.
  **Acceptance:** changing a template/headline/bound/tolerance requires only config edits; validates
  "presentation + safety numbers are config, not code" (and that they remain `TODO` until supplied).

---

## Dependency Order

```
P1 (config) ─┐
P2 (vocab + schema) ─┴─► P3 reads, P4 assembly, P5 fidelity (parallel after P1/P2)
                          P6 (render seam + libs) ─┐
                                                   ▼
                          P7 (marks) ─► P9 (the service: reads + assemble + gate + render + persist)
                          P8 (persistence) ─────────┘
                                                   └─► P10 (n8n trigger)
                                                         └─► P11 (E2E) ─► P12 (README)
```
- P4 (assembly) + P5 (fidelity) are pure and testable before the renderer exists (fake renderer in P6).
- P9 assembles P3 + P4 + P5 + P6 + P7 + P8; P8 mirrors the DCA/SA/Risk FakeStore.
- P11 requires P7–P9 (+P10 for the trigger path).

## Coverage (tasks ↔ acceptance criteria / decisions)

| AC / Decision | Tasks |
|---------------|-------|
| AC-1 assemble-only equals source | G402, G403, G901, G1102 |
| AC-2 verbatim explanation | G402, G403, G1102 |
| AC-2a fixed band headline | G102, G402, G403, G1102 |
| AC-3 deterministic / no model | G403, G1103, G1102 |
| AC-4 read-by-identity, current-only | G301, G304, G1102 |
| AC-4a historical labelled | G301, G701, G1102 |
| AC-5 fidelity gate (exact, fail-closed) | G501, G502, G1102 |
| AC-6 charts render / section-unavailable | G302, G602, G701, G1102 |
| AC-7 not-final marked, never settled | G701, G702, G1102 |
| AC-8 honest withheld report | G701, G702, G1102 |
| AC-9 append-only artifacts | G801, G802, G803, G1102 |
| AC-10 idempotency | G801, G803, G1102 |
| AC-11 reproducible | G802, G803, G1102 |
| AC-12 never-crash 4-scenario | G901, G902, G1103, G1102 |
| AC-13 no dispatch / no needs_approval | G1103, G1102 |
| No model in any path (Principle IV) | G403, G1103 |
| Reads Risk/SA/DCA tables unchanged / new table only | G203, G301, G1103 |
| Const. II/VI traceable + append-only | G203, G801, G802 |
| Marks vocabulary (RENDERED + marks) | G201, G701 |

## Open (non-blocking) — carried config TODOs + design/cross-agent items

- **Severity→headline table, fidelity tolerance, appendix depth bound, report template/letterhead**
  (`TODO` in G101/G102): logic buildable; only the config values/phrases change. Do not guess.
- **`report_artifacts` schema sign-off (G203):** the `marks` representation (enum array vs. booleans),
  the outcome/withheld_reason enums, the idempotency key, the append+supersede triggers.
- **Artifact store + retention (design, plan §5):** Neon `bytea` vs. object storage + URL row, and
  the government retention policy. Append-only/versioning (FR-9) holds regardless.
- **Async enqueue + "report ready" notify mechanism (design, plan §6):** n8n queue vs. a jobs table;
  how the signal reaches the dashboard / a downstream Publish step.
- **Trigger contract (design):** exact scope-key shape (assessment id vs. `(bridge_id, cycle_id)`)
  and **how a historical reprint is requested** (distinguishes it from a current render).
- **Provenance-chain read path (design):** how the service walks assessment → `source_analysis_ids`
  → SA rows → `source_validated_ids` → DCA rows for the tables/appendix.
- **Publish/Alert chokepoint confirmation (cross-agent):** verify a downstream Publish/Alert agent is
  the single un-bypassable `needs_approval` point for report **submission** (FR-13).
- **Dashboard consumption (cross-agent):** whether the Next.js dashboard reads `report_artifacts` to
  surface/download reports.
- **[DB-DEP] / [RENDER-DEP] / n8n-live:** G203/G204/G802 schema + G602/G603 real bytes + G1001 n8n
  path need live Neon + ReportLab/matplotlib + n8n. Built against fakes now (fake store + fake
  renderer), live verification deferred — **flagged, not faked**. Neither ReportLab nor matplotlib is
  installed today.
```
