# Alert & Escalation Agent — Tasks

**Status:** Draft for review (do not implement until approved)
**Date:** 2026-07-09
**Spec:** `specs/alert-escalation-agent/spec.md` (13 FR / 12 AC, notify-and-escalate spine)
**Plan:** `specs/alert-escalation-agent/plan.md` (it is a **deterministic service — NOT an Agents-SDK
Agent**; the DCA/SA/Report counterpart, downstream of the Risk Agent; the **single real-world-action
chokepoint**)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.1.0** (Neon/Postgres, standard
indexes only; no model here, so the SDK alias-import rule does not apply)

## Confirmed decisions (acceptance checks reference these + spec ACs)

- **This is a deterministic Python service, no model** — Option A, same as the DCA/SA/Report; the
  inverse of Agent 003. **n8n triggers it downstream of the Risk Agent**, **per finalized
  assessment**. **Neon/Postgres** is the store.
- **Notify-and-escalate, never re-judge (FR-1):** the alert copies the verdict — score, severity,
  recommendation, **verbatim** explanation — and never recomputes, re-maps, or rewords it.
- **The severity→approval mapping is fixed and explicit (FR-2/FR-3):** SAFE → dashboard-only (no
  push); WATCH & `FINAL` → auto-fire internal; WARNING/CRITICAL → `needs_approval`; **any
  authority/closure dispatch → `needs_approval` regardless of band**; **`PENDING_HUMAN_REVIEW` →
  never auto-fires** at any band. This is spec behaviour, not an implementer choice.
- **Low-band output is fixed (FR-4):** SAFE dashboard-only, WATCH internal push.
- **This agent IS the chokepoint (FR-5):** `needs_approval` is enforced in code with **no bypass
  path**, and this is the system's **single** un-bypassable dispatch point — the **inverse** of the
  Report agent's "no needs_approval here" purity check.
- **Escalation close is severity-dependent (FR-6):** SAFE/WATCH close on provider **DELIVERED**;
  WARNING/CRITICAL stay **OPEN** and escalate until a recorded **human ACK**. Delivery ≠ ack.
- **`SENT` ≠ `DELIVERED` ≠ `ACKNOWLEDGED` (FR-7):** distinct states, reconciled from the provider —
  never mark delivered on a bare send-accept.
- **Failure is retried → failed-over → escalated, never silent (FR-8);** every attempt is a logged
  append-only row.
- **Consistency gate = fail-closed (FR-9):** an alert whose stated band contradicts the source
  verdict (or presents a pending verdict as settled) is **not dispatched** — the alert-layer analogue
  of the Report fidelity gate, plain code, no SDK.
- **Idempotent per assessment version (FR-10); alerts on the current verdict, reproducible from the
  pinned version (FR-11).**
- **Never crashes → always a structured `DispatchSummary` (FR-12).** Append-only dispatch log +
  audit, DELETE-blocked (FR-13).
- **All config values** — the roster, retry/backoff counts, escalation timeout, per-band channels,
  authority-recipient set, severity→message template — stay **`TODO`-marked config** (do not guess).

## Conventions

- Each task is < 1 hour and **independently verifiable**; acceptance checks are concrete (tied to an
  FR/AC or a decision above), never "works correctly". Same granularity as the DCA/SA/Risk/Report
  builds.
- **[DB-DEP]** = needs live Neon to fully verify; built/verified against an in-memory fake now, live
  verification honestly deferred (no Neon instance locally). Same pattern the DCA/SA/Risk/Report
  fakes use.
- **[NOTIFY-DEP]** = needs a real email/SMS provider (SMTP/SendGrid/SES; Twilio/SNS) to send actual
  messages and receive delivery/ack callbacks; **no provider is wired today**. Built/verified against
  a **`FakeNotifier`** (a `NotifierPort` seam that records dispatch attempts and lets a test drive
  DELIVERED/FAILED/ACK transitions) + structural assertions now; live send + webhook reconciliation
  deferred, flagged not faked. Tiering, consistency gate, approval gate, the escalation state
  machine, persistence, idempotency, and service logic are all testable **without** a live provider —
  only the genuine send is [NOTIFY-DEP].
