# Alert & Escalation Agent — Specification

**Status:** Clarified (behaviour-only; research-agent-005 + clarification interview folded in —
the severity→approval mapping, the escalation close condition, and the low-band output are
**settled explicitly**, not left as implementer guesses)
**Date:** 2026-07-09
**Anchors:** `CLAUDE.md` (alert dispatch is a `needs_approval`-gated real-world action; prefer SDK
primitives — guardrails, tracing; trace-from-day-one); `.specify/memory/constitution.md` v2.1.0
(Principles I human-in-the-loop, II data-immutable, III modular contracts, IV
reliability-over-cleverness, V testability, VI auditability, VII trace);
`skills/bridgeguard-skills-README.md` (bands SAFE 0–30 / WATCH 31–60 / WARNING 61–80 / CRITICAL
81–100 + their actions; "Alert timeline" visual-output); `specs/risk-reasoning-agent/spec.md`
(FR-5 "the gate lives downstream **here**"; FR-11 CRITICAL → `PENDING_HUMAN_REVIEW`);
`db/migrations/0006_risk_assessments.sql` (the verdict row this agent consumes);
`specs/alert-escalation-agent/research-agent-005.md` (research).

> **Behaviour only.** This spec describes WHAT the agent does and WHY — no databases, frameworks,
> SDK class names, model IDs, or file layout. Those are design decisions made later (`plan.md`).

---

## Goal

This agent is the **real-world-action chokepoint** of BridgeGuard. It consumes a completed,
persisted risk assessment (the Risk Agent's verdict — score, severity, recommendation, verbatim
explanation, `review_status`, provenance, `trace_id`) and turns it into **notifications dispatched
to humans** (email/SMS), **escalating** until the alert is confirmed handled. It is the single
place where BridgeGuard touches the outside world, so it is the single place the human-approval
gate (`needs_approval`) lives (Principle I; Risk FR-5).

It exists because the upstream agents deliberately stop at *recommendations*: the Risk Agent "emits
recommendations only; takes and gates no real-world action" and names **this** agent as the owner
of the dispatch chokepoint (Risk FR-5, Out of Scope). A risk verdict that no one is told about — or
that is dispatched to authorities without a human in the loop — is the failure this agent prevents.

It **notifies and escalates**; it never re-judges. It copies the upstream verdict, it does not
recompute a score, re-word the explanation, or change a severity band (that judgment already passed
the Risk Agent's numeric-provenance guardrail and must not be silently re-narrated).

---

## Settled in clarification interview (baked into the FRs below)

- **Severity→approval mapping is explicit, not config-discovered.** SAFE/WATCH auto-fire to
  **internal** channels only; **WARNING and CRITICAL require human approval** (`needs_approval`)
  before dispatch; **any authority-facing or closure-implying dispatch requires approval regardless
  of band**; and a verdict marked `PENDING_HUMAN_REVIEW` **never** auto-fires at any band (FR-2,
  FR-3). *(The engineer-tunable pieces — the roster, retry counts, timeout windows — remain config;
  but WHICH severities gate is now spec behaviour, resolved the way DCA resolved cadence and
  OFFLINE/NO_DATA.)*
- **Escalation close condition is severity-dependent.** SAFE/WATCH close on a confirmed provider
  **DELIVERED** state; **WARNING/CRITICAL close only on a recorded human ACKNOWLEDGEMENT** and keep
  escalating (next contact / on-call) until then (FR-6). Delivery is not "a human saw it."
- **Low-band output is settled.** **SAFE** updates the dashboard/alert-timeline with **no outbound
  push** (routine monitoring pages no one); **WATCH** pushes an **internal** notification (FR-4).
- **Two orthogonal human-in-the-loop axes, never conflated** (see Core Concepts): the upstream
  `review_status` (finality of the recommendation) and this agent's `needs_approval` (gate on the
  physical dispatch).

---

## Core Concepts

- **Two orthogonal human-in-the-loop axes — they co-exist, neither replaces the other:**
  - **`review_status` (finality of the recommendation):** `FINAL | PENDING_HUMAN_REVIEW`, set
    *upstream* by the Risk Agent. Every CRITICAL is emitted `PENDING_HUMAN_REVIEW` (Risk FR-11).
    This agent MUST NOT treat a `PENDING_HUMAN_REVIEW` verdict as a settled, actionable fact.
  - **`needs_approval` (gate on the physical dispatch):** set *here*. The human sign-off on the act
    of notifying, not on the content of the verdict.
  - They answer different questions ("is the verdict final?" vs. "may we send this?") and both must
    hold before a gated dispatch goes out. A `FINAL` WARNING still needs approval (its band gates);
    a `PENDING_HUMAN_REVIEW` SAFE still cannot auto-fire (its finality blocks). Neither axis alone
    is sufficient.

