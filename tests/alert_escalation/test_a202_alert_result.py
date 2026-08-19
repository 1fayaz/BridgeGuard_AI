"""A202 — output payload shapes (typed AlertResult + DispatchSummary).

`AlertResult` is the one record the alert service emits per dispatch; `DispatchSummary` is the
plain dict it hands back to n8n (branches on `ok`). Like the Report `ReportResult`, the coherent
shapes are enforced at construction so an invalid output cannot exist as an object.

Acceptance (tasks.md A202): constructs typed; a DISPATCHED result carries its decision +
delivery/escalation states + pinned provenance (assessment_id+version, trace_id); a WITHHELD result
carries exactly one reason and no dispatch details (no delivered channel); `__post_init__` enforces
coherent shapes; `ok` is True only when the alert reached its band's close condition (a CLOSED
dispatch). Matches the spec output contract.
"""
from __future__ import annotations

import pytest

from agents.alert_escalation.alert_result import AlertResult, DispatchSummary
from agents.alert_escalation.statuses import (
    AlertOutcome,
    ApprovalState,
    DeliveryState,
    DispatchDecision,
    EscalationState,
    WithheldReason,
)


def _dispatched(**over):
    base = dict(
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_id=1001,
        assessment_version=3,
        outcome=AlertOutcome.DISPATCHED,
        dispatch_decision=DispatchDecision.AUTO_FIRE,
        channel="email",
        recipient="engineer@gov",
        provider_message_id="prov-abc",
        delivery_state=DeliveryState.DELIVERED,
        escalation_state=EscalationState.CLOSED,
        close_reason=DeliveryState.DELIVERED,
        approval_state=None,
        approved_by=None,
        trace_id="trace-xyz",
        attempted_at="ATTEMPTED_AT_SEAM",
        withheld_reason=None,
    )
    base.update(over)
    return AlertResult(**base)


# ------------------------------------------------------------------ DISPATCHED ---
def test_dispatched_result_constructs_with_decision_states_and_provenance():
    r = _dispatched()
    assert r.outcome is AlertOutcome.DISPATCHED
    assert r.dispatch_decision is DispatchDecision.AUTO_FIRE
    assert r.delivery_state is DeliveryState.DELIVERED
    assert r.escalation_state is EscalationState.CLOSED
    assert r.assessment_id == 1001 and r.assessment_version == 3
    assert r.trace_id == "trace-xyz"


def test_dispatched_needs_approval_records_the_approver():
    r = _dispatched(
        dispatch_decision=DispatchDecision.NEEDS_APPROVAL,
        approval_state=ApprovalState.APPROVED,
        approved_by="reviewer@gov",
    )
    assert r.approval_state is ApprovalState.APPROVED
    assert r.approved_by == "reviewer@gov"


def test_dispatched_held_awaiting_approval_is_open_not_closed():
    # A gated alert with no approval yet: nothing sent, escalation OPEN — a valid DISPATCHED shape.
    r = _dispatched(
        dispatch_decision=DispatchDecision.NEEDS_APPROVAL,
        approval_state=ApprovalState.AWAITING_APPROVAL,
        channel=None,
        recipient=None,
        provider_message_id=None,
        delivery_state=None,
        escalation_state=EscalationState.OPEN,
        close_reason=None,
    )
    assert r.escalation_state is EscalationState.OPEN
    assert r.delivery_state is None


def test_dashboard_only_dispatched_has_no_push_channel():
    # SAFE dashboard-only: recorded + closed, but no outbound push (no channel/delivery).
    r = _dispatched(
        dispatch_decision=DispatchDecision.DASHBOARD_ONLY,
        channel=None,
        recipient=None,
        provider_message_id=None,
        delivery_state=None,
        escalation_state=EscalationState.CLOSED,
        close_reason=None,
    )
    assert r.dispatch_decision is DispatchDecision.DASHBOARD_ONLY
    assert r.channel is None


def test_dispatched_without_a_decision_is_rejected():
    with pytest.raises(ValueError):
        _dispatched(dispatch_decision=None)


def test_dispatched_with_a_withheld_reason_is_rejected():
    # A dispatched alert cannot also claim a no-dispatch reason.
    with pytest.raises(ValueError):
        _dispatched(withheld_reason=WithheldReason.CONSISTENCY_MISMATCH)


def test_approved_without_an_approver_is_rejected():
    # FR-5 audit: an APPROVED gated dispatch must record WHO approved.
    with pytest.raises(ValueError):
        _dispatched(
            dispatch_decision=DispatchDecision.NEEDS_APPROVAL,
            approval_state=ApprovalState.APPROVED,
            approved_by=None,
        )


