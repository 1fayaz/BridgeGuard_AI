"""R702 — FakeReasoningModel deterministic stub (test infrastructure for R703+).

Acceptance (tasks.md R702): the stub yields deterministic drafts per scenario; swapping it for the
real model changes only the draft text, not the control flow. It returns canned explanation drafts
keyed by scenario (clean / one-bad-then-clean / two-bad / conflicting-factors) so the scorer,
guardrail loop, gating, and persistence are all testable WITHOUT a live model.

The stub implements the same `draft(attempt, context)` shape the guardrail loop (R604) and the
orchestrator (R703) call, so it is a drop-in for the real model in tests.
"""
from __future__ import annotations

from agents.risk_reasoning.fake_model import FakeReasoningModel, Scenario


def test_clean_scenario_yields_a_traceable_draft_every_attempt():
    m = FakeReasoningModel(Scenario.CLEAN)
    d0 = m.draft(0, context={})
    assert isinstance(d0, str) and d0
    # Deterministic: same attempt -> same text.
    assert m.draft(0, context={}) == d0


def test_one_bad_then_clean_scenario_sequences_by_attempt():
    m = FakeReasoningModel(Scenario.ONE_BAD_THEN_CLEAN)
    bad = m.draft(0, context={})
    good = m.draft(1, context={})
    assert bad != good
    # attempt 0 carries a fabricated number; attempt 1 is clean.
    assert "48" in bad
    assert "48" not in good


def test_two_bad_scenario_is_bad_on_both_attempts():
    m = FakeReasoningModel(Scenario.TWO_BAD)
    assert "48" in m.draft(0, context={})
    assert "48" in m.draft(1, context={})


def test_conflicting_factors_scenario_names_both_directions():
    m = FakeReasoningModel(Scenario.CONFLICTING)
    d = m.draft(0, context={}).lower()
    # The conflicting-signals narrative should mention a factor that rose and one that stayed low.
    assert "vibration" in d
    assert "deflection" in d


def test_deterministic_across_instances():
    a = FakeReasoningModel(Scenario.CLEAN).draft(0, context={})
    b = FakeReasoningModel(Scenario.CLEAN).draft(0, context={})
    assert a == b


def test_records_calls_for_assertion():
    m = FakeReasoningModel(Scenario.ONE_BAD_THEN_CLEAN)
    m.draft(0, context={})
    m.draft(1, context={})
    assert m.calls == [0, 1]


def test_context_can_be_interpolated_into_the_draft():
    # The stub may weave a score from context so drafts can cite the real deterministic number.
    m = FakeReasoningModel(Scenario.CLEAN)
    d = m.draft(0, context={"score": 58})
    assert "58" in d
