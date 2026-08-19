"""R903 — reproducibility from pinned inputs (FR-10, AC-10) [DB-DEP].

Acceptance (tasks.md R903): an assessment is re-derivable from its recorded source_analysis_ids +
standard_code/version + score_weights_version even after a standard version is bumped or an SA
result is superseded; a re-assessment for the same (bridge, cycle) SUPERSEDES (appends + links old),
never overwrites. AC-10.

Pure test over persistence + the deterministic scorer: the score is recomputed from the SAME pinned
factor inputs and must equal the stored value, regardless of what the live sources say NOW.
"""
from __future__ import annotations

from agents.risk_reasoning.persistence import persist_assessment
from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.statuses import Severity, ReviewStatus
from agents.risk_reasoning.scorer import score_bridge, FactorInput
from agents.risk_reasoning.config.score_config import ScoreConfig


def _cfg(version="rev1") -> ScoreConfig:
    return ScoreConfig(
        score_weights_version=version, weights=(("rms", 0.5), ("threshold", 0.5)),
        ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
    )


def _pinned_inputs():
    # The exact factor inputs the original assessment used (as would be reconstructed from the
    # recorded source_analysis_ids + standard limits).
    return [FactorInput("rms", 1, 0.60, 1.0), FactorInput("threshold", 2, 0.40, 1.0)]


def _assessment_from(score, cfg) -> RiskAssessment:
    return RiskAssessment(
        bridge_id="b1", cycle_id="c1", risk_score=score, severity=Severity.WARNING,
        recommendation="monitor", explanation=f"score {score} from pinned inputs",
        contributing_factors=(), confidence=1.0, data_completeness=1.0,
        review_status=ReviewStatus.FINAL, source_analysis_ids=(1, 2),
        baseline_ref=None, standard_code="IRC:6", standard_version="2017",
        score_weights_version=cfg.score_weights_version, model_id="m", model_version="v",
        trace_id="t1",
    )


def test_score_recomputes_identically_from_pinned_inputs():
    cfg = _cfg()
    original = score_bridge(_pinned_inputs(), cfg).score        # 50
    store = FakeRiskStore()
    persist_assessment(store, _assessment_from(original, cfg))

    # Later: recompute from the SAME pinned inputs + the SAME weights version -> identical score.
    recomputed = score_bridge(_pinned_inputs(), cfg).score
    assert recomputed == store.current("b1", "c1").risk_score == 50


def test_recorded_provenance_identifies_exactly_what_to_reload():
    cfg = _cfg()
    store = FakeRiskStore()
    persist_assessment(store, _assessment_from(50, cfg))
    row = store.current("b1", "c1")
    # The row pins WHICH inputs + WHICH weights + WHICH standard version were used.
    assert row.source_analysis_ids == (1, 2)
    assert row.standard_version == "2017"
    assert row.score_weights_version == "rev1"


def test_standard_version_bump_does_not_change_a_pinned_assessment():
    # The live standard is later revised to 2020, but the stored assessment still records 2017 and
    # its score is unchanged — it is pinned at decision time.
    cfg = _cfg()
    store = FakeRiskStore()
    persist_assessment(store, _assessment_from(50, cfg))

    # A NEW assessment under the revised standard supersedes; the OLD one keeps its pinned version.
    revised = RiskAssessment(
        bridge_id="b1", cycle_id="c1", risk_score=55, severity=Severity.WARNING,
        recommendation="monitor", explanation="score 55 under revised standard",
        contributing_factors=(), confidence=1.0, data_completeness=1.0,
        review_status=ReviewStatus.FINAL, source_analysis_ids=(1, 2),
        baseline_ref=None, standard_code="IRC:6", standard_version="2020",
        score_weights_version="rev1", model_id="m", model_version="v", trace_id="t2",
    )
    persist_assessment(store, revised)

    rows = sorted(store.rows, key=lambda sa: sa.id)
    assert rows[0].assessment.standard_version == "2017"   # old, pinned, unchanged
    assert rows[0].assessment.risk_score == 50
    assert rows[0].superseded_by == rows[1].id             # linked, not overwritten
    assert rows[1].assessment.standard_version == "2020"   # new current
    assert store.current("b1", "c1").risk_score == 55


def test_reassessment_supersedes_never_overwrites():
    cfg = _cfg()
    store = FakeRiskStore()
    persist_assessment(store, _assessment_from(50, cfg))
    persist_assessment(store, _assessment_from(70, cfg))
    # History preserved: two rows, old superseded, current is the new one.
    assert len(store.rows) == 2
    assert store.current("b1", "c1").risk_score == 70
    old = min(store.rows, key=lambda sa: sa.id)
    assert old.assessment.risk_score == 50                 # original verdict intact
    assert old.superseded_by is not None
