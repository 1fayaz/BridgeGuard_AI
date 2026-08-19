# Report Generation Agent (Agent 004)

The **assembly layer** of BridgeGuard. It turns a completed, persisted risk assessment into a
professional, government-ready report (PDF). It is a **deterministic Python service — NOT a
model-calling Agent** (the same Option A as the Data Collection and Structural Analysis agents):
**no model is used anywhere in this package.**

> **It assembles; it does not re-decide.** Every number and every sentence in the report is
> **copied** from an upstream agent's already-finalized output — never recalculated, re-derived, or
> reworded independently. The judgment already happened upstream (the Risk Reasoning Agent); this
> agent renders it faithfully.

## Inputs — read by identity, current-by-default

The trigger carries a thin scope key (`{bridge_id, cycle_id}`, or a specific `assessment_id` for a
historical re-print). The service reads the finalized rows itself, by identity — it is handed no fat
payload, so the document is always a faithful render of the audited record:

| Read port | Source table | Provides |
|-----------|--------------|----------|
| `get_risk_assessment` | `risk_assessments` (0006) | the verdict: score, severity, recommendation, the **verbatim** explanation, review status, provenance |
| `get_analysis_results` | `analysis_results` (0005) | the SA calculation results for the sensor tables + math section |
| `get_validated_readings` | `validated_readings` (0002) | the DCA readings for the time-series charts + raw-data appendix (bounded) |

All reads are **read-only** (they never mutate the upstream Risk/SA/DCA rows) and return the
**current** (non-superseded) row by default; a superseded row is read only for a labelled historical
re-print. A missing row returns a structured signal, never a raise.

## What it produces

One document per finalized assessment, plus a `report_artifacts` row recording what happened. The
outcome vocabulary is closed:

- **`RENDERED`** — a document was produced. It may carry zero or more **marks** (empty ⇒ a clean
  FINAL report):
  - `NOT_FINAL` — the assessment is pending human review or is critical; the report must not be
    consumed downstream as a settled decision.
  - `SCORE_WITHHELD` — the assessment withheld its score; the report is rendered honestly from the
    verbatim withheld explanation, and is also `NOT_FINAL`.
  - `HISTORICAL` — a superseded assessment was rendered (a regulatory re-print).
  - `SECTION_UNAVAILABLE` — a section had no upstream data and prints a conspicuous placeholder.
- **`WITHHELD`** — no document was produced, on purpose. Only two reasons qualify (the cases where
  publishing nothing beats an untraceable number):
  - `ASSESSMENT_NOT_FOUND` — the scope resolves to no assessment.
  - `PROVENANCE_MISMATCH` — a value failed the fidelity gate (see below).
- **`ERROR`** — a structured failure. The service never crashes (FR-12).

## The two rules that keep it honest

1. **Verbatim explanation + fixed headline.** The Risk Agent's explanation is copied **verbatim**
   (byte-for-byte) — re-wording it would create a new, ungoverned narrative that bypasses the
   numeric-provenance guardrail the Risk Agent already passed. The **only** sentence not copied from
   an upstream row is a **fixed** severity→headline phrase, a pure config **lookup** (see
   `config/headline_table.py`) — no model, no computed prose.

2. **The fidelity gate (anti-drift, FR-5).** Before anything is rendered, every value the document
   will print is checked against a fresh authoritative read of the source of record. The match is
   **exact** (tolerance `0.0` by default — the fail-safe). Any value that traces to no source fails
   the gate **fail-closed**: the report is `WITHHELD` with `PROVENANCE_MISMATCH` and **no document
   is written**. A fabricated number can never reach a government artifact.

## Flow (the service entrypoint)

`run_report(scope, …)` wires: resolve assessment → read analysis + readings → assemble (copy-only)
→ **fidelity gate** → render (ReportLab + matplotlib charts, in-process) → determine marks → atomic
persist (`report_artifacts` row + `decision_log` audit). It **always returns a structured
`ReportSummary` and never raises.** The write is atomic — a mid-render failure leaves no partial
artifact.

## Trigger contract

n8n fires **downstream of the Risk Agent**, on a risk-assessment-available signal, and invokes
`run_report` with the scope key. It is **async fire-and-notify**: the build may take 5–30s, so n8n
does not block for it. The workflow is glue only — no assembly/fidelity/marks logic lives in n8n.
Redelivery is safe: the service is idempotent per `(assessment_id, assessment_version)` — a
re-render supersedes, never duplicates.

## Provenance & persistence

Every `report_artifacts` row pins exactly what it rendered, so the document is reproducible even
after its inputs are superseded: `assessment_id` + `assessment_version`, `source_analysis_ids`,
`standard_code` + `standard_version`, and `template_version`. Reports are **append-only** (a
re-render appends + supersedes; the old row is retained, `DELETE` is blocked — Constitution VI). The
audit trail lives in the shared `decision_log` (`REPORT_RENDERED` / `REPORT_WITHHELD` /
`REPORT_ERROR`). Migrations: `0008_report_artifacts.sql`, `0009_decision_log_report_kinds.sql`.

## Out of scope

- **Re-deciding the verdict** — the Risk Agent owns the score/severity/recommendation.
- **Re-calculating the numbers** — the Structural Analysis Agent owns the math.
- **Publishing / dispatching the document** — a separate downstream **Publish/Alert agent** owns
  distribution and its `needs_approval` gate (FR-13). Rendering a PDF harms nothing, so there is no
  `needs_approval` here; the real-world-action chokepoint is **downstream**.

## Configuration

Presentation and safety knobs (the severity→headline phrases, the fidelity tolerance, the appendix
depth bound, the template/letterhead) are **config, not code** — see `CONFIGURING.md`. They stay
`TODO` until a human supplies them; we do not guess values for a safety-critical artifact.
