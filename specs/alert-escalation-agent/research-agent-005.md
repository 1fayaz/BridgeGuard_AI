# Findings: Alert & Escalation Agent (Agent 005)

**Type:** Research findings — NOT a design. No architecture, no code. Names candidate tech; decides nothing.
**Date:** 2026-07-09
**Anchors:** `CLAUDE.md` (alert dispatch is a `needs_approval`-gated real-world action; prefer SDK
primitives — guardrails, tracing; trace-from-day-one); `.specify/memory/constitution.md` v2.1.0
(Principles I human-in-the-loop, II data-immutable, III modular contracts, IV reliability-over-cleverness,
VI auditability, VII trace); `skills/bridgeguard-skills-README.md` (bands SAFE 0–30 / WATCH 31–60 /
WARNING 61–80 / CRITICAL 81–100; "Alert timeline" visual-output); `specs/risk-reasoning-agent/spec.md`
(FR-5 gate-lives-downstream-here, FR-11 CRITICAL → `PENDING_HUMAN_REVIEW`, Open-Item "confirm Alert
Agent is the single un-bypassable chokepoint"); `db/migrations/0006_risk_assessments.sql` (the verdict
row this agent consumes); precedents `research-agent-003.md` (Risk, the guardrail case) +
`research-agent-004.md` (Report, Option A).

> Scope note: this agent consumes a **completed, persisted risk assessment** (score, severity,
> recommendation, verbatim explanation, `review_status`, `trace_id`) and turns it into **dispatched
> notifications to humans** (email/SMS), escalating until acknowledged. It is the system's
> **real-world-action chokepoint** — the one place `needs_approval` is mandatory (CLAUDE.md;
> Risk FR-5). This doc investigates only the three questions below; it does not decide the design.

---

## Framing: this is the chokepoint — and it consumes a verdict that ALREADY carries a review flag

Two human-in-the-loop concepts collide here and must **not** be conflated:

- **`review_status` (finality of the recommendation)** — set *upstream* by Risk. **Every CRITICAL
  is already emitted `PENDING_HUMAN_REVIEW`** (FR-11), and FR-11 binds *this* agent by name: it
  MUST NOT treat a `PENDING_HUMAN_REVIEW` verdict as a settled, actionable fact until a human clears it.
- **`needs_approval` (gate on the physical dispatch)** — set *here* (FR-5): the human sign-off on
  the act of notifying authorities / recommending closure.

These are **orthogonal axes**, and every downstream question below turns on keeping them separate.
**Open (gates Q2's form):** is this a model-calling Agent, or Option A (deterministic routing +
templated messages, like DCA/SA/Report)? Routing and channel selection are rule-expressible; a
model is only arguably justified for composing an ambiguous *escalation* narrative — likely still
Option A. Unresolved; noted, not decided.

## 1. Tiered `needs_approval` (Watch auto-fires, Critical always pauses) vs. every-alert-signs-off?

**Read: a tiered gate is defensible and matches the SDK `needs_approval`-per-tool pattern — but
only with two non-negotiable riders, and the *threshold itself is config a stakeholder sets, not a
value to guess.*** The user's framing is sound in shape; the safety lives in the riders:

- **Rider A — the gate composes with `review_status`, it does not replace it.** A verdict that is
  `PENDING_HUMAN_REVIEW` is **never** auto-fired regardless of band (FR-11). Since every CRITICAL is
  already `PENDING_HUMAN_REVIEW` upstream, "Critical always pauses" falls out *for free* — but the
  rule must be stated as *"auto-fire only a `FINAL` verdict at/below the configured band"*, so a
  future `FINAL`-but-high verdict can't slip through a band-only check.
- **Rider B — blast radius, not just band, sets the tier.** A WATCH "increase inspection frequency"
  note to the internal monitoring team is low-consequence and reversible; a dispatch to a municipal
  authority is not — even at the same band. The gate should key on *the action's consequence*
  (recipient + channel + implied physical action), consistent with the constitution's
  reversibility/blast-radius test, not on severity alone.
- **The alternative (every alert human-signed) is the safest floor** but carries alert-fatigue /
  delayed-routine-notification cost that can itself degrade safety. **Do not guess** where the
  auto-fire line sits — the band cut-point, and which recipients/actions may ever auto-fire, are a
  **government-stakeholder policy decision** (TODO/config sentinel until supplied), exactly like the
  Risk agent's weights and coverage floor.

**Unknowns:** the config severity→gate mapping; whether "auto-fire" ever includes an
authority-facing channel or only internal ones; who the approving human is and their SLA.

## 2. Output guardrail — block an alert claiming "safe" while the score says otherwise?

**Read: yes — a fail-closed *consistency* invariant is high-value here; its *form* depends on the
open model/no-model question (§Framing).** This is the Alert-Agent analogue of Risk's numeric-
provenance guardrail (003 §4), and CLAUDE.md prefers the SDK primitive:

- **The contradiction to catch is real:** an alert whose body/severity-label says "safe/routine"
  while the pinned `risk_score`/`severity` is WARNING/CRITICAL would mislead an engineer at the worst
  moment. A guardrail tripwires on message-band ≠ source-band and **blocks before it reaches a human**.
- **A second contradiction on the *other* axis:** an alert that presents a `PENDING_HUMAN_REVIEW`
  verdict as *settled/actionable* also contradicts the record (FR-11) and should trip the same gate.
