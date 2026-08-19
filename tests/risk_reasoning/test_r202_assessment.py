"""R202 — output payload shape (typed assessment + contributing factors).

Acceptance (tasks.md R202): constructs typed; a withheld assessment is representable with
risk_score=None, severity=None, a populated explanation, and review_status=PENDING_HUMAN_REVIEW;
a scored assessment carries score + severity + >=1 factor; each factor carries its number's
provenance (source_analysis_id, ratio, weight, direction). FR-1 (score+WHY inseparable), FR-9
(provenance), FR-6/FR-7 (withheld shape).
"""
from __future__ import annotations

import pytest

from agents.risk_reasoning.statuses import Severity, ReviewStatus
from agents.risk_reasoning.assessment import (
    ContributingFactor,
    RiskAssessment,
    FactorDirection,
)


def _factor() -> ContributingFactor:
    return ContributingFactor(
        factor_name="vibration",
        source_analysis_id=4101,
        value=0.42,
        limit=0.50,
        ratio=0.84,
        weight=0.4,
        contribution=33.6,
        direction=FactorDirection.RAISED,
    )


def test_contributing_factor_constructs_typed_with_provenance():
    f = _factor()
    assert f.factor_name == "vibration"
    assert f.source_analysis_id == 4101      # provenance: which SA result (FR-9)
    assert f.ratio == 0.84
    assert f.weight == 0.4
    assert f.direction is FactorDirection.RAISED


def test_scored_assessment_carries_score_severity_and_a_factor():
    a = RiskAssessment(
        bridge_id="bridge-7",
        cycle_id="cycle-2026-06-30T10:00",
        risk_score=72,
        severity=Severity.WARNING,
        recommendation="Increase inspection frequency; no closure required.",
        explanation="Vibration rose to 84% of limit, the dominant factor...",
        contributing_factors=(_factor(),),
        confidence=0.9,
        data_completeness=0.95,
        review_status=ReviewStatus.FINAL,
        source_analysis_ids=(4101, 4102),
        baseline_ref="baseline-bridge-7-30d",
        standard_code="IRC:6",
        standard_version="2017",
        score_weights_version="2026-06-weights-rev3",
        model_id="frontier-model-x",
        model_version="2026-05",
        trace_id="trace-abc123",
    )
    assert a.risk_score == 72
    assert a.severity is Severity.WARNING
    assert len(a.contributing_factors) == 1
    assert a.is_withheld is False


def test_withheld_assessment_is_representable():
    # FR-6/FR-7: score withheld, no band, but a populated explanation + pending review.
    a = RiskAssessment(
        bridge_id="bridge-7",
        cycle_id="cycle-2026-06-30T10:00",
        risk_score=None,
        severity=None,
        recommendation="Insufficient data to score; routed to human review.",
        explanation="Only 2 of 9 expected calculations ran; coverage below floor...",
        contributing_factors=(),
        confidence=0.2,
        data_completeness=0.22,
        review_status=ReviewStatus.PENDING_HUMAN_REVIEW,
        source_analysis_ids=(4101, 4102),
        baseline_ref=None,
        standard_code=None,
        standard_version=None,
        score_weights_version="2026-06-weights-rev3",
        model_id="frontier-model-x",
        model_version="2026-05",
        trace_id="trace-def456",
    )
    assert a.risk_score is None
    assert a.severity is None
    assert a.explanation                       # WHY present even when withheld
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW
    assert a.is_withheld is True


def test_bare_score_without_explanation_is_rejected():
    # FR-1 / mandate #1: a score with no explanation is an invalid output.
    with pytest.raises(ValueError):
        RiskAssessment(
            bridge_id="bridge-7",
            cycle_id="c1",
            risk_score=72,
            severity=Severity.WARNING,
            recommendation="...",
            explanation="",                    # empty -> invalid
            contributing_factors=(_factor(),),
            confidence=0.9,
            data_completeness=0.95,
            review_status=ReviewStatus.FINAL,
            source_analysis_ids=(4101,),
            baseline_ref=None,
            standard_code="IRC:6",
            standard_version="2017",
            score_weights_version="rev3",
            model_id="m",
            model_version="v",
            trace_id="t",
        )


def test_scored_assessment_requires_a_severity():
    # FR-1: a numeric score must carry its band; a score with severity=None is not "withheld",
    # it is an incoherent emitted score -> rejected.
    with pytest.raises(ValueError):
        RiskAssessment(
            bridge_id="bridge-7",
            cycle_id="c1",
            risk_score=72,
            severity=None,                      # score present but no band -> invalid
            recommendation="...",
            explanation="something",
            contributing_factors=(_factor(),),
            confidence=0.9,
            data_completeness=0.95,
            review_status=ReviewStatus.FINAL,
            source_analysis_ids=(4101,),
            baseline_ref=None,
            standard_code="IRC:6",
            standard_version="2017",
            score_weights_version="rev3",
            model_id="m",
            model_version="v",
            trace_id="t",
        )


def test_critical_must_be_pending_human_review():
    # FR-11 / mandate #3: a CRITICAL assessment emitted as FINAL is an invalid output.
    with pytest.raises(ValueError):
        RiskAssessment(
            bridge_id="bridge-7",
            cycle_id="c1",
            risk_score=92,
            severity=Severity.CRITICAL,
            recommendation="Recommend closure.",
            explanation="Multiple factors crossed critical...",
            contributing_factors=(_factor(),),
            confidence=0.9,
            data_completeness=0.95,
            review_status=ReviewStatus.FINAL,   # CRITICAL + FINAL -> invalid
            source_analysis_ids=(4101,),
            baseline_ref=None,
            standard_code="IRC:6",
            standard_version="2017",
            score_weights_version="rev3",
            model_id="m",
            model_version="v",
            trace_id="t",
        )


def test_assessment_is_frozen():
    a = RiskAssessment(
        bridge_id="b", cycle_id="c", risk_score=10, severity=Severity.SAFE,
        recommendation="routine", explanation="all nominal",
        contributing_factors=(_factor(),), confidence=1.0, data_completeness=1.0,
        review_status=ReviewStatus.FINAL, source_analysis_ids=(4101,),
        baseline_ref=None, standard_code="IRC:6", standard_version="2017",
        score_weights_version="rev3", model_id="m", model_version="v", trace_id="t",
    )
    with pytest.raises(Exception):
        a.risk_score = 99  # type: ignore[misc]
