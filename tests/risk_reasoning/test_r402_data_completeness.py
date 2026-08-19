"""R402 — data_completeness(ran_count, expected_count, flagged_count, config) (FR-6a).

Acceptance (tasks.md R402): full coverage -> high completeness; missing/flagged inputs -> reduced
completeness; the value is annotation-only — R302's score is UNCHANGED when only completeness
changes (FR-6a: confidence never moves the score). Deterministic and pure.

Completeness is the present-and-clean fraction of expected inputs:
    completeness = (ran_count - flagged_count) / expected_count      (clamped to [0, 1])
A flagged-but-RAN input (clock_drift / interpolated / rate_mismatch) still counts toward coverage
(R401) but DISCOUNTS confidence here — a result resting on a drifted block is less trustworthy.
"""
from __future__ import annotations

from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.completeness import data_completeness
from agents.risk_reasoning.scorer import score_bridge, FactorInput


def _cfg(full=1.0) -> CoverageConfig:
    return CoverageConfig(coverage_floor=0.5, completeness_full_fraction=full)


def test_full_clean_coverage_is_full_completeness():
    c = data_completeness(ran_count=9, expected_count=9, flagged_count=0, config=_cfg())
    assert c == 1.0


def test_missing_inputs_reduce_completeness():
    c = data_completeness(ran_count=6, expected_count=9, flagged_count=0, config=_cfg())
    assert abs(c - (6 / 9)) < 1e-9
    assert c < 1.0


def test_flagged_inputs_discount_completeness_below_coverage():
    # 9/9 ran but 3 flagged -> completeness counts the 6 clean ones: 6/9.
    c = data_completeness(ran_count=9, expected_count=9, flagged_count=3, config=_cfg())
    assert abs(c - (6 / 9)) < 1e-9


def test_completeness_clamped_to_unit_interval():
    # Defensive: never below 0 even if flagged exceeds ran (shouldn't happen, but no negative).
    c = data_completeness(ran_count=2, expected_count=9, flagged_count=5, config=_cfg())
    assert 0.0 <= c <= 1.0


def test_zero_expected_is_zero_completeness_no_divide_by_zero():
    c = data_completeness(ran_count=0, expected_count=0, flagged_count=0, config=_cfg())
    assert c == 0.0


def test_deterministic_repeatable():
    args = dict(ran_count=7, expected_count=9, flagged_count=1, config=_cfg())
    first = data_completeness(**args)
    for _ in range(5):
        assert data_completeness(**args) == first


def test_completeness_does_not_move_the_score():
    # FR-6a: the score is a pure function of the present factors; completeness only annotates.
    # Same factor inputs but two very different completeness contexts -> identical score.
    score_cfg = ScoreConfig(
        score_weights_version="rev1",
        weights=(("vibration", 0.5), ("deflection", 0.5)),
        ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
    )
    inputs = [
        FactorInput("vibration", 1, 0.80, 1.0),
        FactorInput("deflection", 2, 0.40, 1.0),
    ]
    score = score_bridge(inputs, score_cfg).score

    high = data_completeness(ran_count=9, expected_count=9, flagged_count=0, config=_cfg())
    low = data_completeness(ran_count=3, expected_count=9, flagged_count=2, config=_cfg())
    assert high != low                         # completeness genuinely differs
    # ...but the score is computed without it and is unaffected:
    assert score_bridge(inputs, score_cfg).score == score
