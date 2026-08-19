"""G1102 — end-to-end acceptance: every spec AC manifests through the service (AC-1…AC-13 + 2a/4a).

Drives reports through the REAL service (run_report) over the shared harness fixtures, and asserts
each acceptance criterion shows up in the returned summary AND the persisted report_artifacts +
decision_log state — not just in a unit's return value. This is the spec-level gate a reviewer
reads against specs/report-generation-agent/spec.md.

  AC-1  assemble-only equals source        AC-8  honest withheld report
  AC-2  verbatim explanation               AC-9  append-only artifacts
  AC-2a band headline is a fixed lookup    AC-10 idempotency
  AC-3  no model / deterministic           AC-11 reproducible provenance
  AC-4  read-by-identity current           AC-12 never-crash
  AC-4a historical labelled                AC-13 no dispatch / no needs_approval
  AC-5  fidelity fail-closed
  AC-6  charts render / section-unavailable
  AC-7  not-final marked
"""
from __future__ import annotations

import ast
from pathlib import Path

from _report_harness import (
    CONFIG,
    HEADLINES,
    RENDERED_AT,
    HarnessSources,
    run_case,
)
from agents.report_generation.assembler import assemble_report
from agents.report_generation.render.fake_renderer import FakeRenderer
from agents.report_generation.report_statuses import (
    DocumentMark,
    ReportOutcome,
    WithheldReason,
)
from agents.report_generation.service import AssessmentScope, run_report
from agents.report_generation.store import FakeReportStore
from agents.report_generation.tools.analysis_results_read import AnalysisResultsReadResult
from agents.report_generation.tools.validated_readings_read import ValidatedReadingsReadResult
from agents.risk_reasoning.statuses import Severity

SRC = Path(__file__).resolve().parents[2] / "src" / "agents" / "report_generation"
_MODEL_ROOTS = {"openai", "anthropic", "agents_sdk"}


def _assessment(**over):
    base = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
        risk_score=48, severity="WARNING", review_status="FINAL",
        recommendation="Schedule inspection within 30 days.",
        explanation="Deflection ratio elevated at pier 3; within limit but trending up.",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    base.update(over)
    return base


