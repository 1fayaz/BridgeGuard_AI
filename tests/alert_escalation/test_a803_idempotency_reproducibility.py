"""A803 — idempotency + reproducibility (FR-10/FR-11, AC-9/AC-10) [DB-DEP].

Acceptance gate over A801 (store) + A802 (persist), asserting the three persistence guarantees a
safety-critical dispatch history depends on — no new production code:

  * AC-10 idempotency — a redelivered trigger for an already-handled current version produces NO
    duplicate current dispatch (no double-page); the current row stays single, even after several
    redeliveries;
  * AC-9 append-only — a dispatch against a NEWER assessment version appends a new row that
    SUPERSEDES the old (links it), never overwrites;
  * AC-10 reproducibility — a dispatched alert records exactly which assessment version + trace_id
    (+ approver, when gated) it acted on, so it is reconstructable from those identities even after
    the verdict is later superseded.

This is the persistence-layer analogue of the Report G803 gate.
"""
from __future__ import annotations

from agents.alert_escalation.persistence import persist_dispatch
from agents.alert_escalation.store import FakeAlertStore
from agents.alert_escalation.alert_result import AlertResult
from agents.alert_escalation.statuses import (
    AlertOutcome,
    DispatchDecision,
    DeliveryState,
    EscalationState,
    ApprovalState,
)


def _dispatched(
    *,
    assessment_id: int = 1001,
    version: int = 3,
    decision: DispatchDecision = DispatchDecision.AUTO_FIRE,
    approval_state: ApprovalState | None = None,
    approved_by: str | None = None,
    trace_id: str = "trace-xyz",
) -> AlertResult:
    return AlertResult(
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_id=assessment_id,
        assessment_version=version,
        outcome=AlertOutcome.DISPATCHED,
        withheld_reason=None,
        dispatch_decision=decision,
        channel="email",
        recipient="engineer@gov",
        provider_message_id="fake-msg-0",
        delivery_state=DeliveryState.DELIVERED,
        escalation_state=EscalationState.CLOSED,
        close_reason=DeliveryState.DELIVERED,
        approval_state=approval_state,
        approved_by=approved_by,
        trace_id=trace_id,
        attempted_at="2026-07-11T00:00:00Z",
    )


def _current_rows(store):
    return [r for r in store.rows if r.superseded_by is None]


# ------------------------------------------------------------------ AC-10 idempotency ---
def test_redelivered_trigger_leaves_one_current_no_double_page():
    # A redelivered trigger re-handles the SAME version. Exactly one current row remains for that
    # version — the alert is not dispatched twice (no double-page).
    s = FakeAlertStore()
    persist_dispatch(s, _dispatched(version=3))
    persist_dispatch(s, _dispatched(version=3))     # redelivery
    persist_dispatch(s, _dispatched(version=3))     # redelivery again
    assert len(_current_rows(s)) == 1
    assert _current_rows(s)[0].result.assessment_version == 3


def test_history_grows_but_current_stays_one_under_redelivery():
    # History is append-only: superseded rows are retained (Constitution VI), current stays single.
    s = FakeAlertStore()
    persist_dispatch(s, _dispatched(version=3))
    persist_dispatch(s, _dispatched(version=3))
    assert len(s.rows) == 2                 # both retained
    assert len(_current_rows(s)) == 1       # one current


# ------------------------------------------------------------------ AC-9 append + supersede ---
def test_newer_version_supersedes_without_overwriting():
    s = FakeAlertStore()
    persist_dispatch(s, _dispatched(version=3))
    persist_dispatch(s, _dispatched(version=4))
    # both versions' current dispatches coexist (different keys), nothing overwritten
    versions = {r.result.assessment_version for r in _current_rows(s)}
    assert versions == {3, 4}


def test_supersede_within_a_version_retains_the_old_row_unchanged():
    s = FakeAlertStore()
    first = persist_dispatch(s, _dispatched(version=3, decision=DispatchDecision.AUTO_FIRE))
    persist_dispatch(s, _dispatched(version=3, decision=DispatchDecision.NEEDS_APPROVAL,
                                    approval_state=ApprovalState.APPROVED, approved_by="lead@gov"))
    old = s.get(first)
    assert old.superseded_by is not None                 # linked to its replacement
    assert old.result.dispatch_decision is DispatchDecision.AUTO_FIRE  # old row retained, unmutated


# ------------------------------------------------------------------ AC-10 reproducibility ---
def test_dispatched_alert_pins_version_and_trace_id():
    s = FakeAlertStore()
    rid = persist_dispatch(s, _dispatched(assessment_id=1001, version=3, trace_id="trace-xyz"))
    row = s.get(rid).result
    # exactly the identities needed to reconstruct what was acted on
    assert row.assessment_id == 1001
    assert row.assessment_version == 3
    assert row.trace_id == "trace-xyz"


def test_gated_dispatch_pins_the_approver_for_reproducibility():
    s = FakeAlertStore()
    rid = persist_dispatch(s, _dispatched(
        decision=DispatchDecision.NEEDS_APPROVAL,
        approval_state=ApprovalState.APPROVED,
        approved_by="eng-lead@gov",
    ))
    row = s.get(rid).result
    assert row.approval_state is ApprovalState.APPROVED
    assert row.approved_by == "eng-lead@gov"


def test_old_version_dispatch_remains_reproducible_after_supersession():
    # After v3 is re-handled (superseded), the v3 row and its pinned identities are still there.
    s = FakeAlertStore()
    first = persist_dispatch(s, _dispatched(version=3, trace_id="trace-v3"))
    persist_dispatch(s, _dispatched(version=3, trace_id="trace-v3-again"))
    old = s.get(first).result
    assert old.assessment_version == 3
    assert old.trace_id == "trace-v3"                    # its provenance is intact for an audit


def test_audit_trail_records_each_dispatch_event():
    # Constitution VI: the audit answers what happened, per event, even across supersessions.
    s = FakeAlertStore()
    persist_dispatch(s, _dispatched(version=3))
    persist_dispatch(s, _dispatched(version=3))
    persist_dispatch(s, _dispatched(version=4))
    assert [a.decision for a in s.audit_rows] == [
        "ALERT_DISPATCHED", "ALERT_DISPATCHED", "ALERT_DISPATCHED",
    ]
    assert len(s.audit_rows) == 3                         # one per event, none lost
