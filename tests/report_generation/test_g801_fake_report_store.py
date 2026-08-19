"""G801 — FakeReportStore mirrors the 0008/0009 schema guarantees in memory.

Stands in for the Neon-backed `report_artifacts` table + `decision_log` audit until a live instance
exists ([DB-DEP]), the same way FakeRiskStore mirrors risk_assessments. It enforces, in Python,
exactly what the SQL enforces:
  * the store owns row ids (insert assigns them);
  * at most ONE current (non-superseded) report per (assessment_id, assessment_version) — the 0008
    partial unique index; a duplicate current is rejected;
  * a re-render SUPERSEDES (appends a new row, links the old via superseded_by) and NEVER mutates
    the old outcome/marks/artifact in place (the correct-by-append guard);
  * DELETE is blocked (history is permanent, Constitution VI);
  * the audit log is append-only.

Acceptance (tasks.md G801): insert assigns id; supersede links old->new and never mutates
outcome/marks/artifact; delete blocked; a duplicate (assessment_id, assessment_version) among
current rows is rejected.
"""
from __future__ import annotations

import pytest

from agents.report_generation.store import (
    DuplicateReportError,
    FakeReportStore,
    ReportDeleteBlocked,
    ReportImmutableError,
)
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


# ------------------------------------------------------------------ insert ---
def test_insert_assigns_an_id():
    s = FakeReportStore()
    rid = s.insert(_result())
    assert rid == 1
    assert s.get(rid).result.assessment_id == 1001


def test_two_inserts_get_distinct_ids():
    s = FakeReportStore()
    a = s.insert(_result(assessment_id=1001))
    b = s.insert(_result(assessment_id=2002))
    assert a != b


def test_current_returns_the_non_superseded_row():
    s = FakeReportStore()
    s.insert(_result())
    cur = s.current(1001, 3)
    assert cur is not None
    assert cur.artifact_ref.endswith("1001-v3.pdf")


# ------------------------------------------------------------------ idempotency ---
def test_duplicate_current_version_is_rejected():
    s = FakeReportStore()
    s.insert(_result(assessment_id=1001, assessment_version=3))
    with pytest.raises(DuplicateReportError):
        s.insert(_result(assessment_id=1001, assessment_version=3))


def test_same_assessment_different_version_is_allowed():
    # A newer assessment version is a different key -> its first render is not a duplicate.
    s = FakeReportStore()
    s.insert(_result(assessment_id=1001, assessment_version=3))
    rid = s.insert(_result(assessment_id=1001, assessment_version=4))
    assert rid == 2


# ------------------------------------------------------------------ supersede ---
def test_supersede_links_old_to_new_without_mutating_old():
    s = FakeReportStore()
    old_id = s.insert(_result(assessment_version=3, marks=()))
    new_id = s.insert_superseding(old_id, _result(assessment_version=3, marks=(DocumentMark.HISTORICAL,)))

    old = s.get(old_id)
    new = s.get(new_id)
    assert old.superseded_by == new_id           # linked
    assert old.result.marks == ()                # old outcome/marks untouched
    assert new.result.marks == (DocumentMark.HISTORICAL,)


def test_supersede_frees_the_current_slot():
    # After superseding, the old key is no longer current, so a re-insert of that version is fine.
    s = FakeReportStore()
    old_id = s.insert(_result(assessment_version=3))
    s.insert_superseding(old_id, _result(assessment_version=3))
    # the current row for (1001, 3) is now the new one
    assert s.current(1001, 3).artifact_ref  # present, single current row
    assert sum(1 for r in s.rows if r.superseded_by is None) == 1


# ------------------------------------------------------------------ immutability ---
def test_overwrite_is_blocked():
    s = FakeReportStore()
    rid = s.insert(_result())
    with pytest.raises(ReportImmutableError):
        s.overwrite(rid, _result(marks=(DocumentMark.NOT_FINAL,)))


def test_delete_is_blocked():
    s = FakeReportStore()
    rid = s.insert(_result())
    with pytest.raises(ReportDeleteBlocked):
        s.delete(rid)


# ------------------------------------------------------------------ withheld rows ---
def test_a_withheld_result_can_be_stored():
    s = FakeReportStore()
    rid = s.insert(_result(
        outcome=ReportOutcome.WITHHELD,
        withheld_reason=WithheldReason.PROVENANCE_MISMATCH,
        artifact_ref=None, marks=(),
    ))
    assert s.get(rid).result.outcome is ReportOutcome.WITHHELD


# ------------------------------------------------------------------ audit ---
def test_audit_is_append_only_and_assigns_ids():
    s = FakeReportStore()
    a = s.append_audit(1001, 3, "REPORT_RENDERED", "rendered clean FINAL")
    b = s.append_audit(1001, 3, "REPORT_WITHHELD", "provenance mismatch")
    assert (a, b) == (1, 2)
    kinds = [row.decision for row in s.audit_rows]
    assert kinds == ["REPORT_RENDERED", "REPORT_WITHHELD"]
