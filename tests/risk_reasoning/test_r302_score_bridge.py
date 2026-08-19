"""R302 — score_bridge(factor_inputs, config) -> score + ContributingFactor list (FR-2, AC-2).

Acceptance (tasks.md R302): a fixed result set yields a hand-checked weighted score and a factor
per scored result; reordering inputs does not change the score (order-independent combine); the
score is reproducible across repeated calls; weights come from config, not hardcoded. The model is
NOT involved — the score is pure code (Principle IV).

Combine semantics (FR-2): each input's value/limit ratio is normalised to 0..100 (R301), weighted
by the factor's config weight, and combined as a weighted average over the SCORABLE factors:
    score = round( sum(w_i * s_i) / sum(w_i) )
A factor's contribution = w_i * s_i; its direction is RAISED/LOWERED/NEUTRAL relative to the
combined score (which factors pulled it up or down — spec scenario "conflicting signals").
Not-scorable inputs (missing limit, etc.) are recorded as gaps, never guessed.
"""
from __future__ import annotations

from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.assessment import FactorDirection
from agents.risk_reasoning.scorer import score_bridge, FactorInput


def _cfg(weights) -> ScoreConfig:
    return ScoreConfig(
        score_weights_version="rev1",
        weights=weights,
        ratio_at_zero_score=0.0,
        ratio_at_full_score=1.0,
    )


def _inp(name, sid, value, limit) -> FactorInput:
    return FactorInput(factor_name=name, source_analysis_id=sid, value=value, limit=limit)


def test_single_factor_score_is_its_normalised_value():
    cfg = _cfg((("vibration", 1.0),))
    inputs = [_inp("vibration", 4101, 0.42, 0.50)]   # ratio 0.84 -> score 84
    r = score_bridge(inputs, cfg)
    assert r.scorable is True
    assert r.score == 84
    assert len(r.factors) == 1
    f = r.factors[0]
    assert f.factor_name == "vibration"
    assert f.source_analysis_id == 4101
    assert abs(f.weight - 1.0) < 1e-9
    assert abs(f.contribution - 84.0) < 1e-9


def test_weighted_average_of_two_factors_hand_checked():
    # vibration: ratio 0.84 -> 84, weight 0.4 ; deflection: ratio 0.40 -> 40, weight 0.6
    # weighted avg = (0.4*84 + 0.6*40) / 1.0 = (33.6 + 24.0) = 57.6 -> round -> 58
    cfg = _cfg((("vibration", 0.4), ("deflection", 0.6)))
    inputs = [_inp("vibration", 1, 0.84, 1.0), _inp("deflection", 2, 0.40, 1.0)]
    r = score_bridge(inputs, cfg)
    assert r.score == 58
    assert {f.factor_name for f in r.factors} == {"vibration", "deflection"}


def test_combine_is_order_independent():
    cfg = _cfg((("vibration", 0.4), ("deflection", 0.6)))
    a = [_inp("vibration", 1, 0.84, 1.0), _inp("deflection", 2, 0.40, 1.0)]
    b = list(reversed(a))
    assert score_bridge(a, cfg).score == score_bridge(b, cfg).score


def test_score_is_reproducible_across_calls():
    cfg = _cfg((("vibration", 0.4), ("deflection", 0.6)))
    inputs = [_inp("vibration", 1, 0.84, 1.0), _inp("deflection", 2, 0.40, 1.0)]
    first = score_bridge(inputs, cfg).score
    for _ in range(5):
        assert score_bridge(inputs, cfg).score == first


def test_direction_reflects_pull_relative_to_combined():
    # combined 58: vibration(84) RAISED, deflection(40) LOWERED.
    cfg = _cfg((("vibration", 0.4), ("deflection", 0.6)))
    inputs = [_inp("vibration", 1, 0.84, 1.0), _inp("deflection", 2, 0.40, 1.0)]
    r = score_bridge(inputs, cfg)
    by_name = {f.factor_name: f for f in r.factors}
    assert by_name["vibration"].direction is FactorDirection.RAISED
    assert by_name["deflection"].direction is FactorDirection.LOWERED


def test_not_scorable_input_is_a_gap_not_a_guess():
    # deflection has no limit -> not scorable -> excluded from score, recorded as a gap.
    cfg = _cfg((("vibration", 0.4), ("deflection", 0.6)))
    inputs = [_inp("vibration", 1, 0.84, 1.0), _inp("deflection", 2, 0.40, float("nan"))]
    r = score_bridge(inputs, cfg)
    assert r.score == 84                      # only vibration scored
    assert len(r.factors) == 1
    assert any("deflection" in g for g in r.gaps)


def test_factor_with_no_configured_weight_is_a_gap():
    # 'strain' is present but unweighted in config -> cannot include it, record a gap.
    cfg = _cfg((("vibration", 1.0),))
    inputs = [_inp("vibration", 1, 0.50, 1.0), _inp("strain", 2, 0.90, 1.0)]
    r = score_bridge(inputs, cfg)
    assert len(r.factors) == 1
    assert r.factors[0].factor_name == "vibration"
    assert any("strain" in g for g in r.gaps)


def test_no_scorable_factors_yields_no_score():
    cfg = _cfg((("vibration", 0.4),))
    inputs = [_inp("vibration", 1, 0.84, float("nan"))]   # not scorable
    r = score_bridge(inputs, cfg)
    assert r.scorable is False
    assert r.score is None


def test_unconfigured_weights_yields_no_score():
    cfg = ScoreConfig(score_weights_version="v0-unset",
                      ratio_at_zero_score=0.0, ratio_at_full_score=1.0)  # weights empty
    inputs = [_inp("vibration", 1, 0.84, 1.0)]
    r = score_bridge(inputs, cfg)
    assert r.scorable is False
    assert r.score is None


def test_score_is_an_integer_in_range():
    cfg = _cfg((("vibration", 0.4), ("deflection", 0.6)))
    inputs = [_inp("vibration", 1, 0.84, 1.0), _inp("deflection", 2, 0.40, 1.0)]
    s = score_bridge(inputs, cfg).score
    assert isinstance(s, int)
    assert 0 <= s <= 100