- **The gate keys on the action's blast-radius, not on the band alone.** A WATCH note to the
  internal monitoring team is low-consequence and reversible; a dispatch to a municipal authority is
  not — even at the same band. Band sets the *default* tier; an authority-facing or
  closure-implying recipient/channel escalates any dispatch to `needs_approval` (Principle I
  reversibility/blast-radius test).

- **Notify-and-escalate, never re-judge.** The agent relays the upstream verdict; it does not
  recompute the score, re-word the explanation, or re-map the severity. Re-narrating would create a
  new, ungoverned message that bypasses the numeric-provenance guardrail the Risk Agent already
  passed (Risk FR-7).

- **`SENT` ≠ `DELIVERED` ≠ `ACKNOWLEDGED`.** A provider accepting a message (a 200 on the send call)
  is not delivery to a human, and delivery is not a human acknowledging it. These are distinct,
  separately-recorded states; silent non-delivery is the catastrophic failure mode this agent
  exists to prevent.

- **Severity bands are the fixed `math-analysis` set.** `SAFE | WATCH | WARNING | CRITICAL` — a
  closed set, consumed from the upstream verdict, never invented per-run.

---

## The severity → action → approval table (settled — FR-2/FR-3/FR-4/FR-6)

This table is **spec behaviour**, not a config the implementer fills in. The roster, retry counts,
and timeout *values* are config (TODO until a stakeholder supplies them — do not guess); the
*mapping itself* is fixed here.

| Band | Outbound action | Approval before dispatch | Escalation closes on |
|------|-----------------|--------------------------|----------------------|
| **SAFE** (0–30) | Dashboard / alert-timeline only — **no push** | n/a (no dispatch) | n/a |
| **WATCH** (31–60) | **Internal** notification (auto-fire) | none, **if** `review_status = FINAL` | provider **DELIVERED** |
| **WARNING** (61–80) | Notification to the responsible engineer(s) | **`needs_approval`** | recorded **human ACK** |
| **CRITICAL** (81–100) | Notification + closure recommendation to the responsible authority | **`needs_approval`** | recorded **human ACK** |

**Overrides that apply to every row:**
- **Any** authority-facing or closure-implying dispatch → **`needs_approval`**, regardless of band.
- **`review_status = PENDING_HUMAN_REVIEW`** → **never auto-fires**; it routes for human approval
  before any dispatch, at any band (so every CRITICAL, being upstream-pending, is gated twice-over).

---

## What this agent receives (input contract)

Per alert (one persisted risk assessment, at one point in time):

| Input | Source | Meaning |
|---|---|---|
| **Risk verdict** | `risk_assessments` current row (Risk Agent, migration 0006) | `risk_score`, `severity`, `recommendation`, the **verbatim** `explanation`, `review_status`, `confidence`/`data_completeness`, and provenance (`source_analysis_ids`, `standard_*`, `model_*`, `trace_id`). Read by scope key; current (`superseded_by IS NULL`) row only. |
| **Alert scope + trigger** | trigger (downstream of Risk) | Which assessment (bridge/cycle or assessment id) fired this alert. |
| **Contact roster / channels** | configuration | Who to notify at each band, on which channel, and the on-call escalation order. **Config (TODO until supplied — do not guess).** |

The agent **reads** the verdict; it never mutates the upstream `risk_assessments` record. It does
not re-run the Risk Agent, re-open the calculation, or re-derive the severity (Principle III — it
trusts its upstream contract).

---

## What this agent emits (output contract)

Per alert run, **all** of:

- **`dispatch_decision`** — the resolved tier for this verdict: `AUTO_FIRE | NEEDS_APPROVAL |
  DASHBOARD_ONLY`, derived from the settled table (band + blast-radius + `review_status`).
- **`dispatches`** — one record per attempt: channel, recipient, provider message id, **state**
  (`QUEUED | SENT | DELIVERED | FAILED | ACKNOWLEDGED`), timestamp, and the source `assessment_id` +
  `assessment_version`. Append-only; an attempt is never overwritten.
