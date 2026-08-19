"""G702 — not-final-never-settled + honest withheld report (FR-7/AC-7, FR-8/AC-8).

Integration over G402 (assemble) + G701 (marks): proves through the assembled document, not just
the mark function, that
  * a CRITICAL / PENDING_HUMAN_REVIEW assessment produces a report marked NOT_FINAL, whose
    recommendation is presented as pending — and a downstream consumer stand-in HOLDS it (never
    treats it as final);
  * a withheld-score assessment produces a RENDERED report marked SCORE_WITHHELD + NOT_FINAL that
    uses the VERBATIM withheld explanation and prints no fabricated score.

No new production code — an acceptance gate. Mirrors the Risk build's DownstreamConsumer idea
(HELD vs ACTED) at the report layer.
"""
from __future__ import annotations

from agents.report_generation.assembler import assemble_report
from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.marks import determine_marks
from agents.report_generation.report_statuses import DocumentMark
from agents.report_generation.tools.analysis_results_read import AnalysisResultsReadResult
from agents.report_generation.tools.validated_readings_read import ValidatedReadingsReadResult
from agents.risk_reasoning.statuses import Severity


HEADLINES = HeadlineTable(
    phrases=tuple((s, f"HEADLINE::{s.value}") for s in Severity),
    withheld_phrase="Score withheld pending human review.",
)
CONFIG = ReportConfig(
    report_template_version="rev2", appendix_max_rows=500,
    letterhead_ref="lh.png", template_ref="t.html",
)


def _analysis():
    return AnalysisResultsReadResult(
        available=True, results=({"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]},),
        missing_ids=())


def _readings():
    return ValidatedReadingsReadResult(
        available=True, readings=({"id": 110, "value": 1.1},), missing_ids=(),
        truncated=False, total_available=1)


def _assemble(assessment, *, historical=False):
    model = assemble_report(assessment, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    marks = determine_marks(assessment, model.sections, historical=historical)
    return model, marks


# --- A downstream consumer stand-in: it must HOLD a not-final report, ACT only on a clean one. ---
class DownstreamConsumer:
    def decide(self, marks):
        if DocumentMark.NOT_FINAL in marks:
            return "HELD"
        return "ACTED"


# ------------------------------------------------------------------ AC-7 not final ---
def test_critical_report_is_not_final_and_held_downstream():
    a = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=1,
        risk_score=91, severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW",
        recommendation="Immediate engineering inspection required.",
        explanation="Multiple limits exceeded at pier 3.", source_analysis_ids=[11],
        standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    _, marks = _assemble(a)
    assert DocumentMark.NOT_FINAL in marks
    assert DownstreamConsumer().decide(marks) == "HELD"


def test_pending_report_is_not_final_and_held():
    a = dict(
        id=1002, bridge_id="b", cycle_id="c", assessment_version=1,
        risk_score=60, severity="WARNING", review_status="PENDING_HUMAN_REVIEW",
        recommendation="Review recommended.", explanation="Elevated deflection.",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    _, marks = _assemble(a)
    assert DocumentMark.NOT_FINAL in marks
    assert DownstreamConsumer().decide(marks) == "HELD"


def test_final_report_is_acted_on():
    a = dict(
        id=1003, bridge_id="b", cycle_id="c", assessment_version=1,
        risk_score=20, severity="WATCH", review_status="FINAL",
        recommendation="Routine monitoring.", explanation="Stable readings.",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    _, marks = _assemble(a)
    assert marks == ()
    assert DownstreamConsumer().decide(marks) == "ACTED"


# ------------------------------------------------------------------ AC-8 honest withheld ---
def test_withheld_report_uses_verbatim_explanation_and_no_score():
    withheld_explanation = (
        "Score withheld: sensor coverage 40% is below the required floor; "
        "no reliable whole-bridge score can be computed."
    )
    a = dict(
        id=2001, bridge_id="b", cycle_id="c", assessment_version=1,
        risk_score=None, severity=None, review_status="PENDING_HUMAN_REVIEW",
        recommendation="Restore sensor coverage; manual inspection advised.",
        explanation=withheld_explanation, source_analysis_ids=[11],
        standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    model, marks = _assemble(a)

    # Marked honestly.
    assert DocumentMark.SCORE_WITHHELD in marks
    assert DocumentMark.NOT_FINAL in marks
    assert DownstreamConsumer().decide(marks) == "HELD"

    # The explanation is byte-identical (verbatim), and the printed score slot is None (no fabrication).
    by_ref = {s.source_ref: s.value for s in model.all_slots()}
    assert by_ref["risk_assessments:2001:explanation"] == withheld_explanation
    assert by_ref["risk_assessments:2001:risk_score"] is None


def test_withheld_report_headline_is_the_withheld_line_not_a_band():
    a = dict(
        id=2002, bridge_id="b", cycle_id="c", assessment_version=1,
        risk_score=None, severity=None, review_status="PENDING_HUMAN_REVIEW",
        recommendation="Manual inspection.", explanation="Coverage too low to score.",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    model, _ = _assemble(a)
    by_ref = {s.source_ref: s.value for s in model.all_slots()}
    assert by_ref["headline_table:WITHHELD"] == "Score withheld pending human review."


# ------------------------------------------------------------------ historical + not-final compose ---
def test_historical_reprint_of_a_critical_is_marked_both():
    a = dict(
        id=3001, bridge_id="b", cycle_id="c", assessment_version=2,
        risk_score=88, severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW",
        recommendation="Inspect.", explanation="Historical critical assessment.",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=4001,
    )
    _, marks = _assemble(a, historical=True)
    assert DocumentMark.HISTORICAL in marks
    assert DocumentMark.NOT_FINAL in marks
    assert DownstreamConsumer().decide(marks) == "HELD"
