"""G902 — never-crash + atomicity (FR-12, AC-12).

Acceptance gate over G901. The constitution requires that NO input crashes the report service —
every scenario yields a structured ReportSummary, never a stack trace — and that a mid-render
failure leaves NO partial artifact (the write is atomic: the report_artifacts row + its audit
appear together after a successful render, or not at all).

The four-scenario constitution set:
  1. normal              -> RENDERED, artifact persisted;
  2. missing assessment  -> WITHHELD/ASSESSMENT_NOT_FOUND, no artifact;
  3. unreadable provenance (a source read raises) -> ERROR, no artifact;
  4. malformed scope key  -> structured outcome (WITHHELD or ERROR), never a raise.

No new production code.
"""
from __future__ import annotations

from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.render.fake_renderer import FakeRenderer
from agents.report_generation.report_statuses import ReportOutcome
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
        if "analysis" in self._raise_on:
            raise RuntimeError("boom: analysis read failed")
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


def _sources(**kw):
    return FakeSources(
        [_assessment()],
        [{"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]}],
        [{"id": 110, "value": 1.1}],
        **kw,
    )


def _run(sources, store, scope, renderer=None):
    return run_report(
        scope, sources=sources, store=store, config=CONFIG, headlines=HEADLINES,
        renderer=renderer or FakeRenderer(), rendered_at="T",
    )


# ------------------------------------------------------------------ the four scenarios ---
def test_1_normal_renders_and_persists():
    store = FakeReportStore()
    s = _run(_sources(), store, AssessmentScope("b", "c"))
    assert s.outcome is ReportOutcome.RENDERED
    assert len(store.rows) == 1


def test_2_missing_assessment_is_structured_no_artifact():
    store = FakeReportStore()
    s = _run(_sources(), store, AssessmentScope("ghost", "none"))
    assert s.outcome is ReportOutcome.WITHHELD
    assert s.artifact_ref is None
    assert store.rows == ()


def test_3_unreadable_provenance_is_structured_error_no_artifact():
    store = FakeReportStore()
    s = _run(_sources(raise_on={"analysis"}), store, AssessmentScope("b", "c"))
    assert s.outcome is ReportOutcome.ERROR
    assert s.error
    assert store.rows == ()               # no partial artifact


def test_4_malformed_scope_is_structured_never_raises():
    store = FakeReportStore()
    # A scope with None fields is malformed; the service must return structured, not raise.
    s = _run(_sources(), store, AssessmentScope(None, None))  # type: ignore[arg-type]
    assert s.outcome in (ReportOutcome.WITHHELD, ReportOutcome.ERROR)
    assert s.ok is False


def test_all_four_scenarios_return_a_summary_none_raise():
    scenarios = [
        (_sources(), AssessmentScope("b", "c")),
        (_sources(), AssessmentScope("ghost", "none")),
        (_sources(raise_on={"assessment"}), AssessmentScope("b", "c")),
        (_sources(), AssessmentScope(None, None)),  # type: ignore[arg-type]
    ]
    for sources, scope in scenarios:
        store = FakeReportStore()
        summary = _run(sources, store, scope)     # must not raise for ANY
        assert summary is not None
        assert summary.outcome in (
            ReportOutcome.RENDERED, ReportOutcome.WITHHELD, ReportOutcome.ERROR)


# ------------------------------------------------------------------ atomicity ---
def test_mid_render_failure_persists_no_partial_artifact():
    class BoomRenderer:
        def render(self, model):
            raise RuntimeError("boom: render died mid-way")

    store = FakeReportStore()
    s = _run(_sources(), store, AssessmentScope("b", "c"), renderer=BoomRenderer())
    assert s.outcome is ReportOutcome.ERROR
    assert store.rows == ()                       # nothing half-written
    # the failure is still audited (an event happened), even though no artifact row exists
    assert [a.decision for a in store.audit_rows] == ["REPORT_ERROR"]


def test_error_summary_never_carries_an_artifact_ref():
    class BoomRenderer:
        def render(self, model):
            raise RuntimeError("boom")

    store = FakeReportStore()
    s = _run(_sources(), store, AssessmentScope("b", "c"), renderer=BoomRenderer())
    assert s.artifact_ref is None


def test_successful_render_persists_row_and_audit_together():
    store = FakeReportStore()
    _run(_sources(), store, AssessmentScope("b", "c"))
    # atomic success: exactly one row AND exactly one matching audit
    assert len(store.rows) == 1
    assert [a.decision for a in store.audit_rows] == ["REPORT_RENDERED"]
