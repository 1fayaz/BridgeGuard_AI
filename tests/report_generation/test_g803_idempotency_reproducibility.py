"""G803 — idempotency + reproducibility (FR-9/FR-10/FR-11, AC-9/AC-10/AC-11) [DB-DEP].

Acceptance gate over G801 (store) + G802 (persist), asserting the three persistence guarantees a
government artifact depends on:
  * AC-10 idempotency — a redelivered trigger for an already-rendered current version produces NO
    duplicate artifact (no-op supersede-to-self is avoided; the current row stays single);
  * AC-9 append-only — a render against a NEWER assessment version appends a new row that
    SUPERSEDES the old (links it), never overwrites;
  * AC-11 reproducibility — a rendered report records exactly which assessment version + source
    analysis ids + standard version + template version it used, so it is reconstructable from
    those identities even after an input is later superseded.

No new production code.
"""
from __future__ import annotations

from agents.report_generation.persistence import persist_report
from agents.report_generation.store import FakeReportStore
from agents.report_generation.report_result import ReportResult
from agents.report_generation.report_statuses import DocumentMark, ReportOutcome


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


def _current_rows(store):
    return [r for r in store.rows if r.superseded_by is None]


# ------------------------------------------------------------------ AC-10 idempotency ---
def test_redelivered_identical_render_supersedes_leaving_one_current():
    # A redelivered trigger re-renders the SAME version. The result is still exactly one current
    # row for that version — no proliferation of duplicates.
    s = FakeReportStore()
    persist_report(s, _result(assessment_version=3))
    persist_report(s, _result(assessment_version=3))     # redelivery
    persist_report(s, _result(assessment_version=3))     # redelivery again
    assert len(_current_rows(s)) == 1
    assert _current_rows(s)[0].result.assessment_version == 3


def test_total_rows_grow_but_current_stays_one_under_redelivery():
    # History is append-only: superseded rows are retained (Constitution VI), current stays single.
    s = FakeReportStore()
    persist_report(s, _result(assessment_version=3))
    persist_report(s, _result(assessment_version=3))
    assert len(s.rows) == 2                 # both retained
    assert len(_current_rows(s)) == 1       # one current


# ------------------------------------------------------------------ AC-9 append + supersede ---
def test_newer_version_supersedes_without_overwriting():
    s = FakeReportStore()
    persist_report(s, _result(assessment_version=3))
    persist_report(s, _result(assessment_version=4, marks=(DocumentMark.HISTORICAL,)))
    # both versions' current reports coexist (different keys), nothing overwritten
    versions = {r.result.assessment_version for r in _current_rows(s)}
    assert versions == {3, 4}


def test_supersede_within_a_version_retains_the_old_row_unchanged():
    s = FakeReportStore()
    first = persist_report(s, _result(assessment_version=3, marks=()))
    persist_report(s, _result(assessment_version=3, marks=(DocumentMark.HISTORICAL,)))
    old = s.get(first)
    assert old.superseded_by is not None           # linked to its replacement
    assert old.result.marks == ()                  # old artifact retained, unmutated


# ------------------------------------------------------------------ AC-11 reproducibility ---
def test_rendered_report_pins_every_reproducibility_identity():
    s = FakeReportStore()
    rid = persist_report(s, _result(
        assessment_id=1001, assessment_version=3,
        source_analysis_ids=(11, 12), standard_version="2020", template_version="rev2",
    ))
    row = s.get(rid).result
    # exactly the identities needed to reconstruct the document later
    assert row.assessment_id == 1001
    assert row.assessment_version == 3
    assert row.source_analysis_ids == (11, 12)
    assert row.standard_version == "2020"
    assert row.template_version == "rev2"


def test_old_version_report_remains_reproducible_after_supersession():
    # After v3 is superseded by a re-render, the v3 row (and its pinned identities) is still there.
    s = FakeReportStore()
    first = persist_report(s, _result(assessment_version=3, source_analysis_ids=(11,)))
    persist_report(s, _result(assessment_version=3, source_analysis_ids=(11,),
                              marks=(DocumentMark.HISTORICAL,)))
    old = s.get(first).result
    assert old.assessment_version == 3
    assert old.source_analysis_ids == (11,)        # its provenance is intact for a re-print


def test_audit_trail_records_each_render_event():
    # Constitution VI: the audit answers what happened, per event, even across supersessions.
    s = FakeReportStore()
    persist_report(s, _result(assessment_version=3))
    persist_report(s, _result(assessment_version=3, marks=(DocumentMark.HISTORICAL,)))
    persist_report(s, _result(assessment_version=4))
    assert [a.decision for a in s.audit_rows] == [
        "REPORT_RENDERED", "REPORT_RENDERED", "REPORT_RENDERED",
    ]
    assert len(s.audit_rows) == 3                   # one per render, none lost
