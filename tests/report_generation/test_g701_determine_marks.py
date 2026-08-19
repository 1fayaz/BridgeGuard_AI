"""G701 — determine_marks(assessment, sections, *, historical) (pure, FR-4/6/7/8).

Computes the sign-off marks a RENDERED document carries:
  * NOT_FINAL           when review_status == PENDING_HUMAN_REVIEW OR severity == CRITICAL (FR-7)
  * SCORE_WITHHELD      when the assessment withheld its score (risk_score is None) — and then
                        NOT_FINAL too (a withheld score is never final) (FR-8)
  * HISTORICAL          when a superseded row was rendered (historical re-print) (FR-4/AC-4a)
  * SECTION_UNAVAILABLE when any rendered section is available=False (FR-6)

Pure; an empty mark set means a clean FINAL report. Marks compose.

Acceptance (tasks.md G701): a FINAL scored assessment -> no marks; CRITICAL/PENDING -> NOT_FINAL;
withheld -> SCORE_WITHHELD + NOT_FINAL; historical render -> HISTORICAL; missing section ->
SECTION_UNAVAILABLE; marks compose.
"""
from __future__ import annotations

from agents.report_generation.marks import determine_marks
from agents.report_generation.report_statuses import DocumentMark
from agents.report_generation.model import ReportSection, Slot


def _assessment(**over):
    base = dict(
        id=1001, risk_score=48, severity="WARNING", review_status="FINAL", superseded_by=None,
    )
    base.update(over)
    return base


def _sections(all_available=True):
    exec_summary = ReportSection(name="exec_summary", available=True, slots=(
        Slot(48, "risk_assessments:1001:risk_score"),
    ))
    if all_available:
        math = ReportSection(name="math_results", available=True, slots=(
            Slot({"ratio": 0.62}, "analysis_results:11:result"),
        ))
    else:
        math = ReportSection(name="math_results", available=False, slots=())
    return (exec_summary, math)


# ------------------------------------------------------------------ clean FINAL ---
def test_final_scored_assessment_has_no_marks():
    marks = determine_marks(_assessment(), _sections(), historical=False)
    assert marks == ()


# ------------------------------------------------------------------ NOT_FINAL ---
def test_pending_human_review_is_not_final():
    marks = determine_marks(
        _assessment(review_status="PENDING_HUMAN_REVIEW"), _sections(), historical=False)
    assert DocumentMark.NOT_FINAL in marks


def test_critical_severity_is_not_final():
    marks = determine_marks(
        _assessment(severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW"),
        _sections(), historical=False)
    assert DocumentMark.NOT_FINAL in marks


# ------------------------------------------------------------------ SCORE_WITHHELD ---
def test_withheld_score_is_score_withheld_and_not_final():
    # A withheld assessment: risk_score None, severity None, held pending review.
    marks = determine_marks(
        _assessment(risk_score=None, severity=None, review_status="PENDING_HUMAN_REVIEW"),
        _sections(), historical=False)
    assert DocumentMark.SCORE_WITHHELD in marks
    assert DocumentMark.NOT_FINAL in marks       # a withheld score is never final


# ------------------------------------------------------------------ HISTORICAL ---
def test_historical_render_is_marked_historical():
    marks = determine_marks(_assessment(superseded_by=2002), _sections(), historical=True)
    assert DocumentMark.HISTORICAL in marks


def test_current_render_is_not_historical():
    marks = determine_marks(_assessment(), _sections(), historical=False)
    assert DocumentMark.HISTORICAL not in marks


# ------------------------------------------------------------------ SECTION_UNAVAILABLE ---
def test_missing_section_is_section_unavailable():
    marks = determine_marks(_assessment(), _sections(all_available=False), historical=False)
    assert DocumentMark.SECTION_UNAVAILABLE in marks


def test_all_sections_available_no_section_mark():
    marks = determine_marks(_assessment(), _sections(all_available=True), historical=False)
    assert DocumentMark.SECTION_UNAVAILABLE not in marks


# ------------------------------------------------------------------ composition ---
def test_marks_compose_historical_and_not_final_and_section():
    # A superseded CRITICAL assessment with a missing section -> three marks together.
    marks = determine_marks(
        _assessment(severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW", superseded_by=2002),
        _sections(all_available=False),
        historical=True,
    )
    assert DocumentMark.NOT_FINAL in marks
    assert DocumentMark.HISTORICAL in marks
    assert DocumentMark.SECTION_UNAVAILABLE in marks


def test_marks_have_no_duplicates():
    # CRITICAL + PENDING both imply NOT_FINAL — it must appear once, not twice.
    marks = determine_marks(
        _assessment(severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW"),
        _sections(), historical=False)
    assert marks.count(DocumentMark.NOT_FINAL) == 1


def test_returns_a_stable_ordering():
    # Deterministic order (for reproducible persistence/audit) regardless of which fired.
    a = determine_marks(
        _assessment(risk_score=None, severity=None, review_status="PENDING_HUMAN_REVIEW",
                    superseded_by=2002),
        _sections(all_available=False), historical=True)
    b = determine_marks(
        _assessment(risk_score=None, severity=None, review_status="PENDING_HUMAN_REVIEW",
                    superseded_by=2002),
        _sections(all_available=False), historical=True)
    assert a == b
