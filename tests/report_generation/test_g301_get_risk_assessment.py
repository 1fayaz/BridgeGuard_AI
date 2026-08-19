"""G301 — get_risk_assessment(scope_key, *, historical=False) — read-only.

The report's spine: read the ONE finalized risk_assessments row (0006) the scope key resolves to.
Current (non-superseded) by default; a specific superseded row BY ID when historical=True. The
agent assembles from this row — it never re-decides it (FR-1). Read-only; a missing assessment
returns a structured ASSESSMENT_NOT_FOUND signal, never a raise (FR-12).

Acceptance (tasks.md G301): current scope -> the current row; historical=True + id -> that
superseded row; absent -> ASSESSMENT_NOT_FOUND signal (no raise); the call performs NO mutation.
"""
from __future__ import annotations

from agents.report_generation.tools.risk_assessment_read import (
    AssessmentScope,
    RiskAssessmentReadResult,
    get_risk_assessment,
)


# --- A tiny in-memory source mirroring the 0006 current/superseded distinction. ---
class FakeAssessmentSource:
    def __init__(self, rows):
        # rows: list of dicts with id, bridge_id, cycle_id, assessment_version, superseded_by, ...
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
        superseded_by=None,
    )
    base.update(over)
    return base


# ------------------------------------------------------------------ current ---
def test_current_scope_returns_the_current_row():
    src = FakeAssessmentSource([_row()])
    res = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    assert res.found is True
    assert res.not_found_reason is None
    assert res.assessment["id"] == 1001
    assert res.assessment["assessment_version"] == 3


def test_current_scope_ignores_superseded_rows():
    # An old superseded v2 plus the current v3: the default read returns only the current one.
    rows = [
        _row(id=900, assessment_version=2, superseded_by=1001),
        _row(id=1001, assessment_version=3, superseded_by=None),
    ]
    res = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), rows_src(rows))
    assert res.found is True
    assert res.assessment["id"] == 1001


def rows_src(rows):
    return FakeAssessmentSource(rows)


# ------------------------------------------------------------------ historical ---
def test_historical_true_returns_the_named_superseded_row():
    rows = [
        _row(id=900, assessment_version=2, superseded_by=1001),
        _row(id=1001, assessment_version=3, superseded_by=None),
    ]
    res = get_risk_assessment(
        AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42", assessment_id=900),
        rows_src(rows),
        historical=True,
    )
    assert res.found is True
    assert res.assessment["id"] == 900
    assert res.assessment["assessment_version"] == 2
    assert res.assessment["superseded_by"] == 1001  # it IS a historical row


# ------------------------------------------------------------------ not found ---
def test_absent_current_scope_returns_structured_not_found():
    src = FakeAssessmentSource([])  # nothing
    res = get_risk_assessment(AssessmentScope(bridge_id="ghost", cycle_id="none"), src)
    assert res.found is False
    assert res.assessment is None
    assert res.not_found_reason == "ASSESSMENT_NOT_FOUND"


def test_absent_historical_id_returns_structured_not_found():
    src = FakeAssessmentSource([_row()])
    res = get_risk_assessment(
        AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42", assessment_id=999999),
        src,
        historical=True,
    )
    assert res.found is False
    assert res.not_found_reason == "ASSESSMENT_NOT_FOUND"


def test_historical_without_an_id_is_not_found_not_a_raise():
    # historical=True but no assessment_id given: there is no row to name -> structured not-found.
    src = FakeAssessmentSource([_row()])
    res = get_risk_assessment(
        AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"),
        src,
        historical=True,
    )
    assert res.found is False
    assert res.not_found_reason == "ASSESSMENT_NOT_FOUND"


# ------------------------------------------------------------------ read-only ---
def test_read_performs_no_mutation():
    src = FakeAssessmentSource([_row()])
    get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    assert src.mutations == 0


def test_returned_assessment_is_a_copy_not_the_stored_row():
    # Mutating the returned dict must not corrupt the store's row (defensive copy).
    src = FakeAssessmentSource([_row()])
    res = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    res.assessment["risk_score"] = 999
    again = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    assert again.assessment["risk_score"] == 48


def test_result_is_never_both_found_and_not_found():
    src = FakeAssessmentSource([_row()])
    res = get_risk_assessment(AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42"), src)
    assert res.found is True and res.not_found_reason is None