- Constitution gates: never crash → always emit a structured `DispatchSummary` (FR-12); reads never
  mutate the Risk/SA/DCA tables; **no model in any path** (Principle IV — assert the tiering/message/
  service graph imports no model/SDK); every dispatched band binds exactly to the source verdict
  (FR-9); **the `needs_approval` gate EXISTS and is un-bypassable** (FR-5 — the inverted check).
- **Reuse proven patterns:** import `Severity` + `ReviewStatus` from `agents.risk_reasoning.statuses`
  (do **not** re-declare the bands); reuse `get_risk_assessment` / `AssessmentScope` /
  `AssessmentSource` from `agents.report_generation.tools.risk_assessment_read` (the same upstream
  read); mirror the Report `statuses.py` enum style, the `FakeReportStore` mirror, the
  `report_result.py` summary shape, the `render/port.py` seam, and the append-+-supersede triggers
  from `risk_assessments` (0006) / `report_artifacts` (0008).
- **Task prefix `A`** (**A**lert), to avoid collision with DCA `T`, SA `S`, Risk `R`, Report `G`.

---

## Phase 1 — Config (roster, channels, retry/backoff, timeout, message templates — config not code)

- **A101 — `AlertPolicy` config shape (roster + channels + retry/backoff + escalation timeout).**
  Frozen slotted dataclass (mirrors `report_config.py`): `policy_version` (concrete, for audit);
  `contact_roster` / `escalation_order`, `channel_per_band`, `retry_max` + `backoff_seconds`,
  `escalation_timeout_seconds`, `authority_recipients` (the FR-3 blast-radius set) — all **TODO**
  sentinels (NaN for numerics, None/empty for refs) with an `_is_todo` helper. An
  `is_fully_configured` property is False while any human-supplied value is unset.
  **Acceptance:** constructs; `policy_version` is concrete; every operational value
  (roster/channels/retry/backoff/timeout/authority-set) is a clearly-flagged `TODO` sentinel a
  reviewer sees is unset; `is_fully_configured` is False while any is unset. (do-not-guess)

- **A102 — `MessageTemplateTable` (severity→message template lookup, FR-1 assembly half).**
  A fixed mapping `severity → message template` (config, not code): `SAFE|WATCH|WARNING|CRITICAL →
  TODO template`, where the template frames the **verbatim** verdict (score/severity/recommendation/
  explanation) — a fixed phrase, no generated prose. Pure lookup; a severity with no configured
  template returns a clearly-unset sentinel, never a guessed phrase.
  **Acceptance:** every band maps to exactly its configured template (or a flagged `TODO` sentinel);
  the same severity always yields the same template (deterministic); no model/computation involved
  (pure dict lookup); an unknown/absent severity is not guessed. = FR-1 (message half).

---

## Phase 2 — Output vocabulary + schema [DB-DEP]

- **A201 — `statuses.py` (closed vocabulary).**
  `DispatchDecision` enum (`AUTO_FIRE | NEEDS_APPROVAL | DASHBOARD_ONLY`); `DeliveryState` enum
  (`QUEUED | SENT | DELIVERED | FAILED | ACKNOWLEDGED`); `EscalationState` enum (`OPEN | ESCALATED |
  CLOSED`); `ApprovalState` enum (`AWAITING_APPROVAL | APPROVED | REJECTED`); `AlertOutcome` enum
  (`DISPATCHED | WITHHELD | ERROR`); `WithheldReason` enum (`ASSESSMENT_NOT_FOUND |
  CONSISTENCY_MISMATCH`). All `str, Enum`, mirroring the DCA/SA/Risk/Report `statuses.py` style + the
  SQL enums (A203). **Import `Severity`/`ReviewStatus` from `risk_reasoning.statuses` — do not
  redeclare.**
  **Acceptance:** all enum members representable; a `DISPATCHED` result may carry a delivery +
  escalation + (optional) approval state; a `WITHHELD` result carries exactly one reason; matches the
  spec output contract vocabulary; the band enum is imported, not re-defined.

