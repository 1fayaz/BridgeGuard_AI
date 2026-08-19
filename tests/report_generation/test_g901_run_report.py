"""G901 — run_report(scope, *, sources, store, config, headlines, renderer, ...) (orchestrator).

Wires the per-report flow (plan §6):
  1. resolve the assessment (G301) — absent -> WITHHELD/ASSESSMENT_NOT_FOUND, stop;
  2. read analysis + readings (G302/G303);
  3. assemble the model (G402);
  4. fidelity gate (G501) — fail -> WITHHELD/PROVENANCE_MISMATCH, no artifact, stop;
  5. render (via the RenderPort);
  6. determine marks (G701);
  7. atomic write: persist the report_artifacts row + decision_log (G802);
  8. return a ReportSummary.
Per-report failure isolation -> structured status, NEVER raises (FR-12).

Acceptance (tasks.md G901): a normal FINAL scope -> RENDERED (no marks) + a persisted artifact; a
pending/critical -> RENDERED + NOT_FINAL; a withheld-score -> RENDERED + SCORE_WITHHELD; an off-book
number -> WITHHELD/PROVENANCE_MISMATCH (no artifact); a missing assessment ->
WITHHELD/ASSESSMENT_NOT_FOUND; an injected exception -> a structured ERROR summary, nothing raises.
"""
from __future__ import annotations

from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.render.fake_renderer import FakeRenderer
from agents.report_generation.report_statuses import (
    DocumentMark,
    ReportOutcome,
    WithheldReason,
)
from agents.report_generation.service import AssessmentScope, run_report
from agents.report_generation.store import FakeReportStore
from agents.risk_reasoning.statuses import Severity


HEADLINES = HeadlineTable(
    phrases=tuple((s, f"HEADLINE::{s.value}") for s in Severity),
    withheld_phrase="Score withheld pending human review.",
)
CONFIG = ReportConfig(
    report_template_version="rev2", appendix_max_rows=500,
    letterhead_ref="lh.png", template_ref="t.html",
)


# --- One combined fake exposing the three read source protocols. ---
class FakeSources:
    def __init__(self, assessments, analyses, readings, *, raise_on=None):
        self._assessments = [dict(a) for a in assessments]
        self._analyses = {a["id"]: a for a in analyses}
        self._readings = {r["id"]: r for r in readings}
        self._raise_on = raise_on or set()

    def current_assessment_for(self, bridge_id, cycle_id):
        if "assessment" in self._raise_on:
            raise RuntimeError("boom: assessment read failed")
        for a in self._assessments:
            if a["bridge_id"] == bridge_id and a["cycle_id"] == cycle_id and a["superseded_by"] is None:
                return dict(a)
        return None

    def assessment_by_id(self, assessment_id):
        for a in self._assessments:
            if a["id"] == assessment_id:
                return dict(a)
        return None

    def analysis_results_by_ids(self, ids):
        return [dict(self._analyses[i]) for i in ids if i in self._analyses]

    def validated_readings_by_ids(self, ids):
        return [dict(self._readings[i]) for i in ids if i in self._readings]


def _assessment(**over):
    base = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
        risk_score=48, severity="WARNING", review_status="FINAL",
        recommendation="Schedule inspection.", explanation="Deflection elevated at pier 3.",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    base.update(over)
    return base


