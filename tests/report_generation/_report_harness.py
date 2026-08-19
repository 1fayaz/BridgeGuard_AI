"""Shared E2E scenario harness for the Report Generation Agent (G1101).

Underscore-prefixed so pytest does NOT collect it, but it is sibling-importable from the test
modules (prepend import mode), like the Risk build's tests/risk_reasoning/_harness.py. Named
`_report_harness` (not `_harness`) to avoid a sys.modules name collision with the Risk suite's
same-named helper under prepend import mode — both suites lack __init__.py, so a shared module name
would let whichever imports first win.

It scripts every report scenario through the REAL service (run_report) over a fake store + fake
renderer, so G1101 (this file's catalog) and G1102 (the AC assertions) drive one shared,
deterministic, replayable set of inputs:

  FINAL           a clean scored assessment            -> RENDERED, no marks
  CRITICAL        a critical assessment (pending)      -> RENDERED, NOT_FINAL
  WITHHELD_SCORE  the assessment withheld its score    -> RENDERED, SCORE_WITHHELD + NOT_FINAL
  HISTORICAL      a superseded assessment re-print     -> RENDERED, HISTORICAL
  MISSING_SECTION a referenced analysis row is absent  -> RENDERED, SECTION_UNAVAILABLE
  OFF_BOOK        a source value drifts post-index     -> WITHHELD, PROVENANCE_MISMATCH (no artifact)
  RE_RENDER       a newer assessment version rendered  -> RENDERED, supersedes the prior row
  REDELIVERY      the same version delivered twice      -> RENDERED, no duplicate current row
  MALFORMED       a scope with None fields             -> structured (never raises)
  NOT_FOUND       a scope resolving to no assessment   -> WITHHELD, ASSESSMENT_NOT_FOUND

Determinism is structural — no clock, no randomness (rendered_at is a fixed seam) — so replaying
the catalog twice yields identical summaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.render.fake_renderer import FakeRenderer
from agents.report_generation.report_result import ReportSummary
from agents.report_generation.service import AssessmentScope, run_report
from agents.report_generation.store import FakeReportStore
from agents.report_generation.report_statuses import DocumentMark, ReportOutcome, WithheldReason
from agents.risk_reasoning.statuses import Severity

RENDERED_AT = "2026-07-08T00:00:00Z"  # fixed seam — no clock in the harness

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
    appendix_max_rows=500, letterhead_ref="gov-letterhead.png", template_ref="report_template.html",
)

SCENARIO_NAMES = (
    "FINAL", "CRITICAL", "WITHHELD_SCORE", "HISTORICAL", "MISSING_SECTION",
    "OFF_BOOK", "RE_RENDER", "REDELIVERY", "MALFORMED", "NOT_FOUND",
)


# --- Fake sources exposing the three read protocols. -------------------------------------------
class HarnessSources:
    def __init__(self, assessments, analyses, readings, *, drift_readings=False):
        self._assessments = [dict(a) for a in assessments]
        self._analyses = {a["id"]: a for a in analyses}
        self._readings = {r["id"]: r for r in readings}
        self._drift_readings = drift_readings
        self._reading_calls = 0

    def current_assessment_for(self, bridge_id, cycle_id):
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
        rows = [dict(self._readings[i]) for i in ids if i in self._readings]
        if self._drift_readings:
            # First call (assembly) returns the true value; second call (fidelity index) drifts —
            # so a value in the assembled model traces to NO source -> PROVENANCE_MISMATCH.
            self._reading_calls += 1
            if self._reading_calls >= 2:
                for r in rows:
                    r["value"] = r["value"] + 100.0
        return rows


@dataclass(frozen=True, slots=True)
class Expectation:
    outcome: ReportOutcome
    marks: tuple[DocumentMark, ...] = ()
    withheld_reason: WithheldReason | None = None
    artifact_expected: bool = True


@dataclass(frozen=True, slots=True)
class ScenarioCase:
    name: str
    sources: Any
    scope: AssessmentScope
    historical: bool
    expectation: Expectation
    # optional pre-steps: a list of (scope, historical) to run before the scored step (re-render).
    presteps: tuple = ()


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


def all_cases() -> list[ScenarioCase]:
    """Build the full scenario catalog. Each is independent (its own sources)."""
    cases: list[ScenarioCase] = []

    cases.append(ScenarioCase(
        "FINAL", HarnessSources([_assessment()], _analyses(), _readings()),
        AssessmentScope("b", "c"), False, Expectation(ReportOutcome.RENDERED, marks=())))

    cases.append(ScenarioCase(
        "CRITICAL",
        HarnessSources([_assessment(risk_score=91, severity="CRITICAL",
                                    review_status="PENDING_HUMAN_REVIEW")], _analyses(), _readings()),
        AssessmentScope("b", "c"), False,
        Expectation(ReportOutcome.RENDERED, marks=(DocumentMark.NOT_FINAL,))))

    cases.append(ScenarioCase(
        "WITHHELD_SCORE",
        HarnessSources([_assessment(risk_score=None, severity=None,
                                    review_status="PENDING_HUMAN_REVIEW",
                                    explanation="Coverage 40% below floor; no reliable score.")],
                       _analyses(), _readings()),
        AssessmentScope("b", "c"), False,
        Expectation(ReportOutcome.RENDERED,
                    marks=(DocumentMark.SCORE_WITHHELD, DocumentMark.NOT_FINAL))))

    cases.append(ScenarioCase(
        "HISTORICAL",
        HarnessSources(
            [_assessment(id=900, assessment_version=2, superseded_by=1001), _assessment()],
            _analyses(), _readings()),
        AssessmentScope("b", "c", assessment_id=900), True,
        Expectation(ReportOutcome.RENDERED, marks=(DocumentMark.HISTORICAL,))))

    cases.append(ScenarioCase(
        "MISSING_SECTION",
        # references analysis id 11, but the store has none -> analysis section unavailable
        HarnessSources([_assessment(source_analysis_ids=[11])], [], []),
        AssessmentScope("b", "c"), False,
        Expectation(ReportOutcome.RENDERED, marks=(DocumentMark.SECTION_UNAVAILABLE,))))

    cases.append(ScenarioCase(
        "OFF_BOOK",
        HarnessSources([_assessment()], _analyses(), _readings(), drift_readings=True),
        AssessmentScope("b", "c"), False,
        Expectation(ReportOutcome.WITHHELD, withheld_reason=WithheldReason.PROVENANCE_MISMATCH,
                    artifact_expected=False)))

    cases.append(ScenarioCase(
        "REDELIVERY", HarnessSources([_assessment()], _analyses(), _readings()),
        AssessmentScope("b", "c"), False,
        Expectation(ReportOutcome.RENDERED, marks=()),
        presteps=((AssessmentScope("b", "c"), False),)))  # deliver once before

    cases.append(ScenarioCase(
        "MALFORMED", HarnessSources([_assessment()], _analyses(), _readings()),
        AssessmentScope(None, None), False,  # type: ignore[arg-type]
        Expectation(ReportOutcome.WITHHELD, withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
                    artifact_expected=False)))

    cases.append(ScenarioCase(
        "NOT_FOUND", HarnessSources([_assessment()], _analyses(), _readings()),
        AssessmentScope("ghost", "none"), False,
        Expectation(ReportOutcome.WITHHELD, withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
                    artifact_expected=False)))

    # RE_RENDER handled specially (needs two assessment versions in one store) — see run_re_render.
    cases.append(_re_render_case())
    return cases


def _re_render_case() -> ScenarioCase:
    # v3 rendered, then a v4 assessment supersedes it; the v4 render is a fresh current row.
    src = HarnessSources([_assessment(assessment_version=4)], _analyses(), _readings())
    return ScenarioCase(
        "RE_RENDER", src, AssessmentScope("b", "c"), False,
        Expectation(ReportOutcome.RENDERED, marks=()))


def run_case(case: ScenarioCase, store: FakeReportStore | None = None) -> ReportSummary:
    """Drive one scenario through the REAL service. Returns the (final) summary. Never raises."""
    store = store if store is not None else FakeReportStore()
    for scope, historical in case.presteps:
        run_report(scope, sources=case.sources, store=store, config=CONFIG, headlines=HEADLINES,
                   renderer=FakeRenderer(), rendered_at=RENDERED_AT, historical=historical)
    return run_report(case.scope, sources=case.sources, store=store, config=CONFIG,
                      headlines=HEADLINES, renderer=FakeRenderer(), rendered_at=RENDERED_AT,
                      historical=case.historical)


def summary_fingerprint(summary: ReportSummary) -> tuple:
    """A hashable fingerprint of a summary, for determinism comparison."""
    return (
        summary.ok, summary.outcome.value,
        tuple(m.value for m in summary.marks),
        summary.withheld_reason.value if summary.withheld_reason else None,
        summary.artifact_ref,
    )
