# Alert & Escalation Agent (Agent 005)

The **real-world-action layer** of BridgeGuard, and the system's **single chokepoint** to the
outside world. It takes a completed, persisted risk verdict and decides whether — and how — to put
it in front of a human: dashboard-only, an auto-fired internal notification, or a dispatch that a
human must approve first. It is a **deterministic Python service — NOT a model-calling Agent** (the
same Option A as the Data Collection, Structural Analysis, and Report agents): **no model is used
anywhere in this package.**

> **It notifies and escalates; it does not re-judge.** The score, severity, recommendation, and the
> written explanation were already decided and audited by the Risk Reasoning Agent (Agent 003).
> This agent copies that verdict **verbatim** into a fixed per-band template and routes it — it
> never recomputes, re-maps the severity, or re-words the explanation. Doing so would create a new,
> ungoverned statement that never passed the Risk Agent's numeric-provenance guardrail.

## Inputs — read by identity, current-by-default

The trigger carries a thin scope key (`{bridge_id, cycle_id}`, or a specific `assessment_id` for a
historical read). The service reads the finalized verdict itself, **by identity** — it is handed no
fat payload, so the alert is always a faithful relay of the audited record:

| Read port | Source table | Provides |
|-----------|--------------|----------|
| `get_risk_assessment` | `risk_assessments` (0006) | the verdict: `risk_score`, `severity`, `recommendation`, the **verbatim** `explanation`, `review_status`, and the pinned provenance (`assessment_id`, `assessment_version`, `trace_id`) |

The read is **read-only** (it never mutates the upstream `risk_assessments` row) and returns the
**current** (non-superseded) verdict by default; a superseded row is read only for a historical
replay. A missing verdict returns a structured `ASSESSMENT_NOT_FOUND` signal, never a raise. The
read tool is the **same** `get_risk_assessment` the Report agent uses — reused, not forked, so there
is one reader of the verdict across the system.

## What it produces

One `alert_dispatches` row per dispatch attempt, plus a `decision_log` audit entry, and a structured
`DispatchSummary` returned to the caller. The vocabulary is closed:

- **DispatchDecision** — the resolved tier: `DASHBOARD_ONLY` (no outbound push), `AUTO_FIRE`
  (dispatched without human approval), `NEEDS_APPROVAL` (blocked until a human signs off).
- **DeliveryState** — where a dispatch is on the wire: `QUEUED`, `SENT`, `DELIVERED`, `FAILED`,
  `ACKNOWLEDGED`. **`SENT` (the provider accepted it) is NOT `DELIVERED` (a receipt confirmed it) is
  NOT `ACKNOWLEDGED` (a human confirmed it)** — three distinct, reconciled states.
- **EscalationState** — where the escalation ladder is: `OPEN`, `ESCALATED`, `CLOSED`.
- **ApprovalState** — the human sign-off on a gated dispatch: `AWAITING_APPROVAL`, `APPROVED`,
  `REJECTED`.
- **WithheldReason** — the only cases where dispatching nothing is correct: `ASSESSMENT_NOT_FOUND`
  (the scope resolves to no verdict) and `CONSISTENCY_MISMATCH` (the message contradicts the
  verdict).

## The settled severity → approval mapping

The clarification interview settled exactly which severities need human approval; this table is the
one place that mapping lives (`tiering.py`), and it is not left to an implementer guess:

| Band | Decision | Notes |
|------|----------|-------|
| `SAFE` | `DASHBOARD_ONLY` | routine monitoring — recorded on the dashboard/timeline, **no** outbound push |
| `WATCH` (FINAL, internal) | `AUTO_FIRE` | an internal notification, no human approval needed |
| `WARNING` | `NEEDS_APPROVAL` | a human signs off before dispatch |
| `CRITICAL` | `NEEDS_APPROVAL` | a human signs off before dispatch |

Two overrides sit on top of the band default and can only **raise** the gate, never lower it:

- **Blast-radius override** — any **authority-facing** recipient (a closure/authority contact)
  forces `NEEDS_APPROVAL` regardless of band.
- **Finality override** — a `PENDING_HUMAN_REVIEW` verdict is **never** `AUTO_FIRE` at any band.
- A withheld-score verdict (no band) is `NEEDS_APPROVAL` — a human must see it.