- **A202 — Output payload shape (typed `AlertResult` + `DispatchSummary`).**
  Frozen dataclasses (mirror `report_result.py`): `AlertResult` (bridge_id, cycle_id, assessment_id,
  assessment_version, dispatch_decision, channel, recipient, provider_message_id, delivery_state,
  escalation_state + close_reason, approval_state + approved_by, trace_id, attempted_at-seam,
  withheld_reason); `DispatchSummary` (the plain dict the service returns to n8n: `ok`,
  dispatch_decision, delivered_channels, failed_channels, escalated, withheld_reason/error).
  `from_result` / `from_error` / `as_dict`; `ok` True only when the alert reached its band's close
  condition.
  **Acceptance:** constructs typed; a `DISPATCHED` result carries its decision + delivery/escalation
  states + pinned provenance (assessment_id+version, trace_id); a `WITHHELD` result carries a reason
  and no delivered channel; `__post_init__` enforces coherent shapes; `ok` is True only on a closed
  dispatch. = spec output contract.

- **A203 — `alert_dispatches` table (append-+-supersede) [DB-DEP].**
  Migration **`0010_alert_dispatches.sql`** per plan §3b: `id`, `bridge_id`, `cycle_id`,
  `assessment_id`, `assessment_version`, `dispatch_decision` (enum), `channel`, `recipient`,
  `provider_message_id`, `delivery_state` (enum), `escalation_state` (enum) + `close_reason`,
  `approval_state` (enum, NULL when un-gated) + `approved_by` + `approved_at`, `trace_id`,
  `attempted_at`, `superseded_by`. Same BEFORE-UPDATE guard (only `superseded_by` + the state-machine
  columns mutable per the correction discipline) + DELETE-block triggers as `risk_assessments`
  (0006). Partial unique index on `(assessment_id, assessment_version)` WHERE `superseded_by IS NULL`
  (idempotency, standard Postgres index — no TimescaleDB).
  **Acceptance:** enums representable; a `NEEDS_APPROVAL` row requires an `approval_state` (CHECK); an
  `AUTO_FIRE`/`DASHBOARD_ONLY` row has NULL `approval_state` (CHECK); a `WITHHELD` decision path
  records a reason; DELETE revoked; uniqueness on `(assessment_id, assessment_version)` among current
  rows. [DB-DEP live enforcement deferred.]

- **A204 — Audit: extend `decision_log` enum [DB-DEP].**
  Migration **`0011_decision_log_alert_kinds.sql`**: add `ALERT_DISPATCHED | ALERT_ESCALATED |
  ALERT_WITHHELD | ALERT_ERROR` to `decision_kind` (one shared cross-agent audit trail, per plan §3b/
  Open Item 11). Header notes `ALTER TYPE ADD VALUE` cannot run in a transaction block (same as 0007/
  0009).
  **Acceptance:** the new kinds representable alongside the DCA/SA/Risk/Report kinds; an
  `ALERT_WITHHELD` row records the withheld reason; an `ALERT_DISPATCHED` row records which assessment
  version + channel + approval state. [DB-DEP deferred.]

---

## Phase 3 — The read port (reuse the upstream verdict read, read-only) [DB-DEP]

- **A301 — Reuse `get_risk_assessment(scope, source, *, historical=False)` for the verdict read.**
  Wire the Alert service to the **existing** `get_risk_assessment` / `AssessmentScope` /
  `AssessmentSource` from `agents.report_generation.tools.risk_assessment_read` (plan §3a, §Open Item
  7) — read the **current** (non-superseded) `risk_assessments` row the scope key resolves to; a
  specific superseded row by id under `historical=True`. Missing → structured `ASSESSMENT_NOT_FOUND`
  signal (not a raise). Never writes. *(If the report→alert import coupling is rejected at review,
  lift the tool to `agents/_shared/` — same behaviour either way.)*
  **Acceptance (fake source):** current scope → the current verdict; absent → `ASSESSMENT_NOT_FOUND`
  signal, no raise; the call performs **no** mutation (assert source unchanged); the import resolves
  (reused module, band vocabulary imported from `risk_reasoning.statuses`). = FR-1/FR-11, Const. III
  read-only. [DB-DEP live deferred.]

---

## Phase 4 — Tiering (the settled severity→approval decision, FR-2/FR-3) + test

