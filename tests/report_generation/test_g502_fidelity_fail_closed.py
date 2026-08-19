"""G502 — fidelity gate fails closed (FR-5, AC-5).

Proves the report-layer anti-drift control's SAFETY property at the gate level: an assembled model
carrying an off-book number (a value in no source row) does NOT pass the fidelity gate, and the
fabricated value is surfaced by name so the service can withhold on it. A clean model passes and
would proceed to render.

Scope note (honest): the FULL service-path assertion — that a failed gate makes run_report yield
WITHHELD/PROVENANCE_MISMATCH and writes NO artifact — is asserted in G901/G902, where the service
exists. Here we assert the gate contract the service relies on. No new production code; this is an
acceptance gate over G402 (assemble) + G501 (check).
"""
from __future__ import annotations

from agents.report_generation.assembler import assemble_report
from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.fidelity import build_source_index, fidelity_check
from agents.report_generation.model import ReportModel, ReportSection, Slot
from agents.report_generation.tools.analysis_results_read import AnalysisResultsReadResult
from agents.report_generation.tools.validated_readings_read import ValidatedReadingsReadResult
from agents.risk_reasoning.statuses import Severity


HEADLINES = HeadlineTable(
    phrases=tuple((s, f"HEADLINE::{s.value}") for s in Severity),
    withheld_phrase="HEADLINE::WITHHELD",
)
CONFIG = ReportConfig(
    report_template_version="rev2", appendix_max_rows=500,
    letterhead_ref="lh.png", template_ref="t.html",
)


def _assessment():
    return dict(
        id=1001, bridge_id="bridge-7", cycle_id="cycle-42", assessment_version=3,
        risk_score=48, severity="WARNING", recommendation="Schedule inspection.",
        explanation="Deflection ratio elevated at pier 3.", review_status="FINAL",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )


def _analysis():
    return AnalysisResultsReadResult(
        available=True,
        results=({"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]},),
        missing_ids=(),
    )


def _readings():
    return ValidatedReadingsReadResult(
        available=True, readings=({"id": 110, "value": 1.1},),
        missing_ids=(), truncated=False, total_available=1,
    )


def _index_for(assessment):
    return build_source_index(
        assessment,
        _analysis().results,
        _readings().readings,
        tuple((s.value, HEADLINES.headline_for(s)) for s in Severity),
    )


# ------------------------------------------------------------------ clean path ---
def test_faithfully_assembled_model_passes_the_gate():
    a = _assessment()
    m = assemble_report(a, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    verdict = fidelity_check(m, _index_for(a), tolerance=CONFIG.fidelity_tolerance)
    assert verdict.passed is True
    assert verdict.offending == ()


# ------------------------------------------------------------------ fail closed ---
def test_injected_offbook_number_fails_the_gate_and_is_named():
    a = _assessment()
    # Simulate drift: a post-assembly tamper that puts a number present in NO source row into a slot.
    tampered = ReportModel(
        bridge_id="bridge-7", assessment_id=1001, assessment_version=3, severity="WARNING",
        rendered_at="T",
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot(48, "risk_assessments:1001:risk_score"),
                # off-book: "72 mm beyond limit" — 72 is nowhere in the finalized inputs
                Slot(72, "analysis_results:11:result"),
            )),
        ),
    )
    verdict = fidelity_check(tampered, _index_for(a), tolerance=CONFIG.fidelity_tolerance)
    assert verdict.passed is False
    # the fabricated value is surfaced by name so the service can withhold on PROVENANCE_MISMATCH
    assert any(val == 72 for _, val in verdict.offending)


def test_default_tolerance_is_exact_match_the_failsafe():
    # The config the service passes defaults to 0.0 — the strictest anti-drift setting.
    assert CONFIG.fidelity_tolerance == 0.0
    a = _assessment()
    drifted = ReportModel(
        bridge_id="b", assessment_id=1001, assessment_version=3, severity="WARNING", rendered_at="T",
        sections=(ReportSection(name="appendix", available=True, slots=(
            Slot(1.10001, "validated_readings:110:value"),  # source 1.1 — tiny drift
        )),),
    )
    assert fidelity_check(drifted, _index_for(a), tolerance=CONFIG.fidelity_tolerance).passed is False


def test_fabricated_value_never_appears_in_a_passed_verdict():
    # The safety line: a model containing a fabricated number can NEVER produce passed=True.
    a = _assessment()
    for bad_value in (0, 100, 72, -1, 999):
        m = ReportModel(
            bridge_id="b", assessment_id=1001, assessment_version=3, severity="WARNING",
            rendered_at="T",
            sections=(ReportSection(name="exec_summary", available=True, slots=(
                Slot(bad_value, "risk_assessments:1001:risk_score"),  # source is 48
            )),),
        )
        v = fidelity_check(m, _index_for(a), tolerance=0.0)
        if bad_value != 48:
            assert v.passed is False, f"fabricated score {bad_value} wrongly passed the gate"
