"""G802 — persist_report(store, result) [DB-DEP].

Writes one report_artifacts row (rendered, withheld, or error) + the matching decision_log audit
row, linking the pinned provenance (assessment id+version, source_analysis_ids, standard code+
version, template_version). If a current row already exists for the same (assessment_id,
assessment_version), the write SUPERSEDES it (append + link) rather than duplicating — idempotent
by assessment version (FR-9/FR-10/FR-11).

Acceptance (tasks.md G802): a rendered, a withheld (PROVENANCE_MISMATCH), and an error each produce
exactly the expected row + audit kind; every row links its pinned provenance; a re-persist for the
same version supersedes (no duplicate).
"""
from __future__ import annotations

from agents.report_generation.persistence import persist_report
from agents.report_generation.store import FakeReportStore
from agents.report_generation.report_result import ReportResult
from agents.report_generation.report_statuses import (
    DocumentMark,
    ReportOutcome,
    WithheldReason,
)


def _result(assessment_id=1001, assessment_version=3, **over):
    base = dict(
        bridge_id="bridge-7", cycle_id="cycle-42",
        assessment_id=assessment_id, assessment_version=assessment_version,
        outcome=ReportOutcome.RENDERED, marks=(), withheld_reason=None,
        artifact_ref=f"artifact://reports/bridge-7/{assessment_id}-v{assessment_version}.pdf",
        source_analysis_ids=(11, 12), standard_code="AASHTO", standard_version="2020",
        template_version="rev2", rendered_at="T",
    )
    base.update(over)
    return ReportResult(**base)


# ------------------------------------------------------------------ rendered ---
def test_rendered_writes_a_row_and_report_rendered_audit():
    s = FakeReportStore()
    rid = persist_report(s, _result())
    assert s.get(rid).result.outcome is ReportOutcome.RENDERED
    assert [a.decision for a in s.audit_rows] == ["REPORT_RENDERED"]


def test_row_links_the_pinned_provenance():
    s = FakeReportStore()
    rid = persist_report(s, _result())
    row = s.get(rid).result
    assert row.assessment_id == 1001
    assert row.assessment_version == 3
    assert row.source_analysis_ids == (11, 12)
    assert row.standard_code == "AASHTO"
    assert row.standard_version == "2020"
    assert row.template_version == "rev2"


def test_rendered_audit_records_the_assessment_version():
    s = FakeReportStore()
    persist_report(s, _result(assessment_version=3))
    assert "v3" in s.audit_rows[0].reason or "3" in s.audit_rows[0].reason


# ------------------------------------------------------------------ withheld ---
def test_withheld_writes_a_row_and_report_withheld_audit():
    s = FakeReportStore()
    rid = persist_report(s, _result(
        outcome=ReportOutcome.WITHHELD,
        withheld_reason=WithheldReason.PROVENANCE_MISMATCH,
        artifact_ref=None, marks=(),
    ))
    assert s.get(rid).result.outcome is ReportOutcome.WITHHELD
    assert [a.decision for a in s.audit_rows] == ["REPORT_WITHHELD"]


def test_withheld_audit_names_the_reason():
    s = FakeReportStore()
    persist_report(s, _result(
        outcome=ReportOutcome.WITHHELD,
        withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
        artifact_ref=None, marks=(),
    ))
    assert "ASSESSMENT_NOT_FOUND" in s.audit_rows[0].reason


# ------------------------------------------------------------------ error ---
def test_error_writes_report_error_audit():
    s = FakeReportStore()
    rid = persist_report(s, _result(
        outcome=ReportOutcome.ERROR, artifact_ref=None, withheld_reason=None, marks=(),
    ))
    assert s.get(rid).result.outcome is ReportOutcome.ERROR
    assert [a.decision for a in s.audit_rows] == ["REPORT_ERROR"]


# ------------------------------------------------------------------ idempotent supersede ---
def test_repersist_same_version_supersedes_no_duplicate():
    s = FakeReportStore()
    first = persist_report(s, _result(assessment_version=3, marks=()))
    second = persist_report(s, _result(assessment_version=3, marks=(DocumentMark.HISTORICAL,)))

    assert first != second
    # exactly one current row for (1001, v3)
    current_rows = [r for r in s.rows if r.superseded_by is None]
    assert len(current_rows) == 1
    assert current_rows[0].id == second
    # the old row is retained, linked, unmutated
    assert s.get(first).superseded_by == second
    assert s.get(first).result.marks == ()


def test_new_assessment_version_is_a_fresh_row_not_a_supersede():
    s = FakeReportStore()
    persist_report(s, _result(assessment_version=3))
    persist_report(s, _result(assessment_version=4))
    current_rows = [r for r in s.rows if r.superseded_by is None]
    assert len(current_rows) == 2   # v3 and v4 are distinct current reports


def test_each_persist_appends_one_audit_row():
    s = FakeReportStore()
    persist_report(s, _result(assessment_version=3))
    persist_report(s, _result(assessment_version=3, marks=(DocumentMark.HISTORICAL,)))
    assert len(s.audit_rows) == 2   # one per persist, even when the second supersedes
