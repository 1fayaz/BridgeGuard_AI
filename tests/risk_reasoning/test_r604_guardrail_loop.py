"""R604 — regenerate-once-then-fail-closed loop (FR-7, AC-7, mandate #2).

Acceptance (tasks.md R604): drives the loop with a fake model:
  (i)  clean draft -> emitted;
  (ii) one bad draft then a clean regenerate -> emitted after EXACTLY one regeneration;
  (iii) two bad drafts -> FAIL CLOSED to a withheld assessment (risk_score=None,
        review_status=PENDING_HUMAN_REVIEW, explanation naming the failure), RISK_GUARDRAIL_FAIL
        auditable; the untraceable number is NEVER emitted.

This is the safety hinge of mandate #2 — the fail-closed path is exercised by a test that feeds a
DELIBERATELY FABRICATED number, not assumed to work. The reusable FakeReasoningModel is R702; here
a minimal inline draft-generator stub proves the loop mechanism in isolation.
"""
from __future__ import annotations

from agents.risk_reasoning.guardrail import (
    run_guardrail_loop,
    build_legitimate_set,
)
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.statuses import ReviewStatus
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow


def _legit():
    row = AnalysisResultRow(
        id=1, bridge_id="b1", cycle_id="c1", sensor_id="s1", calculation="RMS",
        outcome="RAN", reason_code=None, result={"rms": 0.42, "ratio": 0.84},
        flags={}, source_validated_ids=[1], superseded_by=None,
    )
    return build_legitimate_set([row], score=58, factors=[], standard=None, tolerance=0.01)


CLEAN = "The score is 58 with a ratio of 0.84."
BAD = "Deflection was 48 mm, beyond the limit."   # 48 traces to NO input -> tripwire


def _stub(*drafts_by_attempt):
    """A draft generator returning a scripted draft per attempt index; records the calls."""
    calls = []

    def generate(attempt: int) -> str:
        calls.append(attempt)
        return drafts_by_attempt[attempt]

    generate.calls = calls  # type: ignore[attr-defined]
    return generate


def test_clean_draft_is_emitted_without_regeneration():
    gen = _stub(CLEAN)
    r = run_guardrail_loop(gen, _legit())
    assert r.emitted is True
    assert r.failed_closed is False
    assert r.draft == CLEAN
    assert r.attempts == 1               # no regeneration needed
    assert gen.calls == [0]


def test_one_bad_then_clean_emits_after_exactly_one_regeneration():
    gen = _stub(BAD, CLEAN)
    r = run_guardrail_loop(gen, _legit())
    assert r.emitted is True
    assert r.failed_closed is False
    assert r.draft == CLEAN
    assert r.attempts == 2               # exactly one regeneration
    assert gen.calls == [0, 1]


def test_two_bad_drafts_fail_closed_and_never_emit_the_bad_number():
    gen = _stub(BAD, BAD)
    r = run_guardrail_loop(gen, _legit())
    assert r.emitted is False
    assert r.failed_closed is True
    assert r.draft is None               # the untraceable draft is NEVER emitted
    assert r.attempts == 2               # tried once + regenerated once, then stopped
    assert any("48" in tok.raw for tok in r.offending)   # names the offending number


def test_does_not_regenerate_more_than_once():
    # Even if a third clean draft exists, the loop must stop after one regeneration (bounded).
    gen = _stub(BAD, BAD, CLEAN)
    r = run_guardrail_loop(gen, _legit())
    assert r.failed_closed is True
    assert r.attempts == 2
    assert gen.calls == [0, 1]           # the third draft is never requested


def test_fail_closed_builds_a_valid_withheld_assessment():
    # The fail-closed result must feed a legitimate withheld RiskAssessment (R202 invariants):
    # score withheld, no band, PENDING_HUMAN_REVIEW, explanation naming the failure.
    gen = _stub(BAD, BAD)
    r = run_guardrail_loop(gen, _legit())
    assert r.failed_closed is True

    offending_desc = ", ".join(tok.raw for tok in r.offending)
    withheld = RiskAssessment(
        bridge_id="b1", cycle_id="c1",
        risk_score=None, severity=None,
        recommendation="Score withheld pending human review.",
        explanation=(
            "Numeric-provenance guardrail failed closed after one regeneration: "
            f"the explanation cited untraceable number(s) {offending_desc}."
        ),
        contributing_factors=(),
        confidence=0.0, data_completeness=0.0,
        review_status=ReviewStatus.PENDING_HUMAN_REVIEW,
        source_analysis_ids=(1,),
        baseline_ref=None, standard_code=None, standard_version=None,
        score_weights_version="rev1", model_id="fake", model_version="v0",
        trace_id="t-guardrail-fail",
    )
    assert withheld.is_withheld is True
    assert withheld.review_status is ReviewStatus.PENDING_HUMAN_REVIEW
    assert "48" in withheld.explanation           # the failure is named in the WHY


def test_clean_prose_without_numbers_emits():
    gen = _stub("The bridge is stable with no notable change.")
    r = run_guardrail_loop(gen, _legit())
    assert r.emitted is True
    assert r.attempts == 1
