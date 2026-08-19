"""R1101 — scenario harness (fake store + fake model), deterministic + replayable.

Acceptance (tasks.md R1101): a scripted set of scenarios covering every spec situation — all-RAN
normal, conflicting factors, below-coverage-floor, standard-unavailable, all-four input flags,
CRITICAL band, borderline/near-boundary, invented-number draft (guardrail), one-bad-then-clean
(regenerate once), two-bad (fail closed), re-assessment of the same (bridge, cycle), and a
malformed/partial input (never-crash). The harness is deterministic and replayable, and is the
shared fixture R1102's end-to-end AC assertions drive.

This test proves the harness itself: every named scenario is present, each yields its documented
outcome, and replaying the whole catalog twice gives byte-identical summaries (no clock/random).
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

from _harness import (
    all_cases,
    run_case,
    SCENARIO_NAMES,
    collect_case_caveats,
)
from agents.risk_reasoning.band import severity_for
from agents.risk_reasoning.service import AssessmentSummary


def _by_name():
    return {c.name: c for c in all_cases()}


def test_every_required_scenario_is_present():
    names = {c.name for c in all_cases()}
    assert names == set(SCENARIO_NAMES)


def test_each_case_produces_a_structured_summary_never_raises():
    for case in all_cases():
        summary = run_case(case)
        assert isinstance(summary, AssessmentSummary)  # never a raise, always structured


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_case_matches_its_documented_expectation(name):
    case = _by_name()[name]
    exp = case.expected
    s = run_case(case)

    assert s.ok is exp.ok
    if exp.error:
        assert s.error
        return
    assert s.withheld is exp.withheld
    if exp.review_status is not None:
        assert s.review_status == exp.review_status
    if exp.severity is not None:
        assert s.severity == exp.severity
    if exp.score is not None:
        assert s.risk_score == exp.score
    if exp.reason_contains is not None:
        assert exp.reason_contains in (s.reason or "").lower()


def test_replaying_the_whole_catalog_is_deterministic():
    # Same scripted inputs -> identical summaries on a fresh replay (no clock, no randomness).
    first = [asdict(run_case(c)) for c in all_cases()]
    second = [asdict(run_case(c)) for c in all_cases()]
    assert first == second


def test_normal_scenario_is_a_scored_final_warning():
    s = run_case(_by_name()["normal"])
    assert s.ok and not s.withheld
    assert s.severity == "WARNING" and s.review_status == "FINAL"
    assert s.risk_score == 60


def test_critical_scenario_is_pending_human_review():
    s = run_case(_by_name()["critical"])
    assert s.severity == "CRITICAL"
    assert s.review_status == "PENDING_HUMAN_REVIEW"   # mandate #3: never final unreviewed


def test_borderline_scenario_sits_near_a_cut_point():
    case = _by_name()["borderline"]
    s = run_case(case)
    assert s.ok and not s.withheld
    band = severity_for(s.risk_score, case.score_config)
    assert band.near_boundary is True                  # annotation only — band unchanged


def test_regenerate_once_emits_after_exactly_one_retry():
    case = _by_name()["regenerate_once"]
    s = run_case(case)
    assert s.ok and not s.withheld                     # clean draft on the 2nd attempt was emitted
    assert case.model.calls == [0, 1]                  # exactly one regeneration


def test_fail_closed_withholds_and_never_emits_the_fabrication():
    case = _by_name()["fail_closed"]
    s = run_case(case)
    assert s.withheld is True
    assert s.review_status == "PENDING_HUMAN_REVIEW"
    assert "guardrail" in (s.reason or "").lower()
    # The fabricated value IS named in the audit reason (the tripwire quotes the offending number,
    # which is correct forensics) — but it never becomes an emitted SCORE. That is the safety line.
    assert s.risk_score is None


def test_reassessment_supersedes_not_duplicates():
    case = _by_name()["reassessment"]
    run_case(case)                                     # first delivery
    run_case(case)                                     # redelivered same (bridge, cycle)
    assert case.store.current("b1", "c1") is not None
    assert len(case.store.rows) == 2                   # history preserved, one current


def test_all_flags_scenario_carries_every_caveat():
    case = _by_name()["all_flags"]
    s = run_case(case)
    assert s.ok and not s.withheld
    caveats = collect_case_caveats(case)
    assert {c.flag for c in caveats} == {
        "clock_drift", "interpolated_input", "rate_mismatch", "abnormal_quiet",
    }


def test_malformed_input_is_a_structured_error_not_a_crash():
    s = run_case(_by_name()["malformed"])
    assert s.ok is False and s.error
