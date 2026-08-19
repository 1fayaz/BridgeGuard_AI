"""Tiering (A401) — the settled severity->approval decision (FR-2/FR-3).

This is the ONE place the settled mapping lives. Given a finalized verdict (the risk_assessments
row) and the alert policy, `decide_tier` returns a DispatchDecision plus the resolved
channel/recipient. It is a pure function — no I/O, no model — so the settled table is auditable in
one spot and testable exhaustively (A402).

The settled table (spec + clarification interview):

  SAFE                    -> DASHBOARD_ONLY   (routine monitoring pages no one; no push)
  WATCH & review = FINAL  -> AUTO_FIRE        (internal notification, no human approval)
  WARNING / CRITICAL      -> NEEDS_APPROVAL    (a human signs off before dispatch)

Overrides applied on top of the band default (either can only RAISE the gate, never lower it):
  * any authority-facing recipient       -> NEEDS_APPROVAL, regardless of band (blast radius)
  * review_status = PENDING_HUMAN_REVIEW  -> never AUTO_FIRE at any band (finality axis, FR-11)
  * a withheld-score verdict (no band)    -> NEEDS_APPROVAL (a human must see it)

The two axes are orthogonal and both must be satisfied before an auto-fire: a FINAL WARNING is
gated by its band; a PENDING SAFE still cannot auto-fire (though SAFE has no push to gate at all).
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.statuses import DispatchDecision
from agents.risk_reasoning.statuses import ReviewStatus, Severity


@dataclass(frozen=True, slots=True)
class TierDecision:
    """The resolved dispatch tier for a verdict, plus the routing and a short human-readable why."""

    decision: DispatchDecision
    channel: str | None
    recipient: str | None
    reason: str


def decide_tier(verdict: dict, policy: AlertPolicy) -> TierDecision:
    """Resolve the dispatch tier for a finalized verdict (pure; FR-2/FR-3)."""
    severity_value = verdict.get("severity")
    review_value = verdict.get("review_status")
    is_pending = review_value == ReviewStatus.PENDING_HUMAN_REVIEW.value

    # --- Withheld-score verdict: no severity band at all. A human must see it (FR-6 upstream). ---
    if severity_value is None:
        return TierDecision(
            decision=DispatchDecision.NEEDS_APPROVAL,
            channel=None,
            recipient=None,
            reason="withheld-score verdict has no band; routed to human approval",
        )

    # --- SAFE: dashboard/timeline only, never an outbound push (nothing to gate). ---
    if severity_value == Severity.SAFE.value:
        return TierDecision(
            decision=DispatchDecision.DASHBOARD_ONLY,
            channel=None,
            recipient=None,
            reason="SAFE -> dashboard-only, no outbound notification",
        )

    channel = policy.channel_for(severity_value)
    recipient = policy.recipient_for(severity_value)

    # --- WARNING / CRITICAL: gated by band default. ---
    if severity_value in (Severity.WARNING.value, Severity.CRITICAL.value):
        return TierDecision(
            decision=DispatchDecision.NEEDS_APPROVAL,
            channel=channel,
            recipient=recipient,
            reason=f"{severity_value} band requires human approval before dispatch",
        )

    # --- WATCH: auto-fire ONLY when both axes permit and the recipient is not authority-facing. ---
    #     (severity_value is WATCH here — the only remaining band.)
    if is_pending:
        return TierDecision(
            decision=DispatchDecision.NEEDS_APPROVAL,
            channel=channel,
            recipient=recipient,
            reason="WATCH but verdict is PENDING_HUMAN_REVIEW; never auto-fires (FR-11)",
        )
    if policy.is_authority_recipient(recipient):
        return TierDecision(
            decision=DispatchDecision.NEEDS_APPROVAL,
            channel=channel,
            recipient=recipient,
            reason="WATCH but recipient is authority-facing; blast-radius override (FR-3)",
        )
    return TierDecision(
        decision=DispatchDecision.AUTO_FIRE,
        channel=channel,
        recipient=recipient,
        reason="WATCH + FINAL + internal recipient -> auto-fire",
    )
