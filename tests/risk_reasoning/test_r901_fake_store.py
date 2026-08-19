"""R901 — FakeRiskStore mirroring the R203/R204 schema guarantees in-memory.

Acceptance (tasks.md R901): insert assigns id; supersede links old->new and never mutates
score/severity/explanation; delete blocked; a duplicate (bridge_id, cycle_id) among current rows is
rejected/no-op (idempotency); audit append. Mirrors validated_readings/analysis_results guarantees
the way the DCA/SA fakes do (R203 guarantees in-memory).
"""
from __future__ import annotations

import pytest

from agents.risk_reasoning.store import (
    FakeRiskStore,
    DuplicateAssessmentError,
    AssessmentImmutableError,
    AssessmentDeleteBlocked,
)
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.statuses import Severity, ReviewStatus


def _assessment(bridge="b1", cycle="c1", score=50, severity=Severity.WARNING,
                review=ReviewStatus.FINAL) -> RiskAssessment:
    return RiskAssessment(
        bridge_id=bridge, cycle_id=cycle, risk_score=score, severity=severity,
        recommendation="monitor", explanation="because reasons",
        contributing_factors=(), confidence=0.9, data_completeness=0.9,
        review_status=review, source_analysis_ids=(1, 2),
        baseline_ref=None, standard_code="IRC:6", standard_version="2017",
        score_weights_version="rev1", model_id="m", model_version="v", trace_id="t",
    )


def test_insert_assigns_an_id():
    store = FakeRiskStore()
    rid = store.insert(_assessment())
    assert rid == 1
    rid2 = store.insert(_assessment(cycle="c2"))
    assert rid2 == 2


def test_current_returns_non_superseded_for_scope():
    store = FakeRiskStore()
    store.insert(_assessment(cycle="c1"))
    store.insert(_assessment(cycle="c2"))
    assert store.current("b1", "c1") is not None
    assert store.current("b1", "c2") is not None
    assert store.current("b1", "c3") is None


def test_duplicate_current_bridge_cycle_is_rejected():
    # R203 partial unique index: one current assessment per (bridge, cycle).
    store = FakeRiskStore()
    store.insert(_assessment(cycle="c1"))
    with pytest.raises(DuplicateAssessmentError):
        store.insert(_assessment(cycle="c1"))


def test_supersede_then_reinsert_is_allowed():
    # A re-assessment supersedes the old row, freeing the (bridge, cycle) slot.
    store = FakeRiskStore()
    old = store.insert(_assessment(cycle="c1", score=50))
    new = store.insert_superseding(old, _assessment(cycle="c1", score=70))
    assert new != old
    # The current row is the new one.
    cur = store.current("b1", "c1")
    assert cur.risk_score == 70
    # The old row is retained but superseded.
    assert store.get(old).superseded_by == new


def test_supersede_does_not_mutate_the_old_verdict():
    store = FakeRiskStore()
    old = store.insert(_assessment(cycle="c1", score=50))
    store.insert_superseding(old, _assessment(cycle="c1", score=70))
    old_row = store.get(old)
    assert old_row.assessment.risk_score == 50            # unchanged
    assert old_row.assessment.severity is Severity.WARNING


def test_direct_mutation_of_a_stored_verdict_is_blocked():
    store = FakeRiskStore()
    rid = store.insert(_assessment(cycle="c1", score=50))
    with pytest.raises(AssessmentImmutableError):
        store.overwrite(rid, _assessment(cycle="c1", score=99))


def test_delete_is_blocked():
    store = FakeRiskStore()
    rid = store.insert(_assessment(cycle="c1"))
    with pytest.raises(AssessmentDeleteBlocked):
        store.delete(rid)


def test_audit_append_and_read():
    store = FakeRiskStore()
    store.append_audit("b1", "c1", "RISK_ASSESSMENT", "scored WARNING 50")
    store.append_audit("b1", "c1", "RISK_WITHHELD", "coverage below floor")
    kinds = [a.decision for a in store.audit_rows]
    assert kinds == ["RISK_ASSESSMENT", "RISK_WITHHELD"]


def test_audit_is_append_only():
    store = FakeRiskStore()
    store.append_audit("b1", "c1", "RISK_ASSESSMENT", "x")
    with pytest.raises(Exception):
        store.audit_rows.clear()               # returned copy; underlying log intact
    assert len(store.audit_rows) == 1
