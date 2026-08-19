"""In-memory report store (G801) — mirrors the 0008/0009 schema guarantees for tests.

FakeReportStore stands in for the Neon-backed `report_artifacts` table + `decision_log` audit until
a live instance exists ([DB-DEP]), the same way FakeRiskStore mirrors risk_assessments. It
enforces, in Python, exactly the guarantees the SQL enforces:

  * the store owns row ids (insert assigns them);
  * at most ONE current (non-superseded) report per (assessment_id, assessment_version) — the 0008
    partial unique index; a duplicate current is rejected;
  * a re-render SUPERSEDES (appends a new row, links the old via superseded_by) and NEVER mutates
    the old outcome/marks/artifact in place (the correct-by-append UPDATE guard);
  * DELETE is blocked (history is permanent, Constitution VI);
  * the audit log is append-only.

Keeping these in the fake means the logic tests (G802/G803) exercise the same invariants the live
DB will enforce, so nothing is faked away.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from agents.report_generation.report_result import ReportResult


class DuplicateReportError(Exception):
    """Raised on a second CURRENT report for the same (assessment_id, assessment_version)."""


class ReportImmutableError(Exception):
    """Raised on any attempt to overwrite a stored report in place (correct-by-append)."""


class ReportDeleteBlocked(Exception):
    """Raised on any delete attempt — report history is permanent (Constitution VI)."""


@dataclass(frozen=True, slots=True)
class StoredReport:
    """A persisted report: the result plus its store-assigned id and supersession link."""

    id: int
    result: ReportResult
    superseded_by: int | None = None


@dataclass(frozen=True, slots=True)
class AuditRow:
    """One append-only audit entry (mirrors the extended decision_log, 0009)."""

    id: int
    bridge_id: str
    cycle_id: str
    decision: str        # REPORT_RENDERED | REPORT_WITHHELD | REPORT_ERROR
    reason: str


class FakeReportStore:
    """In-memory report_artifacts + audit store. Not thread-safe; tests are serial."""

    def __init__(self) -> None:
        self._rows: list[StoredReport] = []
        self._audit: list[AuditRow] = []
        self._next_id = 1
        self._next_audit_id = 1

    # --- report_artifacts (append + supersede) -------------------------------
    def insert(self, result: ReportResult) -> int:
        """Insert a new current report; returns its id. Rejects a duplicate current version."""
        if self._current_row(result.assessment_id, result.assessment_version) is not None:
            raise DuplicateReportError(
                f"a current report already exists for "
                f"(assessment {result.assessment_id}, v{result.assessment_version})"
            )
        rid = self._next_id
        self._rows.append(StoredReport(id=rid, result=result))
        self._next_id += 1
        return rid

    def insert_superseding(self, old_id: int, result: ReportResult) -> int:
        """Append a new report and link the old one to it (a re-render). The old row is retained
        unchanged; only its superseded_by is stamped."""
        new_id = self._next_id
        self._rows.append(StoredReport(id=new_id, result=result))
        self._next_id += 1
        for i, sr in enumerate(self._rows):
            if sr.id == old_id:
                self._rows[i] = replace(sr, superseded_by=new_id)
                break
        return new_id

    def overwrite(self, row_id: int, result: ReportResult) -> None:
        """Always blocked: a stored report is correct-by-append, never edited in place."""
        raise ReportImmutableError(
            "report_artifacts is correct-by-append: mutating a stored report is blocked "
            "(insert_superseding instead)"
        )

    def delete(self, row_id: int) -> None:
        """Always blocked: report history is permanent (Constitution VI)."""
        raise ReportDeleteBlocked("report_artifacts history is permanent: DELETE blocked")

    def get(self, row_id: int) -> StoredReport | None:
        for sr in self._rows:
            if sr.id == row_id:
                return sr
        return None

    def current(self, assessment_id: int, assessment_version: int) -> ReportResult | None:
        """The current (non-superseded) report for an assessment version, or None."""
        row = self._current_row(assessment_id, assessment_version)
        return row.result if row is not None else None

    def _current_row(self, assessment_id: int, assessment_version: int) -> StoredReport | None:
        for sr in self._rows:
            if (sr.result.assessment_id == assessment_id
                    and sr.result.assessment_version == assessment_version
                    and sr.superseded_by is None):
                return sr
        return None

    @property
    def rows(self) -> tuple[StoredReport, ...]:
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