- **`escalation_state`** — `OPEN | ESCALATED | CLOSED`, with the close reason (`DELIVERED` for
  SAFE/WATCH, `ACKNOWLEDGED` for WARNING/CRITICAL) and which contact acknowledged.
- **`approval_state`** (when gated) — `AWAITING_APPROVAL | APPROVED | REJECTED`, with who approved
  and when — the audit of the human sign-off.
- **`DispatchSummary`** — a structured status: `{ ok, dispatch_decision, delivered_channels,
  failed_channels, escalated, error }`. `ok` is true only when the alert reached its band's close
  condition. Returned on every run; never a raised exception (Principle IV/V).
- **`trace_id`** — links to the SDK trace of the run (dual audit; carries the upstream verdict's
  `trace_id` for end-to-end provenance).

---

## User Scenarios

- **SAFE — dashboard only, no one paged.** A SAFE verdict updates the alert-timeline and dashboard.
  No email/SMS is sent; `dispatch_decision = DASHBOARD_ONLY`. Routine monitoring must not page a
  human (alert fatigue is itself a safety risk).

- **WATCH, FINAL — auto-fires internally.** A `FINAL` WATCH verdict pushes an internal notification
  ("increased inspection frequency advised") with no human approval. It closes as soon as the
  provider confirms **DELIVERED**.

- **WARNING — held for approval, then dispatched, escalates to ACK.** A WARNING verdict is **not**
  auto-fired: `dispatch_decision = NEEDS_APPROVAL`, `approval_state = AWAITING_APPROVAL`. After a
  human approves, the notification goes to the responsible engineer and the alert stays **OPEN** —
  escalating to the next contact / on-call — until a **human acknowledgement** is recorded.

- **CRITICAL — gated twice, authority-facing, ack-closed.** A CRITICAL verdict arrives already
  `PENDING_HUMAN_REVIEW` (Risk FR-11). It is gated on **both** axes: it cannot auto-fire (pending
  finality) **and** its dispatch is `needs_approval` (band + authority recipient). After human
  approval, the closure recommendation is dispatched to the authority; the ladder escalates until a
  human **ACK**.

- **Delivery fails on the primary channel — fail-over, then escalate.** The email send fails (or no
  DELIVERED receipt arrives within the window). The agent retries with backoff, **fails over** to a
  secondary channel (SMS), and if no channel confirms delivery — and, for WARNING/CRITICAL, no human
  ACK — it **escalates** to the next contact. Every attempt is a logged `dispatches` row; nothing is
  silent.

- **The alert message would contradict the verdict — blocked.** A drafted alert whose stated
  severity/label disagrees with the source `severity`/`risk_score` (e.g. reads "routine" over a
  WARNING verdict), or that presents a `PENDING_HUMAN_REVIEW` verdict as settled, **tripwires the
  consistency guardrail** and is **not dispatched** — it fails closed and routes to human review
  (an engineer must never receive an alert that misstates the record).

- **Provider outage — a structured status, never a crash.** The notification provider is
  unreachable. The agent does not throw: it records `FAILED`, retries/escalates per policy, and
  returns a `DispatchSummary` with `ok = false` and the failure named.

- **Redelivered / re-triggered alert for the same verdict.** The same assessment fires the alert
  twice. The agent does not double-dispatch: a verdict already dispatched (or awaiting approval /
  acknowledged) is idempotent on `(assessment_id, assessment_version)`.

- **A superseded verdict fires late.** A newer assessment version has superseded the one that
  triggered this alert. The agent alerts on the **current** verdict and records which version it
  dispatched, so the alert is reproducible against exactly that verdict.

---

## Functional Requirements

A build that ignores any of these should **visibly fail** a corresponding test.

- **FR-1 — Consumes a persisted verdict read-only; never re-judges.** The agent reads the current
  `risk_assessments` verdict by scope key and dispatches based on it. It does not recompute the
  score, re-word the `explanation`, or re-map the `severity`, and it **mutates no upstream record**.
  A build that alters the verdict, re-narrates the explanation, or writes upstream fails.
  *(Principle III; research §Framing.)*

- **FR-2 — The severity→approval mapping is fixed and explicit (the settled table).** SAFE →
  dashboard-only (no dispatch); WATCH → auto-fire internal; WARNING → `needs_approval`; CRITICAL →
  `needs_approval`. This mapping is **spec behaviour**, not an implementer choice or a config lookup.
  A build that auto-fires WARNING or CRITICAL, or that pushes an outbound notification for SAFE,
  fails. *(Settled in interview; Principle I; CLAUDE.md gate-real-world-actions.)*

