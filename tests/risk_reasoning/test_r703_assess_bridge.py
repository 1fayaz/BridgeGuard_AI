"""R703 — assess_bridge orchestrator (FR-1, FR-3a, FR-8, AC-1, AC-11) [LLM-DEP fake model].

Acceptance (tasks.md R703): a normal scenario -> scored assessment with score + explanation +
factors + review_status; exactly one assessment per (bridge, cycle); the score is the deterministic
value (not the model's); an injected tool/model exception -> a structured withheld/error
assessment, nothing raises out (FR-8).

Wires: three tool fetches -> coverage gate -> deterministic score + band -> model drafts
explanation -> guardrail loop (regenerate-once-then-fail-closed) -> review_status -> RiskAssessment.
The model is the R702 fake; the score is always pure code (R302).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.risk_reasoning.orchestrator import assess_bridge
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.fake_model import FakeReasoningModel, Scenario
from agents.risk_reasoning.statuses import Severity, ReviewStatus
from agents.risk_reasoning.scorer import FactorInput
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.historical_baseline import BaselinePoint
from agents.risk_reasoning.tools.engineering_standard import StandardEntry


# --- a combined store implementing the three read ports (R901 is the persistent version) ------
@dataclass
class FakeStore:
    rows: list[AnalysisResultRow] = field(default_factory=list)
    points: list[BaselinePoint] = field(default_factory=list)
    standards: dict[str, StandardEntry] = field(default_factory=dict)
    raise_on_results: bool = False

    def current_results_for(self, bridge_id, cycle_id):
        if self.raise_on_results:
            raise RuntimeError("injected source failure")
        return [r for r in self.rows
                if r.bridge_id == bridge_id and r.cycle_id == cycle_id and r.superseded_by is None]

    def baseline_for(self, bridge_id, window):
        return [p for p in self.points if p.bridge_id == bridge_id]

    def standard_for(self, bridge_type):
        return self.standards.get(bridge_type)


def _row(rid, calc, value, outcome="RAN"):
    return AnalysisResultRow(
        id=rid, bridge_id="b1", cycle_id="c1", sensor_id=f"s{rid}", calculation=calc,
        outcome=outcome, reason_code=None if outcome == "RAN" else "NO_CHANGE",
        result={"value": value, "limit": 1.0}, flags={}, source_validated_ids=[rid],
        superseded_by=None,
    )


def _extractor(results, standard):
    # Domain seam: turn each RAN result into a FactorInput (value/limit from its payload).
    out = []
    for r in results:
        if r.outcome != "RAN":
            continue
        out.append(FactorInput(
            factor_name=r.calculation.lower(),
            source_analysis_id=r.id,
            value=float(r.result["value"]),
            limit=float(r.result["limit"]),
        ))
    return out


def _score_cfg():
    return ScoreConfig(
        score_weights_version="rev1",
        weights=(("rms", 0.5), ("threshold", 0.5)),
        ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
        band_near_margin=3.0,
    )


def _cov_cfg():
    return CoverageConfig(coverage_floor=0.5, completeness_full_fraction=1.0)


def _store_healthy():
    return FakeStore(
        rows=[_row(1, "RMS", 0.60), _row(2, "THRESHOLD", 0.40)],
        points=[BaselinePoint("b1", "2026-06-01", 45)],
        standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})},
    )


def _assess(store, model, **over):
    kw = dict(
        bridge_id="b1", cycle_id="c1", store=store, bridge_type="girder",
        score_config=_score_cfg(), coverage_config=_cov_cfg(), model=model,
        factor_extractor=_extractor, expected_calc_count=2,
        model_id="frontier-x", model_version="2026-05", trace_id="t1",
    )
    kw.update(over)
    return assess_bridge(**kw)


def test_normal_scenario_scored_with_explanation_and_factors():
    a = _assess(_store_healthy(), FakeReasoningModel(Scenario.CLEAN))
    assert a.risk_score is not None
    assert a.severity is not None
    assert a.explanation
    assert len(a.contributing_factors) == 2
    assert a.review_status in (ReviewStatus.FINAL, ReviewStatus.PENDING_HUMAN_REVIEW)


def test_score_is_the_deterministic_value_not_the_models():
    # (0.60 + 0.40)/... normalised: 60 and 40 -> weighted avg 50 -> WARNING.
    a = _assess(_store_healthy(), FakeReasoningModel(Scenario.CLEAN))
    assert a.risk_score == 50
    assert a.severity is Severity.WARNING


def test_provenance_and_model_audit_fields_recorded():
    a = _assess(_store_healthy(), FakeReasoningModel(Scenario.CLEAN))
    assert set(a.source_analysis_ids) == {1, 2}
    assert a.standard_code == "IRC:6"
    assert a.standard_version == "2017"
    assert a.model_id == "frontier-x"
    assert a.trace_id == "t1"


def test_below_coverage_floor_withholds():
    store = FakeStore(
        rows=[_row(1, "RMS", 0.60), _row(2, "THRESHOLD", 0.40, outcome="SKIPPED")],
        standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})},
    )
    # only 1 of 4 expected ran -> below 0.5 floor.
    a = _assess(store, FakeReasoningModel(Scenario.CLEAN), expected_calc_count=4)
    assert a.is_withheld is True
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW


def test_missing_standard_withholds():
    store = FakeStore(rows=[_row(1, "RMS", 0.60), _row(2, "THRESHOLD", 0.40)], standards={})
    a = _assess(store, FakeReasoningModel(Scenario.CLEAN))
    assert a.is_withheld is True
    assert "standard" in a.explanation.lower()


def test_guardrail_two_bad_drafts_fail_closed_to_withheld():
    a = _assess(_store_healthy(), FakeReasoningModel(Scenario.TWO_BAD))
    assert a.is_withheld is True
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW
    assert "48" in a.explanation          # names the untraceable number


def test_guardrail_one_bad_then_clean_still_scores():
    a = _assess(_store_healthy(), FakeReasoningModel(Scenario.ONE_BAD_THEN_CLEAN))
    assert a.is_withheld is False         # recovered on the single regeneration
    assert a.risk_score == 50


def test_injected_source_exception_yields_structured_withheld_never_raises():
    store = _store_healthy()
    store.raise_on_results = True
    a = _assess(store, FakeReasoningModel(Scenario.CLEAN))   # must NOT raise
    assert a.is_withheld is True
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW


def test_critical_score_is_pending_human_review():
    # High values -> CRITICAL -> must be PENDING_HUMAN_REVIEW (FR-11).
    store = FakeStore(
        rows=[_row(1, "RMS", 0.95), _row(2, "THRESHOLD", 0.90)],
        standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})},
    )
    a = _assess(store, FakeReasoningModel(Scenario.CLEAN))
    assert a.severity is Severity.CRITICAL
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW


def test_exactly_one_assessment_returned():
    a = _assess(_store_healthy(), FakeReasoningModel(Scenario.CLEAN))
    # Single object, scoped to the one bridge+cycle.
    assert a.bridge_id == "b1" and a.cycle_id == "c1"