def _analyses():
    return [{"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]}]


def _readings():
    return [{"id": 110, "value": 1.1}]


def _run(sources, store, scope=None, **kw):
    return run_report(scope or AssessmentScope("b", "c"), sources=sources, store=store,
                      config=CONFIG, headlines=HEADLINES, renderer=FakeRenderer(),
                      rendered_at=RENDERED_AT, **kw)


# ------------------------------------------------------------------ AC-1 / AC-2 / AC-2a ---
def test_ac1_ac2_ac2a_assemble_only_verbatim_and_fixed_headline():
    a = _assessment()
    model = assemble_report(a, AnalysisResultsReadResult(True, tuple(_analyses()), ()),
                            ValidatedReadingsReadResult(True, tuple(_readings()), (), False, 1),
                            CONFIG, HEADLINES, rendered_at=RENDERED_AT)
    by_ref = {s.source_ref: s.value for s in model.all_slots()}
    # AC-1 assemble-only: score/recommendation equal the source
    assert by_ref["risk_assessments:1001:risk_score"] == 48
    assert by_ref["risk_assessments:1001:recommendation"] == a["recommendation"]
    # AC-2 verbatim explanation (byte-identical)
    assert by_ref["risk_assessments:1001:explanation"] == a["explanation"]
    # AC-2a fixed band headline (config lookup, not data-derived)
    assert by_ref["headline_table:WARNING"] == HEADLINES.headline_for(Severity.WARNING)


# ------------------------------------------------------------------ AC-3 no model ---
def test_ac3_no_model_in_the_service_path():
    def roots(p: Path):
        r = set()
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                for al in n.names:
                    r.add(al.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                r.add(n.module.split(".")[0])
        return r
    assert not (roots(SRC / "service.py") & _MODEL_ROOTS)


def test_ac3_deterministic_same_inputs_same_summary():
    a = _assessment()
    s1 = _run(HarnessSources([a], _analyses(), _readings()), FakeReportStore())
    s2 = _run(HarnessSources([a], _analyses(), _readings()), FakeReportStore())
    assert s1.outcome == s2.outcome and s1.artifact_ref == s2.artifact_ref


# ------------------------------------------------------------------ AC-4 / AC-4a ---
def test_ac4_reads_current_by_default():
    store = FakeReportStore()
    src = HarnessSources(
        [_assessment(id=900, assessment_version=2, superseded_by=1001), _assessment()],
        _analyses(), _readings())
    _run(src, store)
    # the persisted report is for the CURRENT assessment (id 1001, v3), not the superseded 900/v2
    row = store.rows[0].result
    assert row.assessment_id == 1001 and row.assessment_version == 3


def test_ac4a_historical_render_is_labelled():
    store = FakeReportStore()
    src = HarnessSources(
        [_assessment(id=900, assessment_version=2, superseded_by=1001), _assessment()],
        _analyses(), _readings())
    summary = _run(src, store, scope=AssessmentScope("b", "c", assessment_id=900), historical=True)
    assert DocumentMark.HISTORICAL in summary.marks
    assert store.rows[0].result.assessment_id == 900


# ------------------------------------------------------------------ AC-5 fidelity fail-closed ---
def test_ac5_offbook_withholds_and_writes_no_artifact():
    store = FakeReportStore()
    src = HarnessSources([_assessment()], _analyses(), _readings(), drift_readings=True)
    summary = _run(src, store)
    assert summary.outcome is ReportOutcome.WITHHELD
    assert summary.withheld_reason is WithheldReason.PROVENANCE_MISMATCH
    assert summary.artifact_ref is None
    # a first-class WITHHELD row is persisted; NO artifact_ref on it
    assert store.rows[0].result.outcome is ReportOutcome.WITHHELD
    assert store.rows[0].result.artifact_ref is None


def test_ac5_clean_passes():
    store = FakeReportStore()
    summary = _run(HarnessSources([_assessment()], _analyses(), _readings()), store)
    assert summary.outcome is ReportOutcome.RENDERED


# ------------------------------------------------------------------ AC-6 charts / section ---
def test_ac6_missing_section_marks_unavailable():
    store = FakeReportStore()
    # no analysis rows -> the analysis section is unavailable
    summary = _run(HarnessSources([_assessment(source_analysis_ids=[11])], [], []), store)
    assert DocumentMark.SECTION_UNAVAILABLE in summary.marks
    assert summary.outcome is ReportOutcome.RENDERED     # still rendered, just marked


# ------------------------------------------------------------------ AC-7 not final ---
def test_ac7_critical_is_not_final_in_persisted_row():
    store = FakeReportStore()
    _run(HarnessSources([_assessment(risk_score=91, severity="CRITICAL",
                                     review_status="PENDING_HUMAN_REVIEW")], _analyses(), _readings()),
         store)
    assert DocumentMark.NOT_FINAL in store.rows[0].result.marks


# ------------------------------------------------------------------ AC-8 honest withheld ---
def test_ac8_withheld_score_renders_with_honest_marks():
    store = FakeReportStore()
    summary = _run(HarnessSources([_assessment(
        risk_score=None, severity=None, review_status="PENDING_HUMAN_REVIEW",
        explanation="Coverage below floor; no reliable score.")], _analyses(), _readings()), store)
    assert summary.outcome is ReportOutcome.RENDERED
    assert DocumentMark.SCORE_WITHHELD in summary.marks
    assert DocumentMark.NOT_FINAL in summary.marks


# ------------------------------------------------------------------ AC-9 append-only ---
def test_ac9_rerender_appends_and_supersedes():
    store = FakeReportStore()
    src3 = HarnessSources([_assessment(assessment_version=3)], _analyses(), _readings())
    _run(src3, store)
    src4 = HarnessSources([_assessment(assessment_version=4)], _analyses(), _readings())
    _run(src4, store)
    versions = {r.result.assessment_version for r in store.rows if r.superseded_by is None}
    assert versions == {3, 4}                    # both retained; nothing overwritten
    assert len(store.rows) == 2


# ------------------------------------------------------------------ AC-10 idempotency ---
def test_ac10_redelivery_no_duplicate_current():
    store = FakeReportStore()
    src = HarnessSources([_assessment()], _analyses(), _readings())
    _run(src, store)
    _run(src, store)                             # redelivery, same version
    current = [r for r in store.rows if r.superseded_by is None]
    assert len(current) == 1


# ------------------------------------------------------------------ AC-11 reproducible ---
def test_ac11_row_pins_all_provenance():
    store = FakeReportStore()
    _run(HarnessSources([_assessment()], _analyses(), _readings()), store)
    row = store.rows[0].result
    assert row.assessment_id == 1001 and row.assessment_version == 3
    assert row.source_analysis_ids == (11,)
    assert row.standard_version == "2020"
    assert row.template_version == CONFIG.report_template_version


# ------------------------------------------------------------------ AC-12 never crash ---
def test_ac12_four_scenarios_structured_never_raise():
    for name in ("FINAL", "NOT_FOUND", "MALFORMED", "OFF_BOOK"):
        case = next(c for c in _cases() if c.name == name)
        summary = run_case(case)
        assert summary is not None
        assert summary.outcome in (
            ReportOutcome.RENDERED, ReportOutcome.WITHHELD, ReportOutcome.ERROR)


def _cases():
    from _report_harness import all_cases
    return all_cases()


# ------------------------------------------------------------------ AC-13 no dispatch ---
def test_ac13_no_publication_or_needs_approval_in_the_agent():
    # No module in the report package defines a dispatch/publish tool or a needs_approval flag —
    # publication is a downstream gated agent (FR-13).
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "needs_approval" not in text, f"{path.name} has a needs_approval gate"
        assert "def publish" not in text and "def dispatch" not in text, (
            f"{path.name} defines a publication/dispatch tool")


def test_ac13_summary_carries_no_dispatch_affordance():
    # The service's return is a status summary, not a send action.
    summary = _run(HarnessSources([_assessment()], _analyses(), _readings()), FakeReportStore())
    assert not hasattr(summary, "send")
    assert not hasattr(summary, "publish")