- **FR-3 — Blast-radius and `review_status` overrides gate beyond the band.** **(a)** Any
  authority-facing or closure-implying dispatch requires `needs_approval` regardless of band.
  **(b)** A verdict with `review_status = PENDING_HUMAN_REVIEW` is **never auto-fired** at any band;
  it routes for approval first. Both axes must be satisfied before a gated dispatch is sent. A build
  that auto-fires a `PENDING_HUMAN_REVIEW` verdict, or dispatches to an authority without approval,
  fails. *(Settled in interview; Risk FR-11; Principle I reversibility/blast-radius.)*

- **FR-4 — Low-band output is fixed: SAFE dashboard-only, WATCH internal push.** SAFE produces **no**
  outbound notification (dashboard / alert-timeline only); WATCH produces an **internal**
  notification. A build that pages a human on SAFE, or that produces no signal at all for WATCH,
  fails. *(Settled in interview; skills-README band actions.)*

- **FR-5 — `needs_approval` is enforced in code and un-bypassable; this is the single dispatch
  chokepoint.** Every gated dispatch (FR-2/FR-3) is blocked until a human approval is recorded, and
  there is **no code path** that dispatches a gated action without it. This agent is the system's
  **single** un-bypassable real-world-action gate — no other module may notify an authority or
  recommend closure. A build with a bypass path, or a second un-gated dispatch point elsewhere,
  fails. *(Principle I "cannot be bypassed in code"; Risk FR-5 + Open Item; CLAUDE.md.)*

- **FR-6 — Escalation closes on a severity-dependent condition; delivery ≠ acknowledgement.**
  SAFE/WATCH alerts close on a confirmed provider **DELIVERED** state. WARNING/CRITICAL alerts remain
  **OPEN** and escalate (next contact / on-call) until a **human acknowledgement** is recorded —
  a DELIVERED receipt alone does **not** close them. A build that closes a WARNING/CRITICAL alert on
  delivery without an acknowledgement, or that never escalates an unacknowledged high-severity alert,
  fails. *(Settled in interview; research §3.)*

- **FR-7 — Distinct delivery states, tracked and reconciled from the provider.** Each dispatch
  carries a state in `QUEUED → SENT → DELIVERED / FAILED` (and `ACKNOWLEDGED` for the human step),
  reconciled from provider delivery receipts / webhooks — the agent never assumes success from the
  send call returning. A build that collapses "sent" and "delivered", or marks delivered on a bare
  send-accept, fails. *(Research §3; Principle IV always-return-a-status.)*

- **FR-8 — Delivery failure is retried, failed-over, and escalated — never silent.** On a channel
  failure or a missing DELIVERED confirmation within the configured window, the agent retries with
  backoff, fails over to a secondary channel, and escalates to the next contact. Every attempt is a
  logged `dispatches` record. A build that drops a failed dispatch silently, or retries unboundedly
  without failing over/escalating, fails. *(Research §3; retry/backoff/timeout values are config —
  do not guess.)*

- **FR-9 — Consistency output guardrail: an alert that contradicts the verdict is not dispatched.**
  Before dispatch, the alert's stated severity/label must match the source `severity`/`risk_score`,
  and the alert must not present a `PENDING_HUMAN_REVIEW` verdict as settled. A mismatch **tripwires
  the guardrail** and the alert is **not sent** — it fails closed and routes to human review. A
  build that dispatches an alert whose band contradicts the source verdict fails. *(Research §2;
  Principle I "a score/alert without its WHY is a defect" ⇒ an alert that misstates the WHY is also
  a defect; CLAUDE.md prefer-SDK-guardrails.)*

- **FR-10 — Idempotent on the verdict version.** A redelivered or re-triggered alert for a verdict
  already dispatched / awaiting approval / acknowledged is a **no-op** (idempotent on
  `(assessment_id, assessment_version)`); it does not double-dispatch or double-page. A build that
  re-sends on redelivery fails. *(Mirrors Risk 0006 partial-unique-current discipline.)*

- **FR-11 — Alerts on the current verdict; reproducible against the pinned version.** The agent
  dispatches on the **current** (`superseded_by IS NULL`) verdict and records the exact
  `assessment_id` + `assessment_version` it acted on, so the alert is reproducible even after the
  verdict is later superseded. A build that alerts on a stale/superseded verdict as if current, or
  that cannot say which version it dispatched, fails. *(Principle VI; research §Framing.)*

