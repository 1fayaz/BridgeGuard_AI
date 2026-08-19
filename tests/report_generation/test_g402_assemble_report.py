"""G402 — assemble_report(assessment, analysis, readings, config) (pure).

The core "assemble, never re-decide" function (FR-1). It builds a ReportModel by COPYING finalized
values into Slots: the verbatim explanation, the band headline (the ONLY non-copied text — a fixed
HeadlineTable lookup), the score/severity/recommendation as-is, and the tables/appendix from the
reads. No recomputation, re-derivation, re-mapping, or rewording — each slot's value is a copy +
its source ref. A missing section is marked available=False.

Acceptance (tasks.md G402): every populated slot's value equals its source value; the explanation
slot is byte-identical to assessment.explanation; the headline is exactly HeadlineTable[severity];
no slot value is computed/derived; a missing-input section is available=False.
"""
from __future__ import annotations

from agents.report_generation.assembler import assemble_report
from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.tools.analysis_results_read import AnalysisResultsReadResult
from agents.report_generation.tools.validated_readings_read import ValidatedReadingsReadResult
from agents.risk_reasoning.statuses import Severity


HEADLINES = HeadlineTable(
    phrases=(
        (Severity.SAFE, "Structure within normal parameters."),
        (Severity.WATCH, "Minor anomalies; monitoring advised."),
        (Severity.WARNING, "Elevated readings; review recommended."),
        (Severity.CRITICAL, "Severe indicators; immediate attention required."),
    ),
    withheld_phrase="Score withheld pending human review.",
)

CONFIG = ReportConfig(
    report_template_version="2026-06-gov-template-rev2",
    appendix_max_rows=500,
    letterhead_ref="gov-letterhead.png",
    template_ref="report_template.html",
)


def _assessment(**over):
    base = dict(
        id=1001,
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_version=3,
        risk_score=48,
        severity="WARNING",
        recommendation="Schedule inspection within 30 days.",
        explanation="Deflection ratio elevated at pier 3; within limit but trending up.",
        review_status="FINAL",
        source_analysis_ids=[11, 12],
        standard_code="AASHTO",
        standard_version="2020",
        superseded_by=None,
    )
    base.update(over)
    return base


def _analysis(available=True):
    if not available:
        return AnalysisResultsReadResult(available=False, results=(), missing_ids=(12,))
    return AnalysisResultsReadResult(
        available=True,
        results=(
            {"id": 11, "sensor_id": "s-a", "calculation": "DEFLECTION_LIMIT",
             "result": {"ratio": 0.62}, "source_validated_ids": [110]},
            {"id": 12, "sensor_id": "s-b", "calculation": "RMS",
             "result": {"rms": 1.4}, "source_validated_ids": [120]},
        ),
        missing_ids=(),
    )


def _readings(available=True):
    if not available:
        return ValidatedReadingsReadResult(
            available=False, readings=(), missing_ids=(110,), truncated=False, total_available=0)
    return ValidatedReadingsReadResult(
        available=True,
        readings=({"id": 110, "value": 1.1, "unit": "mm"}, {"id": 120, "value": 2.2, "unit": "mm"}),
        missing_ids=(),
        truncated=False,
        total_available=2,
    )


# ------------------------------------------------------------------ identity ---
def test_model_carries_the_assessment_identity_verbatim():
    m = assemble_report(_assessment(), _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    assert m.bridge_id == "bridge-7"
    assert m.assessment_id == 1001
    assert m.assessment_version == 3
    assert m.severity == "WARNING"
    assert m.rendered_at == "T"


# ------------------------------------------------------------------ verbatim explanation (FR-2) ---
def test_explanation_slot_is_byte_identical():
    a = _assessment()
    m = assemble_report(a, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    exec_slots = {s.source_ref: s for s in m.section("exec_summary").slots}
    expl = exec_slots["risk_assessments:1001:explanation"]
    assert expl.value == a["explanation"]  # exact copy, not reworded/summarised


def test_score_severity_recommendation_are_copied_not_derived():
    a = _assessment()
    m = assemble_report(a, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    by_ref = {s.source_ref: s.value for s in m.all_slots()}
    assert by_ref["risk_assessments:1001:risk_score"] == 48
    assert by_ref["risk_assessments:1001:severity"] == "WARNING"
    assert by_ref["risk_assessments:1001:recommendation"] == "Schedule inspection within 30 days."


# ------------------------------------------------------------------ headline (FR-2, the ONLY non-copy) ---
def test_headline_is_the_fixed_table_lookup_for_the_band():
    m = assemble_report(_assessment(), _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    by_ref = {s.source_ref: s.value for s in m.all_slots()}
    assert by_ref["headline_table:WARNING"] == "Elevated readings; review recommended."


def test_headline_changes_with_the_band_not_the_data():
    crit = _assessment(severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW")
    m = assemble_report(crit, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    by_ref = {s.source_ref: s.value for s in m.all_slots()}
    assert by_ref["headline_table:CRITICAL"] == "Severe indicators; immediate attention required."


def test_headline_source_ref_points_at_config_not_an_upstream_row():
    # The headline is the one value NOT from an upstream row; its provenance is the config table.
    m = assemble_report(_assessment(), _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    headline_slots = [s for s in m.all_slots() if s.source_ref.startswith("headline_table:")]
    assert len(headline_slots) == 1


# ------------------------------------------------------------------ tables copied from reads ---
def test_analysis_values_are_copied_into_the_math_section():
    m = assemble_report(_assessment(), _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    math = m.section("math_results")
    assert math.available is True
    refs = {s.source_ref for s in math.slots}
    assert "analysis_results:11:result" in refs
    assert "analysis_results:12:result" in refs


def test_readings_values_are_copied_into_the_appendix():
    m = assemble_report(_assessment(), _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    appx = m.section("appendix")
    assert appx.available is True
    refs = {s.source_ref for s in appx.slots}
    assert "validated_readings:110:value" in refs
    assert "validated_readings:120:value" in refs


# ------------------------------------------------------------------ missing sections (FR-6) ---
def test_missing_analysis_marks_math_section_unavailable():
    m = assemble_report(_assessment(), _analysis(available=False), _readings(), CONFIG, HEADLINES,
                        rendered_at="T")
    assert m.section("math_results").available is False
    assert m.section("math_results").slots == ()


def test_missing_readings_marks_appendix_unavailable():
    m = assemble_report(_assessment(), _analysis(), _readings(available=False), CONFIG, HEADLINES,
                        rendered_at="T")
    assert m.section("appendix").available is False


def test_exec_summary_available_even_when_downstream_sections_missing():
    # The verdict/explanation always render; only the data-backed sections degrade.
    m = assemble_report(_assessment(), _analysis(available=False), _readings(available=False),
                        CONFIG, HEADLINES, rendered_at="T")
    assert m.section("exec_summary").available is True


# ------------------------------------------------------------------ purity ---
def test_assemble_does_not_mutate_the_inputs():
    a = _assessment()
    before = dict(a)
    assemble_report(a, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    assert a == before  # pure: the assessment dict is untouched


def test_every_slot_has_provenance():
    m = assemble_report(_assessment(), _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    assert all(s.source_ref for s in m.all_slots())
