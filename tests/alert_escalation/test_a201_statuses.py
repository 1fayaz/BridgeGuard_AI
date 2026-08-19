"""A201 — statuses.py (closed outcome vocabulary).

Mirrors the Report/Risk/DCA/SA `statuses.py` style: small closed `str, Enum` sets the output
contract (A202), the schema (A203/A204), and persistence (A801/A802) all rely on.

Acceptance (tasks.md A201): all enum members representable; a DISPATCHED result may carry a
delivery + escalation + (optional) approval state; a WITHHELD result carries exactly one reason;
matches the spec output-contract vocabulary; the severity band enum is IMPORTED from
`risk_reasoning.statuses`, not re-defined here (one closed set of bands across the whole system).

The spec's output vocabulary in six enums:
  * DispatchDecision — the resolved tier: AUTO_FIRE / NEEDS_APPROVAL / DASHBOARD_ONLY (FR-2/FR-3)
  * DeliveryState    — QUEUED / SENT / DELIVERED / FAILED / ACKNOWLEDGED (FR-7; SENT != DELIVERED != ACK)
  * EscalationState  — OPEN / ESCALATED / CLOSED (FR-6)
  * ApprovalState    — AWAITING_APPROVAL / APPROVED / REJECTED (FR-5)
  * AlertOutcome     — DISPATCHED / WITHHELD / ERROR (structured, never a crash — FR-12)
  * WithheldReason   — ASSESSMENT_NOT_FOUND / CONSISTENCY_MISMATCH (the two no-dispatch cases)
"""
from __future__ import annotations

from enum import Enum

from agents.alert_escalation.statuses import (
    AlertOutcome,
    ApprovalState,
    DeliveryState,
    DispatchDecision,
    EscalationState,
    WithheldReason,
)


def test_dispatch_decisions_are_the_closed_set_of_three():
    assert {d.value for d in DispatchDecision} == {
        "AUTO_FIRE",
        "NEEDS_APPROVAL",
        "DASHBOARD_ONLY",
    }


def test_delivery_states_are_the_closed_set_of_five():
    assert {s.value for s in DeliveryState} == {
        "QUEUED",
        "SENT",
        "DELIVERED",
        "FAILED",
        "ACKNOWLEDGED",
    }


def test_escalation_states_are_the_closed_set_of_three():
    assert {s.value for s in EscalationState} == {"OPEN", "ESCALATED", "CLOSED"}


def test_approval_states_are_the_closed_set_of_three():
    assert {s.value for s in ApprovalState} == {
        "AWAITING_APPROVAL",
        "APPROVED",
        "REJECTED",
    }


def test_alert_outcomes_are_the_closed_set_of_three():
    assert {o.value for o in AlertOutcome} == {"DISPATCHED", "WITHHELD", "ERROR"}


def test_withheld_reasons_are_exactly_the_two_no_dispatch_cases():
    # WITHHELD (no dispatch) is deliberately narrow: the scope resolves to no verdict, or the
    # assembled message contradicts the verdict (the consistency gate, FR-9).
    assert {r.value for r in WithheldReason} == {
        "ASSESSMENT_NOT_FOUND",
        "CONSISTENCY_MISMATCH",
    }


def test_sent_delivered_acknowledged_are_distinct_members():
    # FR-7: a provider accept (SENT) is not delivery (DELIVERED) is not a human ack (ACKNOWLEDGED).
    assert DeliveryState.SENT != DeliveryState.DELIVERED != DeliveryState.ACKNOWLEDGED
    assert len({DeliveryState.SENT, DeliveryState.DELIVERED, DeliveryState.ACKNOWLEDGED}) == 3


def test_enums_are_str_backed_for_db_json_roundtrip():
    assert isinstance(DispatchDecision.AUTO_FIRE, str)
    assert isinstance(DeliveryState.DELIVERED, str)
    assert isinstance(EscalationState.OPEN, str)
    assert isinstance(ApprovalState.APPROVED, str)
    assert isinstance(AlertOutcome.DISPATCHED, str)
    assert isinstance(WithheldReason.CONSISTENCY_MISMATCH, str)
    assert DispatchDecision.AUTO_FIRE == "AUTO_FIRE"


def test_decision_and_delivery_vocabularies_are_disjoint():
    # A dispatch decision is never a delivery state and vice-versa.
    decisions = {d.value for d in DispatchDecision}
    deliveries = {s.value for s in DeliveryState}
    assert decisions.isdisjoint(deliveries)


def test_severity_and_review_status_are_imported_not_redeclared():
    # The band + finality vocabularies belong to the Risk agent; the Alert agent must import them,
    # not define its own copies (one closed set of bands across the whole system).
    import agents.alert_escalation.statuses as alert_statuses
    from agents.risk_reasoning.statuses import ReviewStatus, Severity

    # If the alert module re-exports them, they must BE the risk enums (same object), never a fork.
    if hasattr(alert_statuses, "Severity"):
        assert alert_statuses.Severity is Severity
    if hasattr(alert_statuses, "ReviewStatus"):
        assert alert_statuses.ReviewStatus is ReviewStatus


def test_all_six_enums_are_enum_subclasses():
    for e in (
        DispatchDecision,
        DeliveryState,
        EscalationState,
        ApprovalState,
        AlertOutcome,
        WithheldReason,
    ):
        assert issubclass(e, Enum)
