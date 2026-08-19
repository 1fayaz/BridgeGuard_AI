"""A601 — approval_gate(decision, approval) (pure) — no gated dispatch without a recorded approval.

This is the human-approval chokepoint in code (FR-5). For a NEEDS_APPROVAL decision, dispatch is
blocked unless a recorded APPROVED (with an approver) is present:

  NEEDS_APPROVAL + no approval / AWAITING_APPROVAL -> HELD (no dispatch)
  NEEDS_APPROVAL + APPROVED (+ approver)            -> may dispatch
  NEEDS_APPROVAL + REJECTED                          -> no dispatch, recorded
  AUTO_FIRE / DASHBOARD_ONLY                          -> pass through (no approval needed)

There is NO path that lets a gated dispatch proceed without an approval. Pure decision function.

Acceptance (tasks.md A601): a gated decision with no approval is held; with APPROVED+approver it
proceeds; with REJECTED it is declined and recorded; an un-gated decision proceeds without approval.
"""
from __future__ import annotations

import pytest

from agents.alert_escalation.approval import ApprovalGateResult, approval_gate
from agents.alert_escalation.statuses import ApprovalState, DispatchDecision


# ------------------------------------------------------------------ un-gated pass-through ---
def test_auto_fire_proceeds_without_approval():
    r = approval_gate(DispatchDecision.AUTO_FIRE, approval=None)
    assert r.may_dispatch is True
    assert r.approval_state is None          # un-gated: no approval recorded
    assert r.approved_by is None


def test_dashboard_only_proceeds_without_approval():
    r = approval_gate(DispatchDecision.DASHBOARD_ONLY, approval=None)
    assert r.may_dispatch is True
    assert r.approval_state is None


def test_ungated_decision_rejects_a_stray_approval():
    # An approval recorded against an un-gated action is a misuse — the gate must not accept it as
    # meaningful (it stays un-gated; approval_state None), never silently "approved".
    r = approval_gate(DispatchDecision.AUTO_FIRE, approval=("APPROVED", "someone@gov"))
    assert r.may_dispatch is True
    assert r.approval_state is None


# ------------------------------------------------------------------ gated: held ---
def test_needs_approval_with_no_approval_is_held():
    r = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=None)
    assert r.may_dispatch is False
    assert r.approval_state is ApprovalState.AWAITING_APPROVAL
    assert r.approved_by is None


def test_needs_approval_still_awaiting_is_held():
    r = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("AWAITING_APPROVAL", None))
    assert r.may_dispatch is False
    assert r.approval_state is ApprovalState.AWAITING_APPROVAL


# ------------------------------------------------------------------ gated: approved ---
def test_needs_approval_with_recorded_approval_proceeds():
    r = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("APPROVED", "reviewer@gov"))
    assert r.may_dispatch is True
    assert r.approval_state is ApprovalState.APPROVED
    assert r.approved_by == "reviewer@gov"


def test_approved_without_an_approver_is_refused_not_dispatched():
    # FR-5 audit: an APPROVED with no approver identity cannot authorise a real-world action.
    with pytest.raises(ValueError):
        approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("APPROVED", None))


# ------------------------------------------------------------------ gated: rejected ---
def test_needs_approval_rejected_is_declined_and_recorded():
    r = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("REJECTED", "reviewer@gov"))
    assert r.may_dispatch is False
    assert r.approval_state is ApprovalState.REJECTED
    assert r.approved_by == "reviewer@gov"       # who declined is audited too


# ------------------------------------------------------------------ no bypass ---
def test_there_is_no_gated_dispatch_without_an_approval():
    # Exhaustive: for NEEDS_APPROVAL, may_dispatch is True ONLY when the approval is APPROVED.
    held = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=None)
    awaiting = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("AWAITING_APPROVAL", None))
    rejected = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("REJECTED", "r@gov"))
    approved = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("APPROVED", "r@gov"))
    assert [held.may_dispatch, awaiting.may_dispatch, rejected.may_dispatch] == [False, False, False]
    assert approved.may_dispatch is True


def test_returns_an_approval_gate_result_shape():
    assert isinstance(approval_gate(DispatchDecision.AUTO_FIRE, approval=None), ApprovalGateResult)
