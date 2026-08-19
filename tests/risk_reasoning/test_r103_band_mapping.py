"""R103 — Band mapping `severity_for(score, config)` (FR-4) + near-boundary annotation.

Acceptance (tasks.md R103): pure function 0..100 -> exactly one of SAFE | WATCH | WARNING |
CRITICAL via the config band table; a boundary value maps deterministically to one side; a
near-boundary score sets a `near_boundary` flag WITHOUT changing the band; unset thresholds ->
structured "not configured", never a guessed band. FR-4 + Edge "borderline".

The band itself comes from the fixed config cut-points (the model never chooses a band). The
near-boundary margin is annotation-only config (band_near_margin); when unset, no score is ever
flagged near (we do not guess "how close is near" for a safety output).
"""
from __future__ import annotations

import pytest

from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.statuses import Severity
from agents.risk_reasoning.band import severity_for, BandNotConfigured


def _bands(near_margin=float("nan")) -> ScoreConfig:
    return ScoreConfig(
        score_weights_version="rev1",
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
        band_near_margin=near_margin,
    )


def test_each_band_maps_correctly():
    c = _bands()
    assert severity_for(10.0, c).severity is Severity.SAFE
    assert severity_for(30.0, c).severity is Severity.WATCH
    assert severity_for(60.0, c).severity is Severity.WARNING
    assert severity_for(90.0, c).severity is Severity.CRITICAL


def test_boundary_value_maps_deterministically_to_upper_side():
    # score == cut-point belongs to the higher band (>=), matching CoverageConfig.meets_floor.
    c = _bands()
    assert severity_for(25.0, c).severity is Severity.WATCH
    assert severity_for(50.0, c).severity is Severity.WARNING
    assert severity_for(75.0, c).severity is Severity.CRITICAL


def test_extremes_map_to_safe_and_critical():
    c = _bands()
    assert severity_for(0.0, c).severity is Severity.SAFE
    assert severity_for(100.0, c).severity is Severity.CRITICAL


def test_unconfigured_bands_raise_not_configured_never_guess():
    # Bands still TODO -> structured "not configured"; the agent must NOT invent a band.
    c = ScoreConfig(score_weights_version="v0-unset")  # band cut-points are NaN
    with pytest.raises(BandNotConfigured):
        severity_for(60.0, c)


def test_near_boundary_flag_set_without_changing_band():
    # margin=3: a score 2 below the WARNING cut-point is WATCH but flagged near the boundary.
    c = _bands(near_margin=3.0)
    r = severity_for(48.0, c)              # WARNING starts at 50.0; 48 is within 3
    assert r.severity is Severity.WATCH    # band UNCHANGED
    assert r.near_boundary is True


def test_score_comfortably_inside_band_is_not_near():
    c = _bands(near_margin=3.0)
    r = severity_for(37.0, c)              # mid-WATCH (25..50), far from both edges
    assert r.severity is Severity.WATCH
    assert r.near_boundary is False


def test_near_boundary_unset_margin_never_flags():
    # With band_near_margin still TODO, no score is flagged near — we do not guess "how close".
    c = _bands()                           # near_margin is NaN
    r = severity_for(49.99, c)
    assert r.severity is Severity.WATCH
    assert r.near_boundary is False


def test_near_boundary_does_not_gate_full_configuration():
    # band_near_margin is annotation-only (like confidence): leaving it TODO must NOT make an
    # otherwise-complete config report unconfigured.
    c = ScoreConfig(
        score_weights_version="rev1",
        weights=(("vibration", 1.0),),
        ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
    )
    assert c.is_fully_configured is True
