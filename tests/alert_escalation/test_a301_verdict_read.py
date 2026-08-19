"""A301 — the verdict read, REUSING the Report agent's risk_assessment_read (read-only).

The Alert agent consumes exactly the finalized risk_assessments verdict the Report agent already
reads by identity. Per the plan (§3a / Open Item 7), we REUSE that one read tool rather than fork a
parallel copy — the Alert package exposes it under its own `tools.verdict_read` namespace (so the
service never reaches into report_generation internals directly), but it IS the same implementation.

Acceptance (tasks.md A301): current scope -> the current verdict; absent -> ASSESSMENT_NOT_FOUND
signal (no raise); the call performs NO mutation; the reused symbols resolve and are the SAME
objects as the Report agent's (a genuine reuse, not a fork); the band vocabulary is importable from
risk_reasoning.statuses.
"""
from __future__ import annotations

from agents.alert_escalation.tools.verdict_read import (
    ASSESSMENT_NOT_FOUND,
    AssessmentScope,
    RiskAssessmentReadResult,
    get_risk_assessment,
)


class FakeVerdictSource:
    """A tiny in-memory source mirroring the 0006 current/superseded distinction."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.mutations = 0  # bumped if any write method is (wrongly) called

    def current_assessment_for(self, bridge_id: str, cycle_id: str):
        for r in self._rows:
            if (
                r["bridge_id"] == bridge_id
                and r["cycle_id"] == cycle_id
                and r["superseded_by"] is None
            ):
                return dict(r)
        return None

    def assessment_by_id(self, assessment_id: int):
        for r in self._rows:
            if r["id"] == assessment_id:
                return dict(r)
        return None


def _row(**over):
    base = dict(
        id=1001,
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_version=3,
        risk_score=48,
        severity="WARNING",
        recommendation="Schedule inspection.",
        explanation="Deflection ratio elevated at pier 3.",
        review_status="FINAL",
        source_analysis_ids=[11, 12],
        standard_code="AASHTO",
        standard_version="2020",
        trace_id="trace-xyz",
        superseded_by=None,
    )
    base.update(over)
    return base


# ------------------------------------------------------------------ current ---
def test_current_scope_returns_the_current_verdict():
    src = FakeVerdictSource([_row()])
    res = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    assert res.found is True
    assert res.not_found_reason is None
    assert res.assessment["id"] == 1001
    assert res.assessment["assessment_version"] == 3


def test_current_scope_ignores_superseded_rows():
    rows = [
        _row(id=900, assessment_version=2, superseded_by=1001),
        _row(id=1001, assessment_version=3, superseded_by=None),
    ]
    res = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"),
                              FakeVerdictSource(rows))
    assert res.found is True
    assert res.assessment["id"] == 1001


# ------------------------------------------------------------------ not found ---
def test_absent_scope_returns_structured_not_found_not_a_raise():
    src = FakeVerdictSource([])
    res = get_risk_assessment(AssessmentScope(bridge_id="ghost", cycle_id="none"), src)
    assert res.found is False
    assert res.assessment is None
    assert res.not_found_reason == ASSESSMENT_NOT_FOUND == "ASSESSMENT_NOT_FOUND"


# ------------------------------------------------------------------ read-only ---
def test_read_performs_no_mutation():
    src = FakeVerdictSource([_row()])
    get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    assert src.mutations == 0


def test_returned_verdict_is_a_copy_not_the_stored_row():
    src = FakeVerdictSource([_row()])
    res = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    res.assessment["risk_score"] = 999
    again = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    assert again.assessment["risk_score"] == 48


# ------------------------------------------------------------------ genuine reuse (not a fork) ---
def test_reused_symbols_are_the_same_objects_as_the_report_agents():
    # A genuine reuse: the Alert namespace re-exports the ONE implementation, never a copy.
    from agents.report_generation.tools import risk_assessment_read as report_read

    assert get_risk_assessment is report_read.get_risk_assessment
    assert AssessmentScope is report_read.AssessmentScope
    assert RiskAssessmentReadResult is report_read.RiskAssessmentReadResult


def test_band_vocabulary_is_importable_from_risk_statuses():
    # The Alert agent reasons over the verdict's Severity/ReviewStatus — importable, one closed set.
    from agents.risk_reasoning.statuses import ReviewStatus, Severity

    assert Severity.WARNING.value == "WARNING"
    assert ReviewStatus.PENDING_HUMAN_REVIEW.value == "PENDING_HUMAN_REVIEW"
