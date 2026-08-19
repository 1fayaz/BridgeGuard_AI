"""R101 — ScoreConfig shape (config-level acceptance).

Acceptance (tasks.md R101): constructs with all fields; the non-physical audit field
`score_weights_version` is concrete; every SAFETY number (per-factor weights, the ratio→0..100
normalisation params, the band cut-points) is a clearly-flagged TODO/NaN sentinel a reviewer can
see is unset; `is_fully_configured` is False while any safety number is unset. We do NOT invent
safety weights or band boundaries for a safety-critical system (FR-2 / FR-4).
"""
from __future__ import annotations

import math

from agents.risk_reasoning.config.score_config import ScoreConfig


def test_constructs_with_concrete_version_only():
    # Constructible from just the audit version; every safety number defaults to the TODO sentinel.
    c = ScoreConfig(score_weights_version="v0-unset")
    assert c.score_weights_version == "v0-unset"


def test_version_is_concrete_not_a_sentinel():
    # The version stamps WHICH weights were used; it is a non-physical field that is always
    # present (like the SA profile's clock_drift_policy), never a NaN.
    c = ScoreConfig(score_weights_version="2026-06-weights-rev3")
    assert isinstance(c.score_weights_version, str)
    assert c.score_weights_version  # non-empty


def test_every_safety_number_is_a_todo_sentinel_by_default():
    # Weights empty (nothing mapped) and every normalisation / band constant is NaN — a reviewer
    # must SEE they are unset, not silently defaulted to a plausible number.
    c = ScoreConfig(score_weights_version="v0-unset")
    assert c.weights == ()  # no factor weights supplied yet
    safety = [c.ratio_at_zero_score, c.ratio_at_full_score,
              c.watch_min, c.warning_min, c.critical_min]
    assert all(math.isnan(v) for v in safety), "a safety constant was given a non-TODO default"


def test_unconfigured_is_not_fully_configured():
    c = ScoreConfig(score_weights_version="v0-unset")
    assert c.weights_are_todo is True
    assert c.normalisation_is_todo is True
    assert c.bands_are_todo is True
    assert c.is_fully_configured is False


def test_partial_config_is_still_not_fully_configured():
    # Supplying weights + normalisation but leaving the band table TODO must NOT pass.
    c = ScoreConfig(
        score_weights_version="rev1",
        weights=(("vibration", 0.5), ("deflection", 0.5)),
        ratio_at_zero_score=0.0,
        ratio_at_full_score=1.0,
    )
    assert c.weights_are_todo is False
    assert c.normalisation_is_todo is False
    assert c.bands_are_todo is True          # bands still unset
    assert c.is_fully_configured is False


def test_a_nan_weight_value_keeps_it_unconfigured():
    # An explicitly-NaN weight (engineer started but didn't finish) is still TODO.
    c = ScoreConfig(
        score_weights_version="rev1",
        weights=(("vibration", float("nan")),),
        ratio_at_zero_score=0.0,
        ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
    )
    assert c.weights_are_todo is True
    assert c.is_fully_configured is False


def test_fully_supplied_config_is_fully_configured():
    # Once a structural engineer supplies every safety number, the config is usable.
    c = ScoreConfig(
        score_weights_version="2026-06-weights-rev3",
        weights=(("vibration", 0.4), ("deflection", 0.4), ("strain", 0.2)),
        ratio_at_zero_score=0.0,
        ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
    )
    assert c.weights_are_todo is False
    assert c.normalisation_is_todo is False
    assert c.bands_are_todo is False
    assert c.is_fully_configured is True
