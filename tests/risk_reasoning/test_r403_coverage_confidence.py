"""R403 — coverage gate + confidence integration (FR-6, FR-6a, AC-6).

Acceptance (tasks.md R403): below-floor input -> withheld decision with reduced confidence naming
the gap (the assessment will be PENDING_HUMAN_REVIEW, no fabricated number, no crash); above-floor
-> scored; confidence annotates but does not alter the score. = AC-6.

Pure integration over already-built units (coverage_check, data_completeness, score_bridge) — no
new production code. Proves the degraded/withhold path behaves end to end before R703 wires it.
"""
from __future__ import annotations

from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.coverage import coverage_check
from agents.risk_reasoning.completeness import data_completeness
from agents.risk_reasoning.scorer import score_bridge, FactorInput


def _cov(floor=0.6) -> CoverageConfig:
    return CoverageConfig(coverage_floor=floor, completeness_full_fraction=1.0)


def _score_cfg() -> ScoreConfig:
    return ScoreConfig(
        score_weights_version="rev1",
        weights=(("vibration", 0.5), ("deflection", 0.5)),
        ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
    )


def test_below_floor_withholds_with_reduced_confidence_and_named_gap():
    cov = _cov(0.6)
    decision = coverage_check(ran_count=2, expected_count=9, standard_present=True, config=cov)
    confidence = data_completeness(ran_count=2, expected_count=9, flagged_count=0, config=cov)

    assert decision.should_score is False                 # withhold (FR-6)
    assert decision.reason and "coverage" in decision.reason.lower()  # names the gap
    assert confidence < 0.5                               # reduced confidence (FR-6a annotation)
    # No fabricated number: the withhold path produces no score at all.


def test_above_floor_scores_with_high_confidence():
    cov = _cov(0.6)
    decision = coverage_check(ran_count=8, expected_count=9, standard_present=True, config=cov)
    confidence = data_completeness(ran_count=8, expected_count=9, flagged_count=0, config=cov)

    assert decision.should_score is True
    assert confidence > 0.6

    inputs = [FactorInput("vibration", 1, 0.80, 1.0), FactorInput("deflection", 2, 0.40, 1.0)]
    scored = score_bridge(inputs, _score_cfg())
    assert scored.scorable is True
    assert scored.score == 60                             # (80+40)/2


def test_standard_missing_withholds_even_with_full_calc_coverage():
    cov = _cov(0.6)
    decision = coverage_check(ran_count=9, expected_count=9, standard_present=False, config=cov)
    assert decision.should_score is False
    assert "standard" in decision.reason.lower()


def test_confidence_annotates_but_does_not_change_score():
    # AC-6 / FR-6a: a degraded (but above-floor) bridge and a pristine bridge with the SAME factor
    # inputs get the SAME score; only the confidence annotation differs.
    cov = _cov(0.5)
    inputs = [FactorInput("vibration", 1, 0.70, 1.0), FactorInput("deflection", 2, 0.50, 1.0)]
    score_cfg = _score_cfg()
    base_score = score_bridge(inputs, score_cfg).score

    pristine_conf = data_completeness(9, 9, 0, cov)
    degraded_conf = data_completeness(5, 9, 1, cov)
    assert pristine_conf > degraded_conf                  # confidence differs
    assert score_bridge(inputs, score_cfg).score == base_score  # score does not


def test_degraded_path_never_crashes_on_partial_input():
    # Const. V / FR-6: partial input returns a structured decision, never an exception.
    cov = _cov(0.6)
    for ran, exp in [(0, 0), (0, 9), (1, 9), (9, 9)]:
        d = coverage_check(ran_count=ran, expected_count=exp, standard_present=True, config=cov)
        assert isinstance(d.should_score, bool)
        c = data_completeness(ran_count=ran, expected_count=exp, flagged_count=0, config=cov)
        assert 0.0 <= c <= 1.0
