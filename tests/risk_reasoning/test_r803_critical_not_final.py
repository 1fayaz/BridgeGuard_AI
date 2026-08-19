"""R803 — critical-not-final + downstream-holds (FR-11, mandate #3, AC-12).

Acceptance (tasks.md R803): a CRITICAL assessment is emitted as a recommendation with
review_status=PENDING_HUMAN_REVIEW; a simulated downstream consumer REJECTS/HOLDS it as non-final
(does not act); an assessment emitted as CRITICAL + FINAL, or missing the flag, fails the test.

This proves mandate #3 end to end: the agent emits Critical freely (it is a recommendation) but the
not-final mark stops a downstream agent treating it as settled. Pure test over already-built units
(assess_bridge + a stand-in downstream consumer) — no new production code.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agents.risk_reasoning.orchestrator import assess_bridge
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.fake_model import FakeReasoningModel, Scenario
from agents.risk_reasoning.scorer import FactorInput
from agents.risk_reasoning.statuses import Severity, ReviewStatus
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import StandardEntry


# --- a stand-in for a downstream agent (e.g. the Alert Agent) ----------------------------------
class DownstreamConsumer:
    """Models how any downstream agent MUST treat an assessment: it may act on a FINAL verdict,
    but must HOLD a PENDING_HUMAN_REVIEW one until a human clears it (mandate #3)."""

    def consider(self, assessment: RiskAssessment) -> str:
        if assessment.review_status is ReviewStatus.PENDING_HUMAN_REVIEW:
            return "HELD"        # cannot be treated as final on the agent's say-so
        return "ACTED"


@dataclass
class FakeStore:
    rows: list = field(default_factory=list)
    standards: dict = field(default_factory=dict)

    def current_results_for(self, b, c):
        return [r for r in self.rows if r.bridge_id == b and r.cycle_id == c and r.superseded_by is None]

    def baseline_for(self, b, w):
        return []

    def standard_for(self, t):
        return self.standards.get(t)


def _row(rid, value):
    return AnalysisResultRow(
        id=rid, bridge_id="b1", cycle_id="c1", sensor_id=f"s{rid}", calculation="RMS",
        outcome="RAN", reason_code=None, result={"value": value, "limit": 1.0},
        flags={}, source_validated_ids=[rid], superseded_by=None,
    )


def _extractor(results, standard):
    return [FactorInput(r.calculation.lower(), r.id, float(r.result["value"]),
                        float(r.result["limit"])) for r in results if r.outcome == "RAN"]


def _assess(values):
    store = FakeStore(rows=[_row(i + 1, v) for i, v in enumerate(values)],
                      standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})})
    return assess_bridge(
        bridge_id="b1", cycle_id="c1", store=store, bridge_type="girder",
        score_config=ScoreConfig(score_weights_version="rev1", weights=(("rms", 1.0),),
                                 ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
                                 watch_min=25.0, warning_min=50.0, critical_min=75.0),
        coverage_config=CoverageConfig(coverage_floor=0.5, completeness_full_fraction=1.0),
        model=FakeReasoningModel(Scenario.CLEAN), factor_extractor=_extractor,
        expected_calc_count=len(values), model_id="m", model_version="v", trace_id="t",
    )


def test_critical_is_emitted_but_pending_review():
    a = _assess([0.95])                          # -> 95 -> CRITICAL
    assert a.severity is Severity.CRITICAL
    assert a.risk_score == 95                    # emitted freely (it IS a recommendation)
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW


def test_downstream_holds_a_critical_verdict():
    a = _assess([0.95])
    assert DownstreamConsumer().consider(a) == "HELD"   # does NOT act (mandate #3)


def test_downstream_acts_on_a_final_non_critical_verdict():
    a = _assess([0.30])                          # -> 30 -> WATCH -> FINAL
    assert a.severity is Severity.WATCH
    assert a.review_status is ReviewStatus.FINAL
    assert DownstreamConsumer().consider(a) == "ACTED"


def test_critical_plus_final_is_an_invalid_assessment():
    # The dataclass invariant (R202) forbids constructing CRITICAL + FINAL — the failure mode the
    # test guards against literally cannot be emitted.
    with pytest.raises(ValueError):
        RiskAssessment(
            bridge_id="b1", cycle_id="c1", risk_score=95, severity=Severity.CRITICAL,
            recommendation="Recommend closure.", explanation="critical",
            contributing_factors=(), confidence=1.0, data_completeness=1.0,
            review_status=ReviewStatus.FINAL,          # <-- invalid
            source_analysis_ids=(1,), baseline_ref=None, standard_code="IRC:6",
            standard_version="2017", score_weights_version="rev1", model_id="m",
            model_version="v", trace_id="t",
        )


def test_withheld_critical_scope_also_held():
    # If a would-be-critical bridge is withheld (e.g. guardrail fail), it is still held, never acted.
    from agents.risk_reasoning.fake_model import Scenario as Sc
    store = FakeStore(rows=[_row(1, 0.95)],
                      standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})})
    a = assess_bridge(
        bridge_id="b1", cycle_id="c1", store=store, bridge_type="girder",
        score_config=ScoreConfig(score_weights_version="rev1", weights=(("rms", 1.0),),
                                 ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
                                 watch_min=25.0, warning_min=50.0, critical_min=75.0),
        coverage_config=CoverageConfig(coverage_floor=0.5, completeness_full_fraction=1.0),
        model=FakeReasoningModel(Sc.TWO_BAD), factor_extractor=_extractor,
        expected_calc_count=1, model_id="m", model_version="v", trace_id="t",
    )
    assert a.is_withheld is True
    assert DownstreamConsumer().consider(a) == "HELD"