# ------------------------------------------------------------------ WITHHELD ---
def test_withheld_result_constructs_with_reason_and_no_dispatch_details():
    r = _dispatched(
        outcome=AlertOutcome.WITHHELD,
        withheld_reason=WithheldReason.CONSISTENCY_MISMATCH,
        dispatch_decision=None,
        channel=None,
        recipient=None,
        provider_message_id=None,
        delivery_state=None,
        escalation_state=None,
        close_reason=None,
        approval_state=None,
        approved_by=None,
    )
    assert r.outcome is AlertOutcome.WITHHELD
    assert r.withheld_reason is WithheldReason.CONSISTENCY_MISMATCH
    assert r.delivery_state is None and r.channel is None


def test_withheld_without_a_reason_is_rejected():
    with pytest.raises(ValueError):
        _dispatched(
            outcome=AlertOutcome.WITHHELD,
            withheld_reason=None,
            dispatch_decision=None,
            channel=None,
            recipient=None,
            provider_message_id=None,
            delivery_state=None,
            escalation_state=None,
            close_reason=None,
        )


def test_withheld_with_a_delivered_channel_is_rejected():
    # A withheld alert dispatched nothing — it cannot carry a delivery state / channel.
    with pytest.raises(ValueError):
        _dispatched(
            outcome=AlertOutcome.WITHHELD,
            withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
            dispatch_decision=None,
            channel="email",
            delivery_state=DeliveryState.DELIVERED,
        )


# ------------------------------------------------------------------ ERROR ---
def test_error_result_carries_neither_reason_nor_dispatch_details():
    r = _dispatched(
        outcome=AlertOutcome.ERROR,
        withheld_reason=None,
        dispatch_decision=None,
        channel=None,
        recipient=None,
        provider_message_id=None,
        delivery_state=None,
        escalation_state=None,
        close_reason=None,
        approval_state=None,
        approved_by=None,
    )
    assert r.outcome is AlertOutcome.ERROR
    assert r.dispatch_decision is None and r.withheld_reason is None


def test_error_with_a_dispatch_decision_is_rejected():
    with pytest.raises(ValueError):
        _dispatched(
            outcome=AlertOutcome.ERROR,
            dispatch_decision=DispatchDecision.AUTO_FIRE,
            withheld_reason=None,
        )


# ------------------------------------------------------------------ DispatchSummary ---
def test_summary_from_closed_dispatch_is_ok_true():
    s = DispatchSummary.from_result(_dispatched())  # DELIVERED + CLOSED
    assert s.ok is True
    assert s.outcome == AlertOutcome.DISPATCHED
    assert "email" in s.delivered_channels
    assert s.withheld_reason is None
    assert s.error is None


def test_summary_from_open_dispatch_is_ok_false():
    # Still escalating / awaiting ack -> not closed -> not ok yet.
    r = _dispatched(
        delivery_state=DeliveryState.SENT,
        escalation_state=EscalationState.OPEN,
        close_reason=None,
    )
    s = DispatchSummary.from_result(r)
    assert s.ok is False
    assert "email" not in s.delivered_channels


def test_summary_escalated_flag_reflects_state():
    r = _dispatched(escalation_state=EscalationState.ESCALATED, close_reason=None,
                    delivery_state=DeliveryState.FAILED)
    s = DispatchSummary.from_result(r)
    assert s.escalated is True
    assert "email" in s.failed_channels


def test_summary_from_withheld_is_ok_false_with_reason():
    r = _dispatched(
        outcome=AlertOutcome.WITHHELD,
        withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
        dispatch_decision=None,
        channel=None,
        recipient=None,
        provider_message_id=None,
        delivery_state=None,
        escalation_state=None,
        close_reason=None,
    )
    s = DispatchSummary.from_result(r)
    assert s.ok is False
    assert s.outcome == AlertOutcome.WITHHELD
    assert s.withheld_reason is WithheldReason.ASSESSMENT_NOT_FOUND


def test_summary_from_error_is_ok_false():
    s = DispatchSummary.from_error("provider unreachable")
    assert s.ok is False
    assert s.outcome == AlertOutcome.ERROR
    assert s.error == "provider unreachable"


def test_summary_is_a_plain_serialisable_shape():
    s = DispatchSummary.from_result(_dispatched())
    d = s.as_dict()
    assert d["ok"] is True
    assert d["outcome"] == "DISPATCHED"
    assert d["dispatch_decision"] == "AUTO_FIRE"
    assert d["delivered_channels"] == ["email"]
    assert d["escalated"] is False