These are **two orthogonal HITL axes**: `review_status` (finality, set upstream by Risk) and the
dispatch `approval` gate (set here). Both must permit before an alert auto-fires.

## The single un-bypassable `needs_approval` chokepoint

This agent is the **inverse** of every upstream agent. The Report agent proves it has **no**
`needs_approval` / dispatch anywhere, because the chokepoint is downstream — **here**. This agent:

- **defines** the `needs_approval` gate (`approval.py`), and it **enforces** — a `NEEDS_APPROVAL`
  dispatch is held (`AWAITING_APPROVAL`, nothing sent) until a human approval with an identified
  approver is recorded; there is **no code path** that dispatches a gated action un-approved;
- is the **single** un-bypassable real-world-action point — no other agent package defines a
  notify/dispatch path (asserted structurally in the constitution test).

## The consistency gate (fail-closed)

Before any dispatch, `consistency.py` verifies the assembled message does not **contradict** the
verdict it relays: the message's band must equal the verdict's severity, and a `PENDING_HUMAN_REVIEW`
verdict must not be presented as settled/final. A contradiction **fails closed** — the alert is
withheld (`CONSISTENCY_MISMATCH`) and dispatched to nobody. An engineer never receives an alert that
misstates the record.

## Escalation — the severity-dependent close

Delivery is not acknowledgement, and "sent" is not "delivered." The escalation ladder
(`escalation.py`) closes on a **severity-dependent** condition:

- **SAFE / WATCH** → `CLOSED` on a **DELIVERED** receipt.
- **WARNING / CRITICAL** (and a withheld-score verdict) → stay `OPEN` / `ESCALATED` until a recorded
  human **ACK**; a `DELIVERED`-without-ACK does **not** close them.

On a send `FAILED` or no timely delivery, the ladder **retries** the channel, **fails over** to the
next contact, then **escalates** to the on-call chain — every attempt a logged `alert_dispatches`
row, so no failure is silent.

## How it's triggered

**Downstream of the Risk Agent**, fired per finalized assessment. n8n
(`n8n/alert_escalation.workflow.json`) is glue: on a risk-assessment-available signal it invokes the
service entrypoint `run_alert(scope)` with the scope key, retries the *trigger*, branches only on the
structured `ok`, and forwards delivery/ack callbacks back to advance `delivery_state`. It is
**fire-and-notify (async)** — a gated alert may wait on a human approval or a delivery/ack, so n8n
does not block for it. All tiering, gating, dispatch, and escalation logic lives in the Python
service, never in the glue.

## Provenance & migrations

Every `alert_dispatches` row pins the verdict it acted on — `assessment_id`, `assessment_version`,
and the upstream `trace_id` — plus the approver on a gated dispatch, so a dispatch is reproducible
after the verdict is later superseded. Rows are **append-only** and correction-by-supersede; DELETE
is blocked (a dispatch history a regulator relies on is permanent). Migrations:
`db/migrations/0010_alert_dispatches.sql` (the table + enums + guard/DELETE-block triggers) and
`0011_decision_log_alert_kinds.sql` (the `ALERT_DISPATCHED` / `ALERT_ESCALATED` / `ALERT_WITHHELD` /
`ALERT_ERROR` audit kinds in the shared `decision_log`).

## Out of scope

- **No re-judging.** The score/severity/recommendation/explanation are the Risk Agent's; this agent
  relays them verbatim and never recomputes them.
- **No report authoring.** The government PDF is the Report agent's; this agent sends short alerts,
  not documents.
- **The human-review-clearing workflow** (moving a verdict `PENDING_HUMAN_REVIEW → FINAL`), the
  concrete approval UI/queue, and the acknowledgement mechanism are **downstream** — this agent
  enforces the gate in code and records the approver, but does not own the human interface.

## No model

There is **no model** anywhere in this package: tiering, message assembly (a fixed severity→template
lookup + verbatim copy), the consistency gate, the approval gate, and escalation are all
deterministic and reproducible. Determinism is the only shape that cannot drift from the finalized
verdict — using an LLM here would be the violation Principle IV forbids.
