"""R603 — provenance_guardrail(draft, legitimate_set) decision function (FR-7, AC-7).

Acceptance (tasks.md R603): a draft whose every number traces -> pass; a draft with an invented
"deflection was 48 mm" -> tripwire naming the offending number; a number within rounding tolerance
of a real value -> pass; tolerance comes from config. Positive AND negative cases (AC-7).

This is the pure decision at the heart of mandate #2. The regenerate-once-then-fail-closed control
flow around it is R604; here we prove the tripwire itself fires on a fabricated number and names it.
"""
from __future__ import annotations

from agents.risk_reasoning.guardrail import (
    provenance_guardrail,
    build_legitimate_set,
    LegitimateSet,
)
from agents.risk_reasoning.assessment import ContributingFactor, FactorDirection
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import EngineeringStandard


def _legit(tolerance=0.01) -> LegitimateSet:
    # Real inputs: an RMS of 0.42 / ratio 0.84, a score of 58, a standard limit 50.0.
    row = AnalysisResultRow(
        id=1, bridge_id="b1", cycle_id="c1", sensor_id="s1", calculation="RMS",
        outcome="RAN", reason_code=None, result={"rms": 0.42, "ratio": 0.84},
        flags={}, source_validated_ids=[1], superseded_by=None,
    )
    factor = ContributingFactor("vibration", 1, 0.42, 0.50, 0.84, 0.4, 33.6,
                                FactorDirection.RAISED)
    std = EngineeringStandard(True, {"max_deflection_mm": 50.0}, "IRC:6", "2017")
    return build_legitimate_set([row], score=58, factors=[factor], standard=std,
                                tolerance=tolerance)


def test_clean_draft_every_number_traces_passes():
    draft = "The score is 58. Vibration reached a ratio of 0.84 against a 50.0 mm limit."
    r = provenance_guardrail(draft, _legit())
    assert r.passed is True
    assert r.offending == ()


def test_fabricated_number_tripwires_and_is_named():
    # "48 mm" appears in NO input (real limit is 50.0) -> tripwire (mandate #2 negative case).
    draft = "Deflection was 48 mm, comfortably under the limit."
    r = provenance_guardrail(draft, _legit())
    assert r.passed is False
    assert any("48" in tok.raw for tok in r.offending)   # the offending number is named


def test_number_within_tolerance_passes():
    # 0.84 is legitimate; "0.84" cited exactly passes; a rounded 58 also passes.
    draft = "Score 58 with ratio 0.84."
    assert provenance_guardrail(draft, _legit()).passed is True


def test_number_just_outside_tolerance_tripwires():
    draft = "The ratio was 0.90."          # no 0.90 in inputs, beyond 0.01 of 0.84
    r = provenance_guardrail(draft, _legit())
    assert r.passed is False
    assert any("0.90" in tok.raw for tok in r.offending)


def test_prose_with_no_numbers_passes_vacuously():
    draft = "The bridge is stable with no notable change since the last assessment."
    r = provenance_guardrail(draft, _legit())
    assert r.passed is True


def test_multiple_fabricated_numbers_all_named():
    draft = "Deflection 48 mm and strain 999 both concerning."
    r = provenance_guardrail(draft, _legit())
    assert r.passed is False
    raws = " ".join(tok.raw for tok in r.offending)
    assert "48" in raws and "999" in raws


def test_tolerance_from_config_widens_acceptance():
    # A wider tolerance accepts a number a tight one rejects (tolerance is not hardcoded).
    draft = "Ratio around 0.85."            # 0.85 vs real 0.84
    assert provenance_guardrail(draft, _legit(tolerance=0.001)).passed is False
    assert provenance_guardrail(draft, _legit(tolerance=0.02)).passed is True


def test_one_bad_number_among_good_ones_still_tripwires():
    # Good: 58, 0.84. Bad: 48. The presence of good numbers does not excuse the bad one.
    draft = "Score 58, ratio 0.84, but deflection 48 mm."
    r = provenance_guardrail(draft, _legit())
    assert r.passed is False
    assert any("48" in tok.raw for tok in r.offending)
