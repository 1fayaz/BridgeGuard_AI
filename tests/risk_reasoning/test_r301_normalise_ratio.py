"""R301 — normalise_ratio(value, limit, config) -> 0..100 (pure, FR-2).

Acceptance (tasks.md R301): a ratio at the limit, well under, and well over map to hand-checked
0..100 values; missing limit / non-finite -> a structured "not scorable" signal (feeds R303 gap
handling), never NaN-as-score, never raises; uses config params (ratio_at_zero_score /
ratio_at_full_score), not a hardcode.

The map is linear between the two configured bounds, CLAMPED to [0, 100]:
    ratio == ratio_at_zero_score -> 0
    ratio == ratio_at_full_score -> 100
"""
from __future__ import annotations

import math

from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.scorer import normalise_ratio, RatioScore


def _cfg(zero=0.0, full=1.0) -> ScoreConfig:
    # A ratio of 0 -> score 0; a ratio at the limit (1.0) -> score 100.
    return ScoreConfig(
        score_weights_version="rev1",
        ratio_at_zero_score=zero,
        ratio_at_full_score=full,
    )


def test_ratio_at_limit_maps_to_full_score():
    r = normalise_ratio(value=50.0, limit=50.0, config=_cfg())  # ratio 1.0
    assert r.scorable is True
    assert r.ratio == 1.0
    assert r.score == 100.0


def test_ratio_well_under_maps_low():
    r = normalise_ratio(value=10.0, limit=50.0, config=_cfg())  # ratio 0.2
    assert r.scorable is True
    assert r.score == 20.0     # linear 0..1 -> 0..100


def test_ratio_at_zero_bound_maps_to_zero():
    r = normalise_ratio(value=0.0, limit=50.0, config=_cfg())   # ratio 0.0
    assert r.scorable is True
    assert r.score == 0.0


def test_ratio_over_limit_clamps_to_100():
    r = normalise_ratio(value=75.0, limit=50.0, config=_cfg())  # ratio 1.5 -> clamp
    assert r.scorable is True
    assert r.score == 100.0


def test_ratio_below_zero_bound_clamps_to_0():
    # A configured zero-bound above 0 means small ratios still floor at 0, never negative.
    r = normalise_ratio(value=1.0, limit=100.0, config=_cfg(zero=0.2, full=1.0))  # ratio 0.01
    assert r.scorable is True
    assert r.score == 0.0


def test_uses_config_bounds_not_a_hardcode():
    # With zero-bound 0.5 and full-bound 1.0, a ratio of 0.75 sits halfway -> 50.
    r = normalise_ratio(value=75.0, limit=100.0, config=_cfg(zero=0.5, full=1.0))  # ratio 0.75
    assert r.score == 50.0


def test_missing_limit_is_not_scorable_not_a_raise():
    r = normalise_ratio(value=10.0, limit=float("nan"), config=_cfg())
    assert r.scorable is False
    assert r.score is None
    assert r.reason


def test_zero_limit_is_not_scorable():
    # Division by zero must not happen — a zero limit is "not scorable", not inf/NaN.
    r = normalise_ratio(value=10.0, limit=0.0, config=_cfg())
    assert r.scorable is False
    assert r.score is None


def test_non_finite_value_is_not_scorable():
    r = normalise_ratio(value=float("inf"), limit=50.0, config=_cfg())
    assert r.scorable is False
    assert r.score is None


def test_unconfigured_normalisation_is_not_scorable():
    # Bounds still TODO -> cannot score; structured signal, never a guessed number.
    c = ScoreConfig(score_weights_version="v0-unset")  # ratio bounds are NaN
    r = normalise_ratio(value=10.0, limit=50.0, config=c)
    assert r.scorable is False
    assert r.score is None


def test_score_is_never_nan_on_scorable():
    r = normalise_ratio(value=33.0, limit=50.0, config=_cfg())
    assert r.scorable is True
    assert not math.isnan(r.score)