- **A401 — `decide_tier(verdict, policy)` (pure).**
  The one place the settled mapping lives. Returns a `DispatchDecision` + the resolved channel/
  recipient: SAFE → `DASHBOARD_ONLY`; WATCH & `review_status == FINAL` → `AUTO_FIRE` (internal
  channel); WARNING/CRITICAL → `NEEDS_APPROVAL`. **Overrides:** any authority-facing/closure-implying
  recipient → `NEEDS_APPROVAL` regardless of band; `review_status == PENDING_HUMAN_REVIEW` → never
  `AUTO_FIRE` (routes to `NEEDS_APPROVAL`) at any band. Pure decision function over the verdict +
  policy; no I/O.
  **Acceptance:** each band yields its documented decision; a `PENDING_HUMAN_REVIEW` WATCH → **not**
  `AUTO_FIRE`; an authority-recipient WATCH → `NEEDS_APPROVAL` (blast-radius override); every CRITICAL
  (upstream-pending) → `NEEDS_APPROVAL`; SAFE → `DASHBOARD_ONLY` (no dispatch). = FR-2/FR-3, the
  settled table.

- **A402 — Test tiering: mapping + both overrides (FR-2/FR-3, AC-2/AC-3).**
  **Acceptance:** drives A401 over the four bands × {FINAL, PENDING_HUMAN_REVIEW} × {internal,
  authority recipient}: asserts the full truth table — SAFE never dispatches; WATCH auto-fires only
  when FINAL + internal; WARNING/CRITICAL always gated; the authority override forces
  `NEEDS_APPROVAL` at any band; the pending override forbids `AUTO_FIRE` at any band. A build that
  auto-fires WARNING/CRITICAL, or a `PENDING_HUMAN_REVIEW` verdict, or a SAFE push, fails. = AC-2/AC-3.

---

## Phase 5 — Message assembly + consistency gate (FR-1/FR-9) + test

- **A501 — `assemble_message(verdict, templates)` (pure, verbatim).**
  Build the alert message by **copying** the verdict into the fixed severity→template (A102): the
  **verbatim** explanation, the score/severity/recommendation as-is, the band label from the source
  `severity`. **No recomputation, re-mapping, or rewording.** Each message field records the source
  value it was copied from (for the consistency gate, A502).
  **Acceptance:** the message's band label **equals** the source `severity`; the explanation is
  **byte-identical** to `verdict.explanation`; score/recommendation equal the source; no field is
  computed/derived; the template is the fixed A102 lookup (changes only if config changes, not the
  data). = FR-1, AC-1.

- **A502 — `consistency_check(message, verdict)` (pure, fail-closed).**
  Verify the assembled message does not contradict the verdict: the message band **equals** the
  source `severity`/`risk_score` band, **and** the message does not present a `PENDING_HUMAN_REVIEW`
  verdict as settled/final. Return pass / the offending contradiction. Pure decision function; the
  alert-layer analogue of the Report `fidelity_check` — plain code, **no SDK**.
  **Acceptance:** a faithful message → pass; a message whose band contradicts the source verdict →
  fail, naming the contradiction; a message presenting a pending verdict as settled → fail; a
  consistent message over a pending verdict (correctly marked not-final) → pass. = FR-9, AC-8
  (positive + negative).

- **A503 — Test assembly-verbatim + consistency fail-closed (FR-1/FR-9, AC-1/AC-8).**
  **Acceptance:** drives A501/A502 over fake verdicts: the message equals the source (assemble-only)
  and the explanation is byte-for-byte identical; a deliberately **injected contradicting band**
  (message says "routine" over a WARNING verdict) trips A502 → the service (A901) yields
  `WITHHELD/CONSISTENCY_MISMATCH` and **no dispatch**; a clean message passes. **No model involved** —
  assert the assembly/gate graph imports no model/SDK (ast import-root check, mirroring Report G403/
  Risk R303). = AC-1/AC-8, the alert-layer contradiction control.

---

## Phase 6 — The approval gate (INVERTED chokepoint, FR-5) + test

- **A601 — `approval_gate(decision, approval)` (pure) — no gated dispatch without a recorded approval.**
  For a `NEEDS_APPROVAL` decision, dispatch is blocked unless a recorded `ApprovalState == APPROVED`
  (with `approved_by`) is present; `REJECTED` → no dispatch, audited; `AWAITING_APPROVAL` → held.
  `AUTO_FIRE` / `DASHBOARD_ONLY` decisions pass through (no approval needed). There is **no code
  path** that performs a gated dispatch without an approval — this is the un-bypassable gate.
  **Acceptance:** a `NEEDS_APPROVAL` decision with no approval → dispatch blocked (held
  `AWAITING_APPROVAL`); with `APPROVED` + `approved_by` → proceeds; with `REJECTED` → no dispatch,
  the rejection recorded; an `AUTO_FIRE` decision proceeds without approval. = FR-5.

