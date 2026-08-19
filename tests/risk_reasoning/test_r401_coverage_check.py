"""R401 — coverage_check(ran_count, expected_count, standard_present, config) (FR-6).

Acceptance (tasks.md R401): all-RAN + standard present -> score; mostly SKIPPED/ERROR -> withhold
naming the gap; standard missing -> withhold even with full calc coverage; exact-floor boundary
asserted; uses the config floor (TODO fixture), not a hardcode.

This is the gate that decides whether the agent emits a SCORED (possibly degraded) assessment or
WITHHOLDS the score and routes to human review. It never crashes and never guesses (FR-6 /
Principle IV "always return a status").
"""
from __future__ import annotations

from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.coverage import coverage_check


def _cfg(floor=0.6) -> CoverageConfig:
    return CoverageConfig(coverage_floor=floor, completeness_full_fraction=1.0)


def test_full_coverage_with_standard_scores():
    r = coverage_check(ran_count=9, expected_count=9, standard_present=True, config=_cfg())
    assert r.should_score is True
    assert r.ran_fraction == 1.0
    assert r.reason is None


def test_mostly_skipped_withholds_and_names_gap():
    r = coverage_check(ran_count=2, expected_count=9, standard_present=True, config=_cfg())
    assert r.should_score is False
    assert r.ran_fraction < 0.6
    assert r.reason and "coverage" in r.reason.lower()


def test_standard_missing_withholds_even_with_full_coverage():
    # FR-6: scoring requires the applicable standard; full calc coverage cannot substitute.
    r = coverage_check(ran_count=9, expected_count=9, standard_present=False, config=_cfg())
    assert r.should_score is False
    assert r.reason and "standard" in r.reason.lower()


def test_exact_floor_boundary_scores():
    # ran_fraction == floor scores (>=, consistent with CoverageConfig.meets_floor).
    # 6/10 == 0.6 == floor.
    r = coverage_check(ran_count=6, expected_count=10, standard_present=True, config=_cfg(0.6))
    assert r.ran_fraction == 0.6
    assert r.should_score is True


def test_just_below_floor_withholds():
    r = coverage_check(ran_count=5, expected_count=10, standard_present=True, config=_cfg(0.6))
    assert r.ran_fraction == 0.5
    assert r.should_score is False


def test_uses_config_floor_not_a_hardcode():
    # A stricter floor (0.9) withholds an input that a 0.6 floor would have scored.
    inputs = dict(ran_count=7, expected_count=10, standard_present=True)
    assert coverage_check(**inputs, config=_cfg(0.6)).should_score is True
    assert coverage_check(**inputs, config=_cfg(0.9)).should_score is False


def test_unconfigured_floor_withholds_never_scores():
    # With the floor still TODO, the agent must not score on an unset floor (meets_floor=False).
    cfg = CoverageConfig()  # coverage_floor is NaN
    r = coverage_check(ran_count=9, expected_count=9, standard_present=True, config=cfg)
    assert r.should_score is False
    assert r.reason


def test_zero_expected_withholds_no_divide_by_zero():
    # A bridge with no expected calcs cannot be scored — withhold, never crash on /0.
    r = coverage_check(ran_count=0, expected_count=0, standard_present=True, config=_cfg())
    assert r.should_score is False
    assert r.ran_fraction == 0.0
    assert r.reason
