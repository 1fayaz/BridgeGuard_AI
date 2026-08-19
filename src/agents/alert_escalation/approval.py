"""The approval gate (A601) — the human-approval chokepoint in code (FR-5).

This is the single most important safety control in the agent: a NEEDS_APPROVAL dispatch is blocked
until a human approval is recorded, and there is NO code path that lets a gated dispatch proceed
without one. An un-gated decision (AUTO_FIRE / DASHBOARD_ONLY) passes through — it needs no sign-off.

`may_dispatch` is True for a NEEDS_APPROVAL decision ONLY when the recorded approval is APPROVED
with an identified approver (an anonymous approval cannot authorise a real-world action — FR-5
audit). AWAITING_APPROVAL and REJECTED both hold the dispatch (nothing is sent), and the state is
recorded either way so the sign-off (or its refusal) is auditable.

Pure decision function: `approval` is the recorded human decision (a (state, approver) pair, or
None if none has been recorded yet); the gate maps it to a may_dispatch verdict + the audited
ApprovalState. It performs no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.alert_escalation.statuses import ApprovalState, DispatchDecision


@dataclass(frozen=True, slots=True)
class ApprovalGateResult:
    """Whether a dispatch may proceed, plus the audited approval state + approver (when gated)."""

    may_dispatch: bool
    approval_state: ApprovalState | None
    approved_by: str | None


def approval_gate(
    decision: DispatchDecision,
    *,
    approval: tuple[str, str | None] | None,
) -> ApprovalGateResult:
    """Gate a dispatch on a recorded human approval (A601). Pure; no bypass path (FR-5)."""
    # Un-gated tiers proceed without any approval, and a stray approval against them is ignored
    # (it stays un-gated — approval_state None — so it can never be recorded as "approved").
    if decision is not DispatchDecision.NEEDS_APPROVAL:
        return ApprovalGateResult(may_dispatch=True, approval_state=None, approved_by=None)

    # Gated: with no recorded decision yet, the dispatch is HELD awaiting approval.
    if approval is None:
        return ApprovalGateResult(
            may_dispatch=False,
            approval_state=ApprovalState.AWAITING_APPROVAL,
            approved_by=None,
        )

    state_value, approver = approval
    state = ApprovalState(state_value)

    if state is ApprovalState.APPROVED:
        # An APPROVED with no approver identity cannot authorise a real-world action (FR-5 audit).
        if not approver:
            raise ValueError("an APPROVED gated dispatch must record who approved it (FR-5 audit)")
        return ApprovalGateResult(may_dispatch=True, approval_state=state, approved_by=approver)

    # AWAITING_APPROVAL or REJECTED -> held; nothing is dispatched, but the state is recorded.
    return ApprovalGateResult(may_dispatch=False, approval_state=state, approved_by=approver)