- **A602 — Inverted constitution test: the gate EXISTS and is the single chokepoint (FR-5, AC-4).**
  The **opposite** of the Report agent's G1103 purity check (which asserts no `needs_approval`/
  dispatch exists there). Here: **(a)** assert the alert package **does** define the `needs_approval`
  gate and a dispatch path (the chokepoint is here); **(b)** assert **no code path** dispatches a
  `NEEDS_APPROVAL` decision without a recorded approval (drive A601 + the service A901); **(c)**
  structural check — **no *other* agent package** (`data_collection`, `structural_analysis`,
  `risk_reasoning`, `report_generation`) defines a notify/dispatch-to-authority path (grep/ast scan
  over `src/agents/*/`), so this is the system's **single** un-bypassable real-world-action gate.
  Closes the Risk 003 §2 + Report plan item 12 open items.
  **Acceptance:** the gate + dispatch path exist in this package; no un-approved gated-dispatch path
  exists; no other agent package defines an un-gated dispatch; the scan names any offender. = AC-4,
  FR-5, Const. I single-chokepoint.

---

## Phase 7 — Dispatch + escalation (state machine, FR-6/FR-7/FR-8) [NOTIFY-DEP]

- **A701 — `NotifierPort` seam + `FakeNotifier` (deterministic stub) [NOTIFY-DEP].**
  Define the port the service calls (`send(channel, recipient, message) → provider_message_id +
  initial DeliveryState`), and a `FakeNotifier` that records each dispatch attempt and lets a test
  drive `DELIVERED`/`FAILED`/`ACKNOWLEDGED` transitions — so Phases 4–9 are testable without a real
  provider. Mirrors the Report `RenderPort` + `FakeRenderer` seam.
  **Acceptance:** the fake records the exact (channel, recipient, message) handed to it and returns a
  stable id + `SENT`/`QUEUED`; a test can drive it to `DELIVERED`, `FAILED`, or `ACKNOWLEDGED`;
  swapping in a real provider changes only the wire send, not the control flow. = [NOTIFY-DEP] seam.

- **A702 — Delivery state machine: `SENT ≠ DELIVERED ≠ ACKNOWLEDGED` (FR-7).**
  Advance a dispatch through `QUEUED → SENT → DELIVERED / FAILED`, and `ACKNOWLEDGED` only on a
  recorded human ack — reconciled from provider signals (the `FakeNotifier` drives them in tests),
  never assumed from the send call returning.
  **Acceptance:** a send-accept sets `SENT`, **not** `DELIVERED`; `DELIVERED` requires the provider
  receipt; `ACKNOWLEDGED` requires an explicit ack signal; the three are distinct recorded states; a
  build that marks `DELIVERED` on a bare send-accept fails. = FR-7, AC-6.

- **A703 — Escalation ladder: retry → failover → escalate; severity-dependent close (FR-6/FR-8).**
  On `FAILED` or no `DELIVERED` within the (config) window: retry with backoff, fail over to the
  secondary channel, then escalate to the next contact — every attempt a logged `AlertResult` row.
  Close condition: SAFE/WATCH → `CLOSED` on `DELIVERED`; WARNING/CRITICAL → stay `OPEN`/`ESCALATED`
  until a recorded human **ACK**. Retry/backoff/timeout values come from config (TODO).
  **Acceptance (fake notifier):** a primary-channel `FAILED` → retry, then failover to secondary,
  then escalate to next contact, each logged; a SAFE/WATCH alert `CLOSED` on `DELIVERED`; a WARNING/
  CRITICAL alert **not** closed by `DELIVERED` alone — stays `OPEN`/`ESCALATED` until `ACK`, then
  `CLOSED`; no failure is silent (every attempt has a row). = FR-6/FR-8, AC-5/AC-7. [NOTIFY-DEP live
  send/webhook deferred.]

---

## Phase 8 — Persistence + audit (Neon) [DB-DEP]

