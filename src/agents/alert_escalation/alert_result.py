"""Output payload (A202) — the typed AlertResult + the DispatchSummary the service returns.

`AlertResult` is the one record this agent emits per run (spec output contract): what happened to
the alert, the resolved dispatch tier, the delivery + escalation + (optional) approval state, and
the pinned provenance that makes it reproducible (FR-11/FR-13). `DispatchSummary` is the plain,
serialisable shape the service hands back to n8n, which branches on `ok` — it carries the
outcome/decision/channels, never a live handle.

Like the Report `ReportResult`, the coherent shapes are enforced at construction so an invalid
output cannot exist as an object:
  - DISPATCHED ⇒ a dispatch_decision is present and NO withheld_reason (a dispatched alert cannot
    also claim a no-dispatch reason). An APPROVED gated dispatch must record who approved (FR-5).
  - WITHHELD ⇒ exactly one withheld_reason, NO dispatch details (no decision/channel/delivery) —
    nothing was sent.
  - ERROR ⇒ neither a dispatch_decision, a withheld_reason, nor dispatch details (a structured
    failure, FR-12).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.alert_escalation.statuses import (
    AlertOutcome,
    ApprovalState,
    DeliveryState,
    DispatchDecision,
    EscalationState,
    WithheldReason,
)


@dataclass(frozen=True, slots=True)
class AlertResult:
    """One alert dispatch result (spec output contract). Validated at construction."""

    bridge_id: str
    cycle_id: str

    # --- Which finalized assessment this alert acted on (identity + version, FR-11) ---
    assessment_id: int
    assessment_version: int

    # --- What happened (FR-12 closed vocabulary) ---
    outcome: AlertOutcome
    withheld_reason: WithheldReason | None

    # --- The resolved dispatch tier — None unless DISPATCHED (FR-2/FR-3) ---
    dispatch_decision: DispatchDecision | None

    # --- The dispatch itself (None on a dashboard-only / awaiting-approval / withheld / error) ---
    channel: str | None
    recipient: str | None
    provider_message_id: str | None
    delivery_state: DeliveryState | None
    escalation_state: EscalationState | None
    close_reason: DeliveryState | None

    # --- The human sign-off audit (None unless the tier was NEEDS_APPROVAL, FR-5) ---
    approval_state: ApprovalState | None
    approved_by: str | None

    # --- Pinned provenance (FR-11/FR-13: reproducible + end-to-end traceable) ---
    trace_id: str
    attempted_at: str            # timestamp seam (passed in; no clock in the service)

    def __post_init__(self) -> None:
        if self.outcome is AlertOutcome.DISPATCHED:
            if self.dispatch_decision is None:
                raise ValueError("a DISPATCHED result must carry a dispatch_decision (FR-2)")
            if self.withheld_reason is not None:
                raise ValueError(
                    "a DISPATCHED result must not carry a withheld_reason (a dispatched alert "
                    "cannot also claim a no-dispatch reason)"
                )
            if self.approval_state is ApprovalState.APPROVED and not self.approved_by:
                raise ValueError(
                    "an APPROVED gated dispatch must record who approved it (FR-5 audit)"
                )
        elif self.outcome is AlertOutcome.WITHHELD:
            if self.withheld_reason is None:
                raise ValueError("a WITHHELD result must carry exactly one withheld_reason")
            if self.dispatch_decision is not None:
                raise ValueError("a WITHHELD result must not carry a dispatch_decision (nothing sent)")
            if self.channel is not None or self.delivery_state is not None:
                raise ValueError("a WITHHELD result must not carry dispatch details (nothing sent)")
        else:  # ERROR
            if self.dispatch_decision is not None:
                raise ValueError("an ERROR result must not carry a dispatch_decision")
            if self.withheld_reason is not None:
                raise ValueError("an ERROR result must not carry a withheld_reason")
            if self.channel is not None or self.delivery_state is not None:
                raise ValueError("an ERROR result must not carry dispatch details")


@dataclass(frozen=True, slots=True)
class DispatchSummary:
    """The plain shape the service returns to n8n (branches on `ok`).

    Carries the outcome, the resolved decision, and which channels delivered/failed — never a live
    provider handle. `ok` is True only when the alert reached its band's close condition
    (escalation CLOSED), so a still-escalating or awaiting-approval alert is not yet `ok`.
    """

    ok: bool
    outcome: AlertOutcome
    dispatch_decision: DispatchDecision | None = None
    delivered_channels: tuple[str, ...] = ()
    failed_channels: tuple[str, ...] = ()
    escalated: bool = False
    withheld_reason: WithheldReason | None = None
    error: str | None = None

    @classmethod
    def from_result(cls, result: AlertResult) -> "DispatchSummary":
        closed = result.escalation_state is EscalationState.CLOSED
        delivered: tuple[str, ...] = ()
        failed: tuple[str, ...] = ()
        if result.channel is not None:
            if result.delivery_state in (DeliveryState.DELIVERED, DeliveryState.ACKNOWLEDGED):
                delivered = (result.channel,)
            elif result.delivery_state is DeliveryState.FAILED:
                failed = (result.channel,)
        return cls(
            ok=result.outcome is AlertOutcome.DISPATCHED and closed,
            outcome=result.outcome,
            dispatch_decision=result.dispatch_decision,
            delivered_channels=delivered,
            failed_channels=failed,
            escalated=result.escalation_state is EscalationState.ESCALATED,
            withheld_reason=result.withheld_reason,
            error=None,
        )

    @classmethod
    def from_error(cls, message: str) -> "DispatchSummary":
        return cls(ok=False, outcome=AlertOutcome.ERROR, error=message)

    def as_dict(self) -> dict[str, Any]:
        """A plain JSON-serialisable dict (enum values unwrapped to their strings)."""
        return {
            "ok": self.ok,
            "outcome": self.outcome.value,
            "dispatch_decision": self.dispatch_decision.value if self.dispatch_decision else None,
            "delivered_channels": list(self.delivered_channels),
            "failed_channels": list(self.failed_channels),
            "escalated": self.escalated,
            "withheld_reason": self.withheld_reason.value if self.withheld_reason else None,
            "error": self.error,
        }
