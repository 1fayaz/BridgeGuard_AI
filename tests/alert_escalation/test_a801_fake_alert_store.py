"""A801 — FakeAlertStore mirrors the A203/A204 schema guarantees in memory [DB-DEP].

Stands in for the Neon `alert_dispatches` table (0010) + the `decision_log` audit (0011) until a
live instance exists, exactly as FakeReportStore mirrors report_artifacts. It enforces, in Python,
the same guarantees the SQL enforces so the logic tests exercise real invariants, not faked ones:

  * the store owns row ids (insert assigns them);
  * at most ONE current (non-superseded) dispatch per (assessment_id, assessment_version) — the
    0010 partial unique index; a duplicate current is rejected;
  * a re-dispatch SUPERSEDES (appends a new row, links the old via superseded_by) and NEVER mutates
    a stored row in place;
  * DELETE is blocked (a dispatch history a regulator relies on is permanent, Constitution VI);
  * the audit log is append-only.

Acceptance (tasks.md A801): insert assigns id; supersede links old->new and never deletes; delete
blocked; a duplicate (assessment_id, assessment_version) among current rows is rejected;
append_audit records a kind. = A203 guarantees in-memory.
"""
from __future__ import annotations

import pytest

from agents.alert_escalation.store import (
    FakeAlertStore,
    StoredDispatch,
    AlertAuditRow,
    DuplicateDispatchError,
    DispatchImmutableError,
    DispatchDeleteBlocked,
)
from agents.alert_escalation.alert_result import AlertResult
from agents.alert_escalation.statuses import (
    AlertOutcome,
    DispatchDecision,
    DeliveryState,
    EscalationState,
    ApprovalState,
)


def _dispatched(assessment_id: int = 7, version: int = 1) -> AlertResult:
    return AlertResult(
        bridge_id="bridge-12",
        cycle_id="cycle-3",
        assessment_id=assessment_id,
        assessment_version=version,
        outcome=AlertOutcome.DISPATCHED,
        withheld_reason=None,
        dispatch_decision=DispatchDecision.AUTO_FIRE,
        channel="email",
        recipient="engineer@gov",
        provider_message_id="fake-msg-0",
        delivery_state=DeliveryState.DELIVERED,
        escalation_state=EscalationState.CLOSED,
        close_reason=DeliveryState.DELIVERED,
        approval_state=None,
        approved_by=None,
        trace_id="trace-abc",
        attempted_at="2026-07-11T00:00:00Z",
    )


def test_insert_assigns_id():
    store = FakeAlertStore()
    rid = store.insert(_dispatched())
    assert rid == 1
    assert store.get(rid).result.assessment_id == 7


def test_insert_returns_incrementing_ids():
    store = FakeAlertStore()
    a = store.insert(_dispatched(assessment_id=1))
    b = store.insert(_dispatched(assessment_id=2))
    assert (a, b) == (1, 2)


def test_current_returns_the_non_superseded_row():
    store = FakeAlertStore()
    store.insert(_dispatched(assessment_id=7, version=1))
    assert store.current(7, 1) is not None
    assert store.current(7, 1).assessment_id == 7
    assert store.current(99, 1) is None


def test_duplicate_current_version_is_rejected():
    # The 0010 partial unique index: only one current dispatch per (assessment_id, version).
    store = FakeAlertStore()
    store.insert(_dispatched(assessment_id=7, version=1))
    with pytest.raises(DuplicateDispatchError):
        store.insert(_dispatched(assessment_id=7, version=1))


def test_supersede_links_old_to_new_and_keeps_both():
    store = FakeAlertStore()
    old = store.insert(_dispatched(assessment_id=7, version=1))
    new = store.insert_superseding(old, _dispatched(assessment_id=7, version=2))
    assert store.get(old).superseded_by == new       # old links forward
    assert store.get(new).superseded_by is None       # new is current
    assert len(store.rows) == 2                        # nothing deleted


def test_superseded_row_is_no_longer_current():
    store = FakeAlertStore()
    old = store.insert(_dispatched(assessment_id=7, version=1))
    store.insert_superseding(old, _dispatched(assessment_id=7, version=2))
    # v1 is superseded; querying v1 current returns None, v2 is current.
    assert store.current(7, 1) is None
    assert store.current(7, 2) is not None


def test_overwrite_is_blocked():
    store = FakeAlertStore()
    rid = store.insert(_dispatched())
    with pytest.raises(DispatchImmutableError):
        store.overwrite(rid, _dispatched())


def test_delete_is_blocked():
    # A dispatch history a regulator relies on is permanent (Constitution VI).
    store = FakeAlertStore()
    rid = store.insert(_dispatched())
    with pytest.raises(DispatchDeleteBlocked):
        store.delete(rid)


def test_append_audit_records_a_kind():
    store = FakeAlertStore()
    aid = store.append_audit("bridge-12", "cycle-3", "ALERT_DISPATCHED", "auto-fired WATCH")
    assert aid == 1
    assert store.audit_rows[0].decision == "ALERT_DISPATCHED"
    assert store.audit_rows[0].bridge_id == "bridge-12"


def test_audit_is_append_only_incrementing():
    store = FakeAlertStore()
    store.append_audit("b", "c", "ALERT_DISPATCHED", "r1")
    store.append_audit("b", "c", "ALERT_ESCALATED", "r2")
    assert [a.id for a in store.audit_rows] == [1, 2]
    assert [a.decision for a in store.audit_rows] == ["ALERT_DISPATCHED", "ALERT_ESCALATED"]


def test_stored_rows_and_audit_rows_are_snapshots():
    # Exposed as tuples so a caller cannot mutate store internals.
    store = FakeAlertStore()
    store.insert(_dispatched())
    assert isinstance(store.rows, tuple)
    assert isinstance(store.audit_rows, tuple)