- **A801 — `FakeAlertStore` mirroring A203/A204 guarantees.**
  In-memory store: append `alert_dispatches`, supersede (link old→new), block delete, enforce
  `(assessment_id, assessment_version)` current-row uniqueness, append audit. Mirrors the
  `FakeReportStore` / `risk_assessments` fakes.
  **Acceptance:** insert assigns id; supersede links old→new and never deletes; delete blocked; a
  duplicate `(assessment_id, assessment_version)` among current rows is rejected/no-op (idempotency);
  append_audit records a kind. = A203 guarantees in-memory.

- **A802 — `persist_dispatch(store, result, audit)` [DB-DEP].**
  Write one `alert_dispatches` row (dispatched or withheld), linking `assessment_id`+version +
  `trace_id` + approval state/approver; append the matching audit row (`ALERT_DISPATCHED |
  ALERT_ESCALATED | ALERT_WITHHELD | ALERT_ERROR`). Auto-supersedes an existing current row for the
  same `(assessment_id, assessment_version)`.
  **Acceptance (fake store):** a dispatched alert, an escalated alert, a withheld
  (`CONSISTENCY_MISMATCH`) alert, and an error each produce exactly the expected row + audit kind;
  every row links its pinned provenance (assessment version + trace_id + approver when gated); a
  re-persist for the same version supersedes (no duplicate). = FR-13, AC-9/AC-12. [DB-DEP deferred.]

- **A803 — Idempotency + reproducibility test (FR-10/FR-11, AC-9/AC-10) [DB-DEP].**
  **Acceptance (fake store):** a redelivered trigger for an **already-handled current version** →
  **no duplicate** dispatch (no-op, no double-page); an alert against a **newer** assessment version →
  a new row that **supersedes**, never overwrites; a dispatched alert records exactly which assessment
  version + trace_id it acted on, so it is reproducible from those identities after the verdict is
  later superseded. = AC-9, AC-10. [DB-DEP deferred.]

---

## Phase 9 — The service (resolve + tier + assemble + gate + approve + dispatch + escalate + persist)

- **A901 — `run_alert(scope, *, sources, store, policy, templates, notifier, now, historical=False)`
  (orchestrator).**
  Wire the per-alert flow (plan §1): (1) resolve the verdict (A301) — absent →
  `WITHHELD/ASSESSMENT_NOT_FOUND`, stop; (2) decide tier (A401); (3) if `DASHBOARD_ONLY` → record the
  dashboard event, no push, close; (4) assemble the message (A501); (5) consistency gate (A502) —
  fail → `WITHHELD/CONSISTENCY_MISMATCH`, no dispatch, route to human, stop; (6) approval gate (A601)
  — `NEEDS_APPROVAL` without approval → hold `AWAITING_APPROVAL`, no dispatch; (7) dispatch via the
  port (A701/A702); (8) escalate to close (A703); (9) persist the row + audit (A802); (10) return a
  `DispatchSummary`. Per-alert failure isolation → structured status, **never raises** (FR-12).
  **Acceptance:** a SAFE scope → `DASHBOARD_ONLY`, no push, closed; a WATCH-FINAL → `AUTO_FIRE`,
  dispatched, closed on DELIVERED; a WARNING → held `AWAITING_APPROVAL` (no dispatch) until approved,
  then dispatched + escalates to ACK; a CRITICAL (pending) → gated on both axes; a contradicting
  message → `WITHHELD/CONSISTENCY_MISMATCH` (no dispatch); a missing verdict →
  `WITHHELD/ASSESSMENT_NOT_FOUND`; an injected notifier/read exception → a structured `ERROR` summary,
  nothing raises out (FR-12). = FR-1/FR-5/FR-12, AC-1/AC-11.

- **A902 — Never-crash test (FR-12, AC-11).**
  **Acceptance:** the four-scenario constitution set — normal / missing verdict / malformed scope /
  provider outage — each returns a **structured** `DispatchSummary` and **never throws**; a provider
  outage yields `ok=false` with the failure named, never a crash or a silently-dropped alert. = AC-11
  (never-crash).

---

## Phase 10 — Trigger wiring (n8n, downstream of Risk)

