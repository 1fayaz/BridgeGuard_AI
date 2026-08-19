"""In-memory alert store (A801) — mirrors the 0010/0011 schema guarantees for tests [DB-DEP].

FakeAlertStore stands in for the Neon-backed `alert_dispatches` table (0010) + the `decision_log`
audit (0011) until a live instance exists, the same way FakeReportStore mirrors report_artifacts.
It enforces, in Python, exactly the guarantees the SQL enforces:

  * the store owns row ids (insert assigns them);
  * at most ONE current (non-superseded) dispatch per (assessment_id, assessment_version) — the
    0010 partial unique index; a duplicate current is rejected (idempotency, FR-10);
  * a re-dispatch SUPERSEDES (appends a new row, links the old via superseded_by) and NEVER mutates
    a stored row in place (the correct-by-append UPDATE guard);
  * DELETE is blocked (a dispatch history a regulator relies on is permanent, Constitution VI);
  * the audit log is append-only.

Keeping these in the fake means the logic tests (A802/A803) exercise the same invariants the live
DB will enforce, so nothing is faked away.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from agents.alert_escalation.alert_result import AlertResult


class DuplicateDispatchError(Exception):
    """Raised on a second CURRENT dispatch for the same (assessment_id, assessment_version)."""


class DispatchImmutableError(Exception):
    """Raised on any attempt to overwrite a stored dispatch in place (correct-by-append)."""


class DispatchDeleteBlocked(Exception):
    """Raised on any delete attempt — dispatch history is permanent (Constitution VI)."""


@dataclass(frozen=True, slots=True)
class StoredDispatch:
    """A persisted dispatch: the result plus its store-assigned id and supersession link."""

    id: int
    result: AlertResult
    superseded_by: int | None = None


@dataclass(frozen=True, slots=True)
class AlertAuditRow:
    """One append-only audit entry (mirrors the extended decision_log, 0011)."""

    id: int
    bridge_id: str
    cycle_id: str
    decision: str        # ALERT_DISPATCHED | ALERT_ESCALATED | ALERT_WITHHELD | ALERT_ERROR
    reason: str


class FakeAlertStore:
    """In-memory alert_dispatches + audit store. Not thread-safe; tests are serial."""

    def __init__(self) -> None:
        self._rows: list[StoredDispatch] = []
        self._audit: list[AlertAuditRow] = []
        self._next_id = 1
        self._next_audit_id = 1

    # --- alert_dispatches (append + supersede) -------------------------------
    def insert(self, result: AlertResult) -> int:
        """Insert a new current dispatch; returns its id. Rejects a duplicate current version."""
        if self._current_row(result.assessment_id, result.assessment_version) is not None:
            raise DuplicateDispatchError(
                f"a current dispatch already exists for "
                f"(assessment {result.assessment_id}, v{result.assessment_version})"
            )
        rid = self._next_id
        self._rows.append(StoredDispatch(id=rid, result=result))
        self._next_id += 1
        return rid

    def insert_superseding(self, old_id: int, result: AlertResult) -> int:
        """Append a new dispatch and link the old one to it (a re-dispatch). The old row is retained
        unchanged; only its superseded_by is stamped."""
        new_id = self._next_id
        self._rows.append(StoredDispatch(id=new_id, result=result))
        self._next_id += 1
        for i, sr in enumerate(self._rows):
            if sr.id == old_id:
                self._rows[i] = replace(sr, superseded_by=new_id)
                break
        return new_id

    def overwrite(self, row_id: int, result: AlertResult) -> None:
        """Always blocked: a stored dispatch is correct-by-append, never edited in place."""
        raise DispatchImmutableError(
            "alert_dispatches is correct-by-append: mutating a stored dispatch is blocked "
            "(insert_superseding instead)"
        )

    def delete(self, row_id: int) -> None:
        """Always blocked: dispatch history is permanent (Constitution VI)."""
        raise DispatchDeleteBlocked("alert_dispatches history is permanent: DELETE blocked")

    def get(self, row_id: int) -> StoredDispatch | None:
        for sr in self._rows:
            if sr.id == row_id:
                return sr
        return None

    def current(self, assessment_id: int, assessment_version: int) -> AlertResult | None:
        """The current (non-superseded) dispatch for an assessment version, or None."""
        row = self._current_row(assessment_id, assessment_version)
        return row.result if row is not None else None

    def _current_row(self, assessment_id: int, assessment_version: int) -> StoredDispatch | None:
        for sr in self._rows:
            if (sr.result.assessment_id == assessment_id
                    and sr.result.assessment_version == assessment_version
                    and sr.superseded_by is None):
                return sr
        return None

    @property
    def rows(self) -> tuple[StoredDispatch, ...]:
        return tuple(self._rows)

    # --- decision_log (append-only) ------------------------------------------
    def append_audit(self, bridge_id: str, cycle_id: str, decision: str, reason: str) -> int:
        aid = self._next_audit_id
        self._audit.append(AlertAuditRow(aid, bridge_id, cycle_id, decision, reason))
        self._next_audit_id += 1
        return aid

    @property
    def audit_rows(self) -> tuple[AlertAuditRow, ...]:
        return tuple(self._audit)
