"""R102 — CoverageConfig shape (config-level acceptance).

Acceptance (tasks.md R102): constructs; `coverage_floor` is a TODO/NaN sentinel (the minimum
fraction of expected RAN results required to score vs. withhold — a safety number, not guessed);
the completeness-formula params are TODO; `require_standard_present` defaults True (non-physical);
below-floor and at-floor are distinguishable by a pure predicate (no hardcode). FR-6 / FR-6a.
"""
from __future__ import annotations

import math

from agents.risk_reasoning.config.coverage_config import CoverageConfig


def test_constructs_with_defaults():
    c = CoverageConfig()
    # The one non-physical default that is meant to be set: scoring requires the standard present.
    assert c.require_standard_present is True


def test_coverage_floor_is_a_todo_sentinel_by_default():
    # The floor gates score-vs-withhold (FR-6). It is a safety number — unset, not a plausible
    # default a reviewer might mistake for a real engineering decision.
    c = CoverageConfig()
    assert math.isnan(c.coverage_floor)
    assert c.floor_is_todo is True
    assert c.is_fully_configured is False


def test_completeness_params_are_todo_by_default():
    # The data-completeness/confidence formula params (FR-6a) are unset until supplied.
    c = CoverageConfig()
    assert math.isnan(c.completeness_full_fraction)
    assert c.completeness_is_todo is True


def test_supplying_floor_and_completeness_is_fully_configured():
    c = CoverageConfig(coverage_floor=0.6, completeness_full_fraction=1.0)
    assert c.floor_is_todo is False
    assert c.completeness_is_todo is False
    assert c.is_fully_configured is True


def test_meets_floor_is_a_pure_predicate_no_hardcode():
    # at/above floor -> score; below -> withhold. Uses the supplied floor, not a literal.
    c = CoverageConfig(coverage_floor=0.6, completeness_full_fraction=1.0)
    assert c.meets_floor(0.6) is True       # exact floor scores (>=)
    assert c.meets_floor(0.75) is True
    assert c.meets_floor(0.59) is False     # below withholds


def test_meets_floor_when_unset_is_never_true():
    # With the floor still TODO, nothing "meets" it — the agent must not score on an unset floor.
    c = CoverageConfig()
    assert c.meets_floor(1.0) is False
