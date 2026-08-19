"""G202 — output payload shapes (typed ReportResult + ReportSummary).

`ReportResult` is the one record the report service emits per run; `ReportSummary` is the plain
dict it hands back to n8n (fire-and-notify). Like the Risk `RiskAssessment`, the coherent shapes
are enforced at construction so an invalid output cannot exist as an object.

Acceptance (tasks.md G202): constructs typed; a RENDERED result carries an artifact_ref + its
marks + pinned provenance; a WITHHELD result carries no artifact_ref and exactly one reason;
`__post_init__` enforces coherence (RENDERED⇒artifact_ref present & no reason; WITHHELD⇒reason
present & artifact_ref None; ERROR⇒neither artifact_ref nor reason). Matches the spec output
contract.
"""
from __future__ import annotations

import pytest

from agents.report_generation.report_result import ReportResult, ReportSummary
from agents.report_generation.report_statuses import (
    DocumentMark,
    ReportOutcome,
    WithheldReason,
)


def _rendered(**over):
    base = dict(
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_id=1001,
        assessment_version=3,
        outcome=ReportOutcome.RENDERED,
        marks=(),
        withheld_reason=None,
        artifact_ref="artifact://reports/bridge-7/1001-v3.pdf",
        source_analysis_ids=(11, 12),
        standard_code="AASHTO",
        standard_version="2020",
        template_version="2026-06-gov-template-rev2",
        rendered_at="RENDERED_AT_SEAM",
    )
    base.update(over)
    return ReportResult(**base)


# ------------------------------------------------------------------ RENDERED ---
def test_rendered_result_constructs_with_artifact_and_provenance():
    r = _rendered()
    assert r.outcome is ReportOutcome.RENDERED
    assert r.artifact_ref
    assert r.source_analysis_ids == (11, 12)
    assert r.template_version == "2026-06-gov-template-rev2"
    assert r.assessment_version == 3


def test_rendered_may_carry_marks():
    r = _rendered(marks=(DocumentMark.HISTORICAL, DocumentMark.NOT_FINAL))
    assert DocumentMark.HISTORICAL in r.marks and DocumentMark.NOT_FINAL in r.marks


def test_rendered_empty_marks_is_a_clean_final():
    r = _rendered(marks=())
    assert r.marks == ()


def test_rendered_without_artifact_ref_is_rejected():
    with pytest.raises(ValueError):
        _rendered(artifact_ref=None)


def test_rendered_with_a_withheld_reason_is_rejected():
    # A produced document cannot also claim a no-document reason.
    with pytest.raises(ValueError):
        _rendered(withheld_reason=WithheldReason.PROVENANCE_MISMATCH)


# ------------------------------------------------------------------ WITHHELD ---
def test_withheld_result_constructs_with_reason_and_no_artifact():
    r = _rendered(
        outcome=ReportOutcome.WITHHELD,
        withheld_reason=WithheldReason.PROVENANCE_MISMATCH,
        artifact_ref=None,
        marks=(),
    )
    assert r.outcome is ReportOutcome.WITHHELD
    assert r.withheld_reason is WithheldReason.PROVENANCE_MISMATCH
    assert r.artifact_ref is None


def test_withheld_without_a_reason_is_rejected():
    with pytest.raises(ValueError):
        _rendered(outcome=ReportOutcome.WITHHELD, withheld_reason=None, artifact_ref=None)


def test_withheld_with_an_artifact_ref_is_rejected():
    with pytest.raises(ValueError):
        _rendered(
            outcome=ReportOutcome.WITHHELD,
            withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
            artifact_ref="artifact://should-not-exist.pdf",
        )


def test_withheld_with_marks_is_rejected():
    # No document ⇒ no document marks.
    with pytest.raises(ValueError):
        _rendered(
            outcome=ReportOutcome.WITHHELD,
            withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
            artifact_ref=None,
            marks=(DocumentMark.NOT_FINAL,),
        )


# ------------------------------------------------------------------ ERROR ---
def test_error_result_carries_neither_artifact_nor_reason():
    r = _rendered(
        outcome=ReportOutcome.ERROR,
        withheld_reason=None,
        artifact_ref=None,
        marks=(),
    )
    assert r.outcome is ReportOutcome.ERROR
    assert r.artifact_ref is None
    assert r.withheld_reason is None


def test_error_with_an_artifact_ref_is_rejected():
    with pytest.raises(ValueError):
        _rendered(outcome=ReportOutcome.ERROR, artifact_ref="artifact://nope.pdf", withheld_reason=None)


# ------------------------------------------------------------------ ReportSummary ---
def test_summary_from_rendered_is_ok_true():
    s = ReportSummary.from_result(_rendered(marks=(DocumentMark.NOT_FINAL,)))
    assert s.ok is True
    assert s.outcome == ReportOutcome.RENDERED
    assert DocumentMark.NOT_FINAL.value in [m.value for m in s.marks]
    assert s.withheld_reason is None
    assert s.error is None


def test_summary_from_withheld_is_ok_false_with_reason():
    r = _rendered(
        outcome=ReportOutcome.WITHHELD,
        withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
        artifact_ref=None,
        marks=(),
    )
    s = ReportSummary.from_result(r)
    assert s.ok is False
    assert s.outcome == ReportOutcome.WITHHELD
    assert s.withheld_reason is WithheldReason.ASSESSMENT_NOT_FOUND


def test_summary_is_a_plain_serialisable_shape():
    # n8n branches on `ok`; the summary must expose plain fields (no artifact bytes).
    s = ReportSummary.from_result(_rendered())
    d = s.as_dict()
    assert d["ok"] is True
    assert d["outcome"] == "RENDERED"
    assert "artifact_ref" in d  # the ref (a string), not the bytes