- **FR-12 — Every run is structured, never crashes, and is independently testable.** For every
  alert the agent returns a `DispatchSummary` (or a structured degraded/awaiting-approval status)
  and never propagates an unhandled exception — including on provider outage, malformed scope, or a
  missing verdict. A build that throws on bad/partial input instead of returning a status fails.
  *(Principle IV/V.)*

- **FR-13 — Dual audit: append-only dispatch log + full trace.** Every dispatch attempt, approval,
  and acknowledgement writes an **append-only** record (channel, recipient, provider id, state,
  timestamp, `assessment_id` + version, approver, `trace_id`) — corrections append, never overwrite,
  and DELETE is blocked (a dispatch history a regulator relies on is permanent). Separately, the full
  run is **traced** from the first run, no exceptions. A build that overwrites or deletes a dispatch
  record, or that omits the approver / source verdict / trace id, fails. *(Principles II, VI, VII;
  mirrors `risk_assessments` correct-by-append; research §3.)*

---

## Edge Cases & Rules

- **`FINAL` WARNING vs. `PENDING_HUMAN_REVIEW` SAFE.** Both axes are checked independently: the
  WARNING gates on its band (`needs_approval`); the SAFE cannot auto-fire because it is pending. One
  axis being permissive never overrides the other (FR-2/FR-3).
- **Authority recipient at a low band.** If a WATCH-band alert would go to an authority (unusual but
  possible via roster config), the blast-radius override applies and it becomes `needs_approval`
  despite the band (FR-3a).
- **DELIVERED but never ACKNOWLEDGED (WARNING/CRITICAL).** The alert stays OPEN and keeps escalating;
  delivery does not close a high-severity alert (FR-6). This is the core "escalation" behaviour.
- **All channels fail for a CRITICAL.** Exhaust retry + fail-over, then escalate up the on-call chain;
  the `DispatchSummary` reports `ok = false` with the failure — the alert is never silently dropped
  (FR-8/FR-12).
- **Approval rejected.** A human rejects the dispatch: `approval_state = REJECTED`, no notification is
  sent, and the rejection is audited (FR-5/FR-13). The verdict stands; the *dispatch* was declined.
- **Verdict superseded between trigger and dispatch.** Re-resolve to the current verdict and dispatch
  on that, recording the version acted on (FR-11).
- **Redelivered trigger.** No-op if already handled for that version (FR-10).
- **Alert message contradicts the verdict.** Guardrail tripwire — not sent, routed to human (FR-9).

---

## Out of Scope

- **Judging risk / computing or re-computing a score, severity, or explanation** — the **Risk
  Agent's** job (Agent 003). This agent consumes a finished verdict and never re-decides it.
- **The human-review-clearing workflow for `PENDING_HUMAN_REVIEW`** — *who* clears a pending verdict,
  the review UI/queue, and the cleared→`FINAL` transition are a separate downstream concern (Risk
  Out of Scope). This agent only *observes* `review_status` and refuses to auto-fire a pending one.
- **Authoring the PDF / government report** — the **Report Generation Agent's** job (Agent 004).
  This agent may *dispatch a link to* or *notify of* a report, but does not render it.
- **Maintaining the contact roster / on-call schedule** — it *reads* the roster; curating who-is-on-
  call and the escalation order is an operational/config concern (TODO until supplied).
- **The dashboard / alert-timeline UI** — a Next.js frontend concern (`visual-output`). This agent
  emits the events the timeline shows; it does not render the timeline.
- **Choosing the notification provider(s) and the concrete channel integration** — a `plan.md`
  design decision (SMTP/SendGrid/SES, Twilio/SNS, MCP-tool vs. in-service, n8n glue). This spec fixes
  only the behaviour (distinct delivery states, retry/fail-over/escalate, append-only audit).

This agent only **notifies and escalates** — it carries an accountable human-reviewed verdict to the
people who must act on it, gated by a human at the one point BridgeGuard touches the physical world.

---

## Acceptance Criteria

Each is testable against a scenario above.

- **AC-1.** The agent reads the current verdict and dispatches from it **without mutating** the
  `risk_assessments` row and **without re-wording** the explanation or re-mapping the severity.
  *(read-only; no re-judge — FR-1)*
