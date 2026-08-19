"""R602 — build_legitimate_set(ran_results, score, factors, standard) (pure, FR-7 support).

Acceptance (tasks.md R602): the deterministic score and each factor number are present; an SA
result's RMS / ratio / limit is present; a number from NO input is absent; uses the config match
tolerance (TODO fixture), not a hardcode.

This is the second half of the guardrail's inputs: the set of numbers an explanation is ALLOWED to
cite. The score is in the set by construction (it is computed in code, R302). A membership test
(`contains`) applies the configured tolerance so "48.0" matches a real 48.004, but a fabricated
"48 mm" against a real 50.0 limit does not.
"""
from __future__ import annotations

from agents.risk_reasoning.assessment import ContributingFactor, FactorDirection
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import EngineeringStandard
from agents.risk_reasoning.guardrail import build_legitimate_set


def _factor(name="vibration", sid=1, value=0.42, limit=0.50, ratio=0.84,
            weight=0.4, contribution=33.6) -> ContributingFactor:
    return ContributingFactor(
        factor_name=name, source_analysis_id=sid, value=value, limit=limit, ratio=ratio,
        weight=weight, contribution=contribution, direction=FactorDirection.RAISED,
    )


def _row(rid=1, result=None) -> AnalysisResultRow:
    return AnalysisResultRow(
        id=rid, bridge_id="b1", cycle_id="c1", sensor_id="s1", calculation="RMS",
        outcome="RAN", reason_code=None, result=result or {"rms": 0.42, "ratio": 0.84},
        flags={}, source_validated_ids=[1], superseded_by=None,
    )


def _standard() -> EngineeringStandard:
    return EngineeringStandard(
        available=True, limits={"deflection_ratio": 0.00125, "max_strain": 500.0},
        standard_code="IRC:6", standard_version="2017",
    )


def test_score_is_in_the_set_by_construction():
    s = build_legitimate_set(ran_results=[_row()], score=58, factors=[_factor()],
                             standard=_standard(), tolerance=0.01)
    assert s.contains(58)


def test_factor_numbers_are_present():
    f = _factor(ratio=0.84, weight=0.4, contribution=33.6)
    s = build_legitimate_set(ran_results=[], score=84, factors=[f],
                             standard=None, tolerance=0.01)
    assert s.contains(0.84)      # ratio
    assert s.contains(0.4)       # weight
    assert s.contains(33.6)      # contribution


def test_sa_result_values_are_present():
    s = build_legitimate_set(ran_results=[_row(result={"rms": 0.42, "ratio": 0.84})],
                             score=42, factors=[], standard=None, tolerance=0.01)
    assert s.contains(0.42)
    assert s.contains(0.84)


def test_standard_limits_are_present():
    s = build_legitimate_set(ran_results=[], score=10, factors=[],
                             standard=_standard(), tolerance=0.01)
    assert s.contains(500.0)
    assert s.contains(0.00125)


def test_number_from_no_input_is_absent():
    # 48 appears in NO input -> not legitimate (this is the fabricated-number case R604 exercises).
    s = build_legitimate_set(ran_results=[_row()], score=58, factors=[_factor()],
                             standard=_standard(), tolerance=0.01)
    assert s.contains(48.0) is False


def test_tolerance_allows_rounding_match():
    s = build_legitimate_set(ran_results=[_row(result={"rms": 48.004})],
                             score=10, factors=[], standard=None, tolerance=0.01)
    assert s.contains(48.0) is True     # within 0.01
    assert s.contains(48.5) is False    # outside 0.01


def test_tolerance_is_used_not_hardcoded():
    # A wider tolerance matches what a tight one rejects.
    row = _row(result={"rms": 48.4})
    tight = build_legitimate_set([row], 10, [], None, tolerance=0.01)
    wide = build_legitimate_set([row], 10, [], None, tolerance=0.5)
    assert tight.contains(48.0) is False
    assert wide.contains(48.0) is True


def test_absent_standard_contributes_no_limits():
    s = build_legitimate_set(ran_results=[], score=10, factors=[],
                             standard=None, tolerance=0.01)
    assert s.contains(500.0) is False
