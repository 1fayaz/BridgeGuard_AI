"""In-memory risk store (R901) — mirrors the R203/R204 schema guarantees for tests.

FakeRiskStore stands in for the Supabase-backed `risk_assessments` table + `decision_log` audit
until a live instance exists ([DB-DEP]), the same way the DCA/SA fakes mirror their tables. It
enforces, in Python, exactly the guarantees the SQL enforces in the database:

  * the store owns row ids (INSERT assigns them);
  * at most ONE current (non-superseded) assessment per (bridge_id, cycle_id) — the R203 partial
    unique index; a duplicate is rejected;
  * a re-assessment SUPERSEDES (appends a new row, links the old via superseded_by) and NEVER
    mutates the old verdict's score/severity/explanation (the correct-by-append UPDATE guard);
  * DELETE is blocked (history is permanent, Constitution VI);
  * the audit log is append-only.

Keeping these in the fake means the logic tests (R902/R903) exercise the same invariants the live
DB will enforce, so nothing is faked away.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from agents.risk_reasoning.assessment import RiskAssessment


class DuplicateAssessmentError(Exception):
    """Raised on a second CURRENT assessment for the same (bridge_id, cycle_id) — R203 uniqueness."""


class AssessmentImmutableError(Exception):
    """Raised on any attempt to overwrite a stored verdict in place (correct-by-append)."""


class AssessmentDeleteBlocked(Exception):
    """Raised on any delete attempt — assessment history is permanent (Constitution VI)."""


@dataclass(frozen=True, slots=True)
class StoredAssessment:
    """A persisted assessment: the verdict plus its store-assigned id and supersession link."""

    id: int
    assessment: RiskAssessment
    superseded_by: int | None = None


@dataclass(frozen=True, slots=True)
class AuditRow:
    """One append-only audit entry (mirrors the extended decision_log, R204)."""

    id: int
    bridge_id: str
    cycle_id: str
    decision: str        # RISK_ASSESSMENT | RISK_WITHHELD | RISK_GUARDRAIL_FAIL
    reason: str


class FakeRiskStore:
    """In-memory risk_assessments + audit store. Not thread-safe; tests are serial."""

    def __init__(self) -> None:
        self._rows: list[StoredAssessment] = []
        self._audit: list[AuditRow] = []
        self._next_id = 1
        self._next_audit_id = 1

    # --- risk_assessments (append + supersede) -------------------------------
    def insert(self, assessment: RiskAssessment) -> int:
        """Insert a new current assessment; returns its id. Rejects a duplicate current scope."""
        if self._current_row(assessment.bridge_id, assessment.cycle_id) is not None:
            raise DuplicateAssessmentError(
                f"a current assessment already exists for "
                f"({assessment.bridge_id!r}, {assessment.cycle_id!r})"
            )
        rid = self._next_id
        self._rows.append(StoredAssessment(id=rid, assessment=assessment))
        self._next_id += 1
        return rid

    def insert_superseding(self, old_id: int, assessment: RiskAssessment) -> int:
        """Append a new assessment and link the old one to it (a re-assessment). The old verdict
        is retained unchanged; only its superseded_by is stamped."""
        new_id = self._next_id
        self._rows.append(StoredAssessment(id=new_id, assessment=assessment))
        self._next_id += 1
        for i, sa in enumerate(self._rows):
            if sa.id == old_id:
                self._rows[i] = replace(sa, superseded_by=new_id)
                break
        return new_id

    def overwrite(self, row_id: int, assessment: RiskAssessment) -> None:
        """Always blocked: a stored verdict is correct-by-append, never edited in place."""
        raise AssessmentImmutableError(
            "risk_assessments is correct-by-append: mutating a stored verdict is blocked "
            "(insert_superseding instead)"
        )

    def delete(self, row_id: int) -> None:
        """Always blocked: assessment history is permanent (Constitution VI)."""
        raise AssessmentDeleteBlocked("risk_assessments history is permanent: DELETE blocked")

    def get(self, row_id: int) -> StoredAssessment | None:
        for sa in self._rows:
            if sa.id == row_id:
                return sa
        return None

    def current(self, bridge_id: str, cycle_id: str) -> RiskAssessment | None:
        """The current (non-superseded) assessment for a scope, or None."""
        row = self._current_row(bridge_id, cycle_id)
        return row.assessment if row is not None else None

    def _current_row(self, bridge_id: str, cycle_id: str) -> StoredAssessment | None:
        for sa in self._rows:
            if (sa.assessment.bridge_id == bridge_id
                    and sa.assessment.cycle_id == cycle_id
                    and sa.superseded_by is None):
                return sa
        return None

    @property
    def rows(self) -> tuple[StoredAssessment, ...]:
        return tuple(self._rows)

    # --- decision_log (append-only) ------------------------------------------
    def append_audit(self, bridge_id: str, cycle_id: str, decision: str, reason: str) -> int:
        aid = self._next_audit_id
        self._audit.append(AuditRow(aid, bridge_id, cycle_id, decision, reason))
        self._next_audit_id += 1
        return aid

    @property
    def audit_rows(self) -> tuple[AuditRow, ...]:
        return tuple(self._audit)
