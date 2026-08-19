"""Alert persistence (A802) — one alert_dispatches row + matching audit (FR-13) [DB-DEP].

`persist_dispatch` writes one alert (dispatched, escalated, withheld, or error) to the store and
appends the matching decision_log entry, so the structured record alone answers what was dispatched
/ withheld, from which verdict version, to whom, and — when gated — who approved it (AC-9/AC-12). It
pins every provenance field (assessment id+version, trace_id, approver) and is idempotent by
assessment version: re-persisting the same (assessment_id, assessment_version) SUPERSEDES the prior
row rather than crashing on the uniqueness constraint (a redelivered trigger appends + links, never
overwrites — FR-10).

Audit-kind selection mirrors the 0011 decision_kind extension, split on escalation state so the
audit trail distinguishes a resolved dispatch from one still climbing the ladder:
  DISPATCHED + ESCALATED -> ALERT_ESCALATED
  DISPATCHED (OPEN/CLOSED) -> ALERT_DISPATCHED
  WITHHELD -> ALERT_WITHHELD
  ERROR    -> ALERT_ERROR

[DB-DEP] Runs against FakeAlertStore now; the live Neon write is deferred (no instance locally).
"""
from __future__ import annotations

from agents.alert_escalation.alert_result import AlertResult
from agents.alert_escalation.statuses import AlertOutcome, EscalationState
from agents.alert_escalation.store import FakeAlertStore


def _audit_kind(result: AlertResult) -> str:
    if result.outcome is AlertOutcome.DISPATCHED:
        if result.escalation_state is EscalationState.ESCALATED:
            return "ALERT_ESCALATED"
        return "ALERT_DISPATCHED"
    if result.outcome is AlertOutcome.WITHHELD:
        return "ALERT_WITHHELD"
    return "ALERT_ERROR"


def _audit_reason(result: AlertResult) -> str:
    """A short, structured reason line for the audit row — records the pinned version + outcome."""
    base = f"assessment {result.assessment_id} v{result.assessment_version}"
    if result.outcome is AlertOutcome.DISPATCHED:
        decision = result.dispatch_decision.value if result.dispatch_decision else "?"
        approver = f" by {result.approved_by}" if result.approved_by else ""
        esc = result.escalation_state.value if result.escalation_state else "?"
        return f"dispatched {base} [{decision}/{esc}]{approver}"
    if result.outcome is AlertOutcome.WITHHELD:
        reason = result.withheld_reason.value if result.withheld_reason else "WITHHELD"
        return f"withheld {base}: {reason}"
    return f"error {base}"


def persist_dispatch(store: FakeAlertStore, result: AlertResult) -> int:
    """Persist one alert + its audit entry (FR-13). Returns the new row id.

    If a current dispatch already exists for this (assessment_id, assessment_version), the new one
    supersedes it (append + link); otherwise it is a fresh insert. Idempotent by assessment version
    — a redelivered trigger or a re-dispatch never duplicates or crashes (FR-10).
    """
    existing = store.current(result.assessment_id, result.assessment_version)
    if existing is not None:
        old_id = next(
            sr.id for sr in store.rows
            if sr.result is existing and sr.superseded_by is None
        )
        row_id = store.insert_superseding(old_id, result)
    else:
        row_id = store.insert(result)

    store.append_audit(
        result.bridge_id,
        result.cycle_id,
        _audit_kind(result),
        _audit_reason(result),
    )
    return row_id
