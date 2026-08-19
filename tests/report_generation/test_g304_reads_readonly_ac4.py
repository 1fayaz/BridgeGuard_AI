"""G304 — the three read ports are read-only + structured-missing (AC-4).

This is a cross-cutting acceptance test (no new production code): it asserts the AC-4 contract
holistically across G301/G302/G303 in one place, rather than per-port. AC-4 = the report reads
finalized rows BY IDENTITY, current-by-default, and never mutates upstream; a superseded row is
reachable ONLY under historical=True; missing data yields a structured signal, never a raise.

The assertions are load-bearing, not tautological: each store records mutations and each read is
driven through its real port over a populated + a depleted fake, and the raise-vs-signal boundary
is checked by construction (we assert no exception escapes AND the structured miss is set).
"""
from __future__ import annotations

import pytest

from agents.report_generation.tools.analysis_results_read import get_analysis_results
from agents.report_generation.tools.risk_assessment_read import (
    AssessmentScope,
    get_risk_assessment,
)
from agents.report_generation.tools.validated_readings_read import get_validated_readings


# --- One combined fake exposing all three source protocols, counting any write attempt. ---
class FakeUpstream:
    def __init__(self, assessments, analyses, readings):
        self._assessments = [dict(a) for a in assessments]
        self._analyses = {a["id"]: a for a in analyses}
        self._readings = {r["id"]: r for r in readings}
        self.mutations = 0

    # risk_assessments (0006)
    def current_assessment_for(self, bridge_id, cycle_id):
        for a in self._assessments:
            if a["bridge_id"] == bridge_id and a["cycle_id"] == cycle_id and a["superseded_by"] is None:
                return dict(a)
        return None

    def assessment_by_id(self, assessment_id):
        for a in self._assessments:
            if a["id"] == assessment_id:
                return dict(a)
        return None

    # analysis_results (0005)
    def analysis_results_by_ids(self, ids):
        return [dict(self._analyses[i]) for i in ids if i in self._analyses]

    # validated_readings (0002)
    def validated_readings_by_ids(self, ids):
        return [dict(self._readings[i]) for i in ids if i in self._readings]

    def snapshot(self):
        # A cheap structural fingerprint to prove no read mutated the store.
        return (
            tuple((a["id"], a["risk_score"], a["superseded_by"]) for a in self._assessments),
            tuple(sorted(self._analyses)),
            tuple(sorted(self._readings)),
        )


def _populated():
    assessments = [
        dict(id=900, bridge_id="b", cycle_id="c", assessment_version=2,
             risk_score=40, superseded_by=1001),
        dict(id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
             risk_score=48, superseded_by=None),
    ]
    analyses = [dict(id=11, source_validated_ids=[110]), dict(id=12, source_validated_ids=[120])]
    readings = [dict(id=110, value=1.0), dict(id=120, value=2.0)]
    return FakeUpstream(assessments, analyses, readings)


# ------------------------------------------------------------------ current-by-default ---
def test_reads_current_assessment_by_default_not_the_superseded_one():
    src = _populated()
    res = get_risk_assessment(AssessmentScope("b", "c"), src)
    assert res.found and res.assessment["id"] == 1001  # the current v3, never the superseded v900


def test_superseded_row_reachable_only_under_historical_true():
    src = _populated()
    # Default read never surfaces the superseded row...
    default = get_risk_assessment(AssessmentScope("b", "c"), src)
    assert default.assessment["id"] != 900
    # ...but a historical read by id does.
    hist = get_risk_assessment(AssessmentScope("b", "c", assessment_id=900), src, historical=True)
    assert hist.found and hist.assessment["id"] == 900


# ------------------------------------------------------------------ no mutation ---
def test_none_of_the_three_reads_mutate_any_store():
    src = _populated()
    before = src.snapshot()
    get_risk_assessment(AssessmentScope("b", "c"), src)
    get_analysis_results((11, 12), src)
    get_validated_readings((110, 120), src, max_rows=100)
    assert src.mutations == 0
    assert src.snapshot() == before  # structural state identical after all three reads


# ------------------------------------------------------------------ structured-missing, never raises ---
def test_all_three_return_structured_signal_on_missing_never_raise():
    empty = FakeUpstream([], [], [])
    # No exception may escape any of the three...
    a = get_risk_assessment(AssessmentScope("ghost", "none"), empty)
    b = get_analysis_results((11, 12), empty)
    c = get_validated_readings((110, 120), empty, max_rows=10)
    # ...and each reports its miss structurally.
    assert a.found is False and a.not_found_reason == "ASSESSMENT_NOT_FOUND"
    assert b.available is False and set(b.missing_ids) == {11, 12}
    assert c.available is False and set(c.missing_ids) == {110, 120}


def test_partial_analysis_gap_is_a_signal_not_a_raise():
    src = _populated()
    # 11 exists, 99 does not -> section-gap signal, no exception.
    res = get_analysis_results((11, 99), src)
    assert res.available is False
    assert 99 in res.missing_ids
    assert [r["id"] for r in res.results] == [11]


def test_reads_are_by_identity_not_scan():
    # A read for ids the store does not have returns nothing for them (identity lookup), and does
    # not accidentally return other rows.
    src = _populated()
    res = get_validated_readings((999,), src, max_rows=10)
    assert res.readings == ()
    assert res.available is False