- **AC-2.** SAFE → no outbound notification (dashboard-only); WATCH(`FINAL`) → auto-fired internal
  notification; WARNING → `NEEDS_APPROVAL` (not auto-fired); CRITICAL → `NEEDS_APPROVAL`. A test
  asserting WARNING/CRITICAL are **not** dispatched without approval passes; one asserting SAFE pages
  a human fails. *(settled mapping — FR-2/FR-4)*
- **AC-3.** A `PENDING_HUMAN_REVIEW` verdict is **never auto-fired** at any band; any
  authority-facing/closure dispatch is `needs_approval` regardless of band. *(overrides — FR-3)*
- **AC-4.** There is **no code path** that performs a gated dispatch without a recorded approval, and
  no second un-gated dispatch point exists in the system. *(single un-bypassable chokepoint — FR-5)*
- **AC-5.** A SAFE/WATCH alert closes on a **DELIVERED** state; a WARNING/CRITICAL alert stays OPEN
  and escalates until a **human ACK** — a DELIVERED-without-ACK WARNING/CRITICAL does **not** close.
  *(escalation close condition — FR-6)*
- **AC-6.** `SENT`, `DELIVERED`, and `ACKNOWLEDGED` are distinct recorded states reconciled from the
  provider; the agent never marks DELIVERED on a bare send-accept. *(delivery states — FR-7)*
- **AC-7.** A primary-channel failure triggers retry → fail-over → escalation, each a logged
  `dispatches` record; no failure is silent. *(failure handling — FR-8)*
- **AC-8.** An alert whose stated band contradicts the source verdict (or presents a pending verdict
  as settled) **tripwires the guardrail** and is **not dispatched**; a consistent alert passes.
  *(consistency guardrail — FR-9)*
- **AC-9.** A redelivered trigger for an already-handled verdict version is a **no-op** (no
  double-dispatch). *(idempotency — FR-10)*
- **AC-10.** The agent dispatches on the **current** verdict and records the `assessment_version` it
  acted on; the alert is reproducible after supersession. *(reproducibility — FR-11)*
- **AC-11.** The agent **returns a structured `DispatchSummary` on malformed/partial input, a missing
  verdict, and a provider outage, and never throws** (the four-scenario constitution test:
  normal / missing / corrupt / offline). *(never-crash — FR-12)*
- **AC-12.** Every dispatch, approval, and acknowledgement writes an **append-only** audit record
  (with approver, source `assessment_id`+version, and `trace_id`); an attempt to overwrite or delete
  one is blocked, and the full run is traced. *(dual audit — FR-13)*

---

## Open Items

The clarification interview settled the agent's **behaviour** — the severity→approval mapping
(FR-2), the blast-radius/`review_status` overrides (FR-3), low-band output (FR-4), the ack-vs-
delivery close condition (FR-6), and the consistency guardrail (FR-9). What remains is **not**
behavioural ambiguity — it is config values a stakeholder must supply and design decisions to pin at
`plan.md`. None should be guessed in a safety-critical system.

**Config TODOs (a government stakeholder / ops owner supplies; placeholders until then — do not
invent):**
- **Contact roster + on-call escalation order:** who is notified at each band and the escalation chain.
- **Retry/backoff counts + escalation timeout window:** how many retries, backoff schedule, and how
  long before escalating an unacknowledged/undelivered alert.
- **Primary + fail-over channel per band:** which channel is tried first and the fail-over order.
- **Which recipients/channels count as "authority-facing"** (drives the FR-3a blast-radius override).
- **Acknowledgement mechanism:** how a human records an ACK (reply, dashboard action, signed link).

**Deferred to plan.md (design decisions, not spec behaviour):**
- **Model vs. Option A:** whether composing the escalation message needs a model (then FR-9 is an SDK
  output guardrail, regenerate-once-then-fail-closed like Risk 003) or is deterministic templating
  (then FR-9 is a deterministic fail-closed assertion, like Report 004). Research §Framing leans
  Option A; unresolved.
- **Notification provider(s) + channel integration mechanism** (SMTP/SendGrid/SES, Twilio/SNS;
  MCP-tool vs. in-service; n8n glue) and the delivery-receipt/webhook reconciliation wiring.
- **Where the append-only dispatch log lives** relative to `risk_assessments` (same Neon store,
  parallel to the Report agent's artifact-store question) and its retention policy.
- **Confirming the single-chokepoint invariant in code** — an import/structural check that no other
  module defines a dispatch/notify path (Risk Open Item; Principle I).
