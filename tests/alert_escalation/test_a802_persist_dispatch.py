"""A802 — persist_dispatch(store, result): one alert_dispatches row + matching audit [DB-DEP].

Writes one row (dispatched, escalated, withheld, or error) to the store and appends the matching
decision_log entry, pinning every provenance field (assessment id+version, trace_id, and — when the
tier was gated — the approver). Idempotent by assessment version: re-persisting the same
(assessment_id, assessment_version) SUPERSEDES the prior row rather than crashing on the uniqueness
constraint (FR-10). Mirrors the Report persist_report.

Audit-kind selection (0011 decision_kind extension), split on escalation state so the audit trail
distinguishes a resolved dispatch from one still climbing the escalation ladder:
  DISPATCHED + escalation ESCALATED -> ALERT_ESCALATED
  DISPATCHED (OPEN / CLOSED)        -> ALERT_DISPATCHED
  WITHHELD                          -> ALERT_WITHHELD
  ERROR                             -> ALERT_ERROR

Acceptance (tasks.md A802): a dispatched, an escalated, a withheld (CONSISTENCY_MISMATCH), and an
error each produce exactly the expected row + audit kind; every row links its pinned provenance
(version + trace_id + approver when gated); a re-persist for the same version supersedes. = FR-13,
AC-9/AC-12.
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
    WithheldReason,
)


def _dispatched(
    *,
    assessment_id: int = 7,
    version: int = 1,
    escalation: EscalationState = EscalationState.CLOSED,
    approval_state: ApprovalState | None = None,
    approved_by: str | None = None,
    decision: DispatchDecision = DispatchDecision.AUTO_FIRE,
) -> AlertResult:
    return AlertResult(
        bridge_id="bridge-12",
        cycle_id="cycle-3",
        assessment_id=assessment_id,
        assessment_version=version,
        outcome=AlertOutcome.DISPATCHED,
        withheld_reason=None,
        dispatch_decision=decision,
        channel="email",
        recipient="engineer@gov",
        provider_message_id="fake-msg-0",
        delivery_state=DeliveryState.DELIVERED,
        escalation_state=escalation,
        close_reason=DeliveryState.DELIVERED if escalation is EscalationState.CLOSED else None,
        approval_state=approval_state,
        approved_by=approved_by,
        trace_id="trace-abc",
        attempted_at="2026-07-11T00:00:00Z",
    )


def _withheld(reason: WithheldReason = WithheldReason.CONSISTENCY_MISMATCH) -> AlertResult:
    return AlertResult(
        bridge_id="bridge-12",
        cycle_id="cycle-3",
        assessment_id=7,
        assessment_version=1,
        outcome=AlertOutcome.WITHHELD,
        withheld_reason=reason,
        dispatch_decision=None,
        channel=None,
        recipient=None,
        provider_message_id=None,
        delivery_state=None,
        escalation_state=None,
        close_reason=None,
        approval_state=None,
        approved_by=None,
        trace_id="trace-abc",
        attempted_at="2026-07-11T00:00:00Z",
    )


def _error() -> AlertResult:
    return AlertResult(
        bridge_id="bridge-12",
        cycle_id="cycle-3",
        assessment_id=7,
        assessment_version=1,
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
        trace_id="trace-abc",
        attempted_at="2026-07-11T00:00:00Z",
    )


# ------------------------------------------------------------------ row + audit per outcome ---
def test_dispatched_writes_row_and_alert_dispatched_audit():
    store = FakeAlertStore()
    rid = persist_dispatch(store, _dispatched())
    assert store.get(rid).result.outcome is AlertOutcome.DISPATCHED
    assert store.audit_rows[-1].decision == "ALERT_DISPATCHED"


def test_escalated_dispatch_writes_alert_escalated_audit():
    # A dispatch still climbing the ladder is audited as ALERT_ESCALATED, not ALERT_DISPATCHED.
    store = FakeAlertStore()
    persist_dispatch(store, _dispatched(escalation=EscalationState.ESCALATED))
    assert store.audit_rows[-1].decision == "ALERT_ESCALATED"


def test_withheld_writes_alert_withheld_audit_with_reason():
    store = FakeAlertStore()
    persist_dispatch(store, _withheld())
    assert store.audit_rows[-1].decision == "ALERT_WITHHELD"
    assert "CONSISTENCY_MISMATCH" in store.audit_rows[-1].reason


def test_error_writes_alert_error_audit():
    store = FakeAlertStore()
    persist_dispatch(store, _error())
    assert store.audit_rows[-1].decision == "ALERT_ERROR"


# ------------------------------------------------------------------ provenance pinned ---
def test_row_pins_assessment_version_and_trace_id():
    store = FakeAlertStore()
    rid = persist_dispatch(store, _dispatched(assessment_id=7, version=3))
    row = store.get(rid).result
    assert (row.assessment_id, row.assessment_version) == (7, 3)
    assert row.trace_id == "trace-abc"


def test_gated_dispatch_pins_the_approver():
    store = FakeAlertStore()
    rid = persist_dispatch(
        store,
        _dispatched(
            decision=DispatchDecision.NEEDS_APPROVAL,
            approval_state=ApprovalState.APPROVED,
            approved_by="eng-lead@gov",
        ),
    )
    row = store.get(rid).result
    assert row.approval_state is ApprovalState.APPROVED
    assert row.approved_by == "eng-lead@gov"


def test_audit_reason_records_version():
    store = FakeAlertStore()
    persist_dispatch(store, _dispatched(assessment_id=7, version=5))
    assert "v5" in store.audit_rows[-1].reason


# ------------------------------------------------------------------ idempotency by version ---
def test_first_persist_is_a_fresh_insert():
    store = FakeAlertStore()
    persist_dispatch(store, _dispatched(assessment_id=7, version=1))
    assert len(store.rows) == 1
    assert store.rows[0].superseded_by is None


def test_re_persist_same_version_supersedes_not_duplicates():
    # A redelivered trigger for the same verdict version supersedes; it never crashes on the
    # uniqueness constraint nor leaves two current rows (FR-10 idempotency).
    store = FakeAlertStore()
    persist_dispatch(store, _dispatched(assessment_id=7, version=1))
    persist_dispatch(store, _dispatched(assessment_id=7, version=1))
    assert len(store.rows) == 2                          # append, not overwrite
    current = [r for r in store.rows if r.superseded_by is None]
    assert len(current) == 1                             # exactly one current row
    assert store.rows[0].superseded_by == store.rows[1].id


def test_new_version_is_a_separate_current_row():
    store = FakeAlertStore()
    persist_dispatch(store, _dispatched(assessment_id=7, version=1))
    persist_dispatch(store, _dispatched(assessment_id=7, version=2))
    # v1 and v2 are distinct assessment versions -> two independent current rows.
    assert store.current(7, 1) is not None
    assert store.current(7, 2) is not None


def test_persist_returns_the_new_row_id():
    store = FakeAlertStore()
    rid = persist_dispatch(store, _dispatched())
    assert store.get(rid) is not None