- **Form depends on architecture:** if the agent composes any *new* natural-language (model case),
  an **SDK output guardrail** validating the drafted message against the source row is the right
  primitive (tripwire → regenerate-once → fail-closed, mirroring 003). If the agent only *relays*
  the Risk verdict verbatim (Option A, like Report's assemble-not-re-decide), the contradiction
  largely *can't arise* — but a cheap deterministic assertion (`assert message_band == source_band`,
  fail-closed) is still worth keeping as an invariant. Either way: **fail-closed, never fire the
  contradicting alert.**

**Unknowns:** exact match rule (band equality vs. richer semantic check); whether the guardrail
regenerates (model case) or simply blocks + routes to human (template case).

## 3. Notification channels (email/SMS) and how delivery failures are handled and logged

**Read: silent non-delivery is the catastrophic failure mode — so "sent" ≠ "delivered" ≠
"acknowledged" must be distinct logged states, and every attempt is append-only audited.** This is
the "Escalation" half of the agent's name.

- **Channels (candidate tech, decide nothing):** email via SMTP or a provider (SendGrid / SES);
  SMS via a provider (Twilio / SNS). Likely MCP-tool or provider integrations, with **n8n as glue**
  (consistent with the DCA/SA/Report fire-and-notify pattern). Each dispatch tool is a `needs_approval`
  candidate per Q1.
- **Delivery is asynchronous and confirmation is out-of-band:** provider *accepted* ≠ *delivered to a
  human*. The agent must model at least `QUEUED → SENT → DELIVERED / FAILED`, reconciled from provider
  delivery-receipts/webhooks — never assume success on a 200 from the send call.
- **Failure handling = retry → fail-over → escalate:** bounded retry with backoff on a channel;
  **fail-over** to a second channel (SMS if email fails); and **escalation** — if no channel confirms
  delivery (and, for high severity, no human *acknowledgement*) within a window, escalate to the next
  contact / on-call. Acknowledgement, not mere delivery, is the closing condition for a Critical.
- **Logging (Principle II / VI):** every attempt is an **append-only** row — channel, recipient,
  provider message-id, state, timestamp, the source `assessment_id`/version, and the `trace_id` —
  mirroring `risk_assessments`' correct-by-append + DELETE-blocked discipline. A dispatch history a
  regulator relies on is permanent.
- **Never-crash structured status** (like `CycleSummary`/`AssessmentSummary`/`ReportSummary`): a
  `DispatchSummary { ok, delivered_channels, failed_channels, escalated }`; a provider outage is a
  logged status + retry/escalate, never an exception.

**Unknowns (all config / stakeholder policy — do not guess SLAs for a safety system):** retry counts
+ backoff; escalation timeout window; the contact/on-call roster; primary channel per severity;
whether human *acknowledgement* is required (and for which bands) vs. delivery-confirmation alone.

---

## Cross-cutting: this agent is the single un-bypassable approval chokepoint

Risk 003 §2 and FR-5 both defer the real-world-action gate to *here*, and Risk's Open Items ask to
**confirm this is the system's *single* un-bypassable dispatch point** (Principle I "cannot be
bypassed in code"). That is a design invariant to pin: no other module may notify an authority or
change signage un-gated. If the agent calls a model, **tracing is on from the first run** (CLAUDE.md,
VII); its dispatch history is append-only regardless (II/VI).

---

## Summary

| | Status |
|---|---|
| **What's settled (read)** | Tiered `needs_approval` is defensible **only** if it (a) composes with `review_status` — never auto-fire a `PENDING_HUMAN_REVIEW` verdict (FR-11), and (b) keys on action blast-radius, not band alone; a fail-closed **contradiction guardrail** (message-band ≠ source-band, or "settled" claim on a pending verdict) is high-value; **silent non-delivery is the worst failure mode** → distinct `SENT/DELIVERED/ACKNOWLEDGED` states, append-only audit, retry → fail-over → escalate, never-crash `DispatchSummary`. This is the **single un-bypassable dispatch chokepoint** (FR-5). |
| **Main options** | Model-calling Agent vs. Option A deterministic router (gates the guardrail's *form*: SDK output-guardrail vs. deterministic assertion); channel providers (SMTP/SendGrid/SES, Twilio/SNS); n8n-glue vs. in-service dispatch; delivery-confirmation-only vs. required human acknowledgement per band. |
| **Biggest unknowns (config / stakeholder policy — do not guess)** | (1) severity→gate mapping + which actions may ever auto-fire; (2) retry/backoff + escalation timeout + on-call roster + primary-channel-per-severity; (3) model vs. no-model; (4) acknowledgement-required bands; (5) confirmation of the single-chokepoint invariant in code. |

**Sources:** OpenAI Agents SDK docs (`needs_approval` human-in-the-loop, output guardrails, tracing);
`CLAUDE.md`; `.specify/memory/constitution.md` v2.1.0 (I, II, III, IV, VI, VII);
`skills/bridgeguard-skills-README.md`; `specs/risk-reasoning-agent/spec.md` + `research-agent-003.md`;
`specs/report-generation-agent/research-agent-004.md`; `db/migrations/0006_risk_assessments.sql`;
email/SMS provider delivery-receipt/webhook docs (Twilio, SES/SNS, SendGrid).