- **A1001 — n8n workflow definition (glue only, downstream of Risk).**
  `n8n/alert_escalation.workflow.json`: fires **on risk-assessment-available** for a bridge, invokes
  `run_alert` with the scope key, retries the **trigger**, branches on the structured `ok`, and
  routes delivery/ack callbacks back to advance `delivery_state`. **No tiering/consistency/approval/
  escalation logic in n8n.**
  **Acceptance:** workflow doc/export exists; risk-assessment-available → invoke path described per
  bridge; invoke carries the scope key + retries; branches only on `ok` (never on tier/state
  internals); contains **no** tiering/gate/dispatch/judgment logic (Const. III); `meta` self-declares
  glue only. [n8n/Neon live verification deferred.] Mirrors the DCA/Risk/Report glue workflows.

---

## Phase 11 — End-to-end test (every spec AC)

- **A1101 — Scenario harness (fake store + fake notifier).**
  Scripted inputs covering: SAFE (dashboard-only), WATCH-FINAL (auto-fire → DELIVERED close), WARNING
  (needs-approval → held → approved → escalate to ACK), CRITICAL (pending, gated both axes),
  authority-recipient WATCH (blast-radius override), a contradicting message (→ consistency
  fail-closed), a channel failure (retry→failover→escalate), a redelivered trigger (idempotent no-op),
  a superseded verdict (supersede), and a malformed scope (never-crash). Deterministic and replayable
  (no clock/random — `now` is a fixed seam); the shared fixture A1102 drives. Mirrors the Report G1101
  harness (and the `_alert_harness.py` module is underscore-prefixed + **uniquely named** to avoid the
  cross-suite `sys.modules` collision the Report build hit).
  **Acceptance:** every named scenario present; each yields its documented decision/delivery/
  escalation state; replaying the catalog twice gives identical summaries.

- **A1102 — E2E asserting AC-1…AC-12.**
  **Acceptance:** drive alerts through the real service; assert each AC manifests in `alert_dispatches`
  + audit: AC-1 assemble-only/verbatim · AC-2 settled mapping (SAFE/WATCH/WARNING/CRITICAL) · AC-3
  overrides (authority + pending) · AC-4 single un-bypassable gate · AC-5 severity-dependent close ·
  AC-6 distinct delivery states · AC-7 retry→failover→escalate logged · AC-8 consistency fail-closed
  (pos+neg) · AC-9 append-only idempotent · AC-10 reproducible · AC-11 never-crash 4-scenario · AC-12
  dual audit (append-only, DELETE-blocked, with approver + trace_id). = **all spec ACs**.

- **A1103 — Constitution check test (Const. I/II/III/IV/VI — inverted chokepoint).**
  **Acceptance:** never-crash (malformed/partial → structured summary, not raise); reads never mutate
  the Risk/SA/DCA tables; every dispatched band binds exactly to the source verdict (FR-9); **no model
  in any path** (assert the tiering + message + service import graph pulls in no model/SDK root — ast
  check, mirroring Report G1103); **the `needs_approval` gate EXISTS here and is the single
  un-bypassable dispatch point** (the inverse of G1103 — reuses A602). = Const. I/II/III/IV/VI.

---

## Phase 12 — README (module docs)

- **A1201 — Module README.**
  Inputs (the finalized verdict read by identity + what it provides), outputs (the dispatch + the
  closed decision/delivery/escalation/approval vocabulary + the `alert_dispatches` provenance), the
  **notify-not-re-judge** invariant, the **settled severity→approval table**, the **single
  un-bypassable `needs_approval` chokepoint**, the consistency gate (fail-closed), the
  severity-dependent escalation close, and explicit out-of-scope (no re-judging → Risk owns the
  verdict; no report authoring → Report; the human-review-clearing workflow → downstream).
  **Acceptance:** README present; documents inputs, outputs, the notify-not-re-judge invariant, the
  approval table, the chokepoint, and the trigger; matches the implemented contract. (Mirrors the
  DCA/Risk/Report READMEs.)

- **A1202 — "Change the roster / channels / retry / templates via config only" guide.**
  Step-by-step: change the contact roster/escalation order, the per-band channels, the retry/backoff/
  timeout values, the authority-recipient set, and the severity→message templates **without** touching
  tiering, gate, dispatch, escalation, or service code.
  **Acceptance:** changing a roster/channel/retry/template requires only config edits; validates
  "policy + safety numbers are config, not code" (and that they remain `TODO` until supplied).

---

## Dependency Order