def _analyses():
    return [{"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]}]


def _readings():
    return [{"id": 110, "value": 1.1}]


def _sources(assessment=None, **kw):
    return FakeSources([assessment or _assessment()], _analyses(), _readings(), **kw)


def _run(sources, store, scope=None, **kw):
    return run_report(
        scope or AssessmentScope("b", "c"),
        sources=sources, store=store, config=CONFIG, headlines=HEADLINES,
        renderer=FakeRenderer(), rendered_at="T", **kw,
    )


# ------------------------------------------------------------------ RENDERED clean ---
def test_final_scope_renders_clean_and_persists_an_artifact():
    store = FakeReportStore()
    summary = _run(_sources(), store)
    assert summary.ok is True
    assert summary.outcome is ReportOutcome.RENDERED
    assert summary.marks == ()
    assert summary.artifact_ref
    # persisted: one current report_artifacts row + a REPORT_RENDERED audit
    assert len([r for r in store.rows if r.superseded_by is None]) == 1
    assert [a.decision for a in store.audit_rows] == ["REPORT_RENDERED"]


# ------------------------------------------------------------------ RENDERED + NOT_FINAL ---
def test_critical_scope_renders_not_final():
    store = FakeReportStore()
    summary = _run(_sources(_assessment(
        risk_score=91, severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW")), store)
    assert summary.outcome is ReportOutcome.RENDERED
    assert DocumentMark.NOT_FINAL in summary.marks


# ------------------------------------------------------------------ RENDERED + SCORE_WITHHELD ---
def test_withheld_score_scope_renders_score_withheld():
    store = FakeReportStore()
    summary = _run(_sources(_assessment(
        risk_score=None, severity=None, review_status="PENDING_HUMAN_REVIEW",
        explanation="Coverage too low to score.")), store)
    assert summary.outcome is ReportOutcome.RENDERED
    assert DocumentMark.SCORE_WITHHELD in summary.marks
    assert DocumentMark.NOT_FINAL in summary.marks


# ------------------------------------------------------------------ WITHHELD / not found ---
def test_missing_assessment_is_withheld_not_found_no_artifact():
    store = FakeReportStore()
    summary = _run(_sources(), store, scope=AssessmentScope("ghost", "none"))
    assert summary.ok is False
    assert summary.outcome is ReportOutcome.WITHHELD
    assert summary.withheld_reason is WithheldReason.ASSESSMENT_NOT_FOUND
    assert summary.artifact_ref is None
    # no artifact row persisted (there is no assessment to key on); the event is audited
    assert [r for r in store.rows] == []
    assert [a.decision for a in store.audit_rows] == ["REPORT_WITHHELD"]


# ------------------------------------------------------------------ WITHHELD / provenance ---
def test_offbook_number_is_withheld_provenance_mismatch_no_artifact():
    # Force a mismatch: the analysis payload the assembler copies differs from the fidelity source.
    # Simulate by making the readings row absent from the fidelity index but present in assembly —
    # instead, tamper the assessment so the assembled explanation traces but a number does not.
    store = FakeReportStore()
    # An assessment whose analysis row the reader returns, but we corrupt the stored analysis value
    # AFTER the fidelity index is built by using a renderer-independent path: the simplest reliable
    # trigger is a readings value that the fidelity index will not contain.
    class DriftSources(FakeSources):
        def validated_readings_by_ids(self, ids):
            # assembler sees value 9.9, but build_source_index (below) is built from the SAME read,
            # so to force drift we return DIFFERENT values on the second call.
            self._calls = getattr(self, "_calls", 0) + 1
            base = 1.1 if self._calls == 1 else 9.9
            return [{"id": 110, "value": base}]

    src = DriftSources([_assessment()], _analyses(), _readings())
    summary = run_report(
        AssessmentScope("b", "c"), sources=src, store=store, config=CONFIG, headlines=HEADLINES,
        renderer=FakeRenderer(), rendered_at="T",
    )
    assert summary.outcome is ReportOutcome.WITHHELD
    assert summary.withheld_reason is WithheldReason.PROVENANCE_MISMATCH
    assert summary.artifact_ref is None
    # a first-class WITHHELD report_artifacts row IS persisted (assessment identity is known)
    assert len(store.rows) == 1
    assert store.rows[0].result.outcome is ReportOutcome.WITHHELD
    assert [a.decision for a in store.audit_rows] == ["REPORT_WITHHELD"]


# ------------------------------------------------------------------ ERROR / never raises ---
def test_injected_read_exception_is_structured_error_never_raises():
    store = FakeReportStore()
    summary = _run(_sources(raise_on={"assessment"}), store)  # must not raise
    assert summary.ok is False
    assert summary.outcome is ReportOutcome.ERROR
    assert summary.error
    assert summary.artifact_ref is None


def test_injected_renderer_exception_is_structured_error_no_partial_artifact():
    class BoomRenderer:
        def render(self, model):
            raise RuntimeError("boom: render failed")

    store = FakeReportStore()
    summary = run_report(
        AssessmentScope("b", "c"), sources=_sources(), store=store, config=CONFIG,
        headlines=HEADLINES, renderer=BoomRenderer(), rendered_at="T",
    )
    assert summary.outcome is ReportOutcome.ERROR
    assert summary.error
    # atomic: a mid-render failure persists NO artifact row
    assert [r for r in store.rows] == []


# ------------------------------------------------------------------ historical ---
def test_historical_scope_renders_marked_historical():
    store = FakeReportStore()
    superseded = _assessment(id=900, assessment_version=2, superseded_by=1001)
    src = FakeSources([superseded, _assessment()], _analyses(), _readings())
    summary = run_report(
        AssessmentScope("b", "c", assessment_id=900), sources=src, store=store, config=CONFIG,
        headlines=HEADLINES, renderer=FakeRenderer(), rendered_at="T", historical=True,
    )
    assert summary.outcome is ReportOutcome.RENDERED
    assert DocumentMark.HISTORICAL in summary.marks