```
P1 (config) ─┐
P2 (vocab + schema) ─┴─► P3 read (reuse), P4 tiering, P5 assemble+consistency (parallel after P1/P2)
                          P6 (approval gate — inverted chokepoint)
                          P7 (dispatch + escalation seam + state machine) ─┐
                                                                           ▼
                          P8 (persistence) ─► P9 (the service: resolve+tier+assemble+gate+dispatch+persist)
                                                                           └─► P10 (n8n trigger)
                                                                                 └─► P11 (E2E) ─► P12 (README)
```
- P4 (tiering) + P5 (assemble/consistency) + P6 (approval gate) are pure and testable before the
  notifier exists (fake notifier in P7).
- P9 assembles P3 + P4 + P5 + P6 + P7 + P8; P8 mirrors the DCA/SA/Risk/Report FakeStore.
- P11 requires P6–P9 (+P10 for the trigger path); A1103 reuses A602's single-chokepoint scan.

## Coverage (tasks ↔ acceptance criteria / decisions)

| AC / Decision | Tasks |
|---------------|-------|
| AC-1 assemble-only / verbatim, no re-judge | A501, A503, A901, A1102 |
| AC-2 settled severity→approval mapping | A401, A402, A1102 |
| AC-3 blast-radius + review_status overrides | A401, A402, A1102 |
| AC-4 single un-bypassable needs_approval gate | A601, A602, A1103, A1102 |
| AC-5 severity-dependent escalation close | A703, A1102 |
| AC-6 distinct delivery states (SENT≠DELIVERED≠ACK) | A702, A1102 |
| AC-7 retry→failover→escalate, never silent | A703, A1102 |
| AC-8 consistency gate fail-closed | A502, A503, A1102 |
| AC-9 append-only, idempotent | A801, A802, A803, A1102 |
| AC-10 reproducible from pinned version | A802, A803, A1102 |
| AC-11 never-crash 4-scenario | A901, A902, A1102 |
| AC-12 dual audit (append-only, DELETE-blocked) | A203, A802, A1102 |
| No model in any path (Principle IV) | A503, A1103 |
| Reads Risk/SA/DCA tables unchanged / new table only | A203, A301, A1103 |
| Single-chokepoint invariant (Const. I) | A602, A1103 |
| Decision vocabulary (tier/delivery/escalation/approval) | A201, A401, A702, A703 |

## Open (non-blocking) — carried config TODOs + design/cross-agent items

- **Contact roster + escalation order, retry/backoff counts, escalation timeout, per-band channels,
  authority-recipient set, severity→message templates** (`TODO` in A101/A102): logic buildable; only
  the config values change. Do not guess.
- **`alert_dispatches` schema sign-off (A203):** the four enums, the idempotency key, the mutable-
  columns discipline in the append+supersede trigger, the CHECKs (gated⇒approval_state present).
- **Shared upstream read (A301, plan Open Item 7):** reuse `report_generation/tools/
  risk_assessment_read.py` directly, or lift it to `agents/_shared/` to avoid a report→alert import
  dependency.
- **`NotifierPort` + provider (A701, [NOTIFY-DEP]):** the email/SMS provider (SMTP/SendGrid/SES;
  Twilio/SNS) and the delivery-receipt/webhook reconciliation that advances `delivery_state` — new
  build dependencies; the plan is otherwise provider-agnostic behind the port.
- **Acknowledgement mechanism (design):** how a human records an ACK (reply / dashboard action /
  signed link) that closes a WARNING/CRITICAL alert (FR-6).
- **Approval mechanism (design):** the concrete UI/queue by which a human approves a `NEEDS_APPROVAL`
  dispatch; the *gate enforcement* is in scope (A601/A602), the *UI* is downstream.
- **Audit home (A204):** extend the shared `decision_log` `decision_kind` enum (0004/0007/0009
  precedent) with the four `ALERT_*` kinds.
- **Dashboard / alert-timeline consumption (cross-agent):** how SAFE (dashboard-only) events and the
  alert timeline reach the Next.js frontend (`visual-output` "Alert timeline"), and how delivery/ack
  callbacks flow back.
- **[DB-DEP] / [NOTIFY-DEP] / n8n-live:** A203/A204/A802 schema + A701/A702/A703 real send + A1001
  n8n path need live Neon + a provider + n8n. Built against fakes now (fake store + fake notifier),
  live verification deferred — **flagged, not faked**. No provider is wired today.
```
