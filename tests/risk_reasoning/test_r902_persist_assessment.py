"""R902 — persist_assessment(store, assessment, guardrail_failed) [DB-DEP].

Acceptance (tasks.md R902): a scored WARNING assessment, a withheld (below-floor) assessment, and a
guardrail-fail assessment each produce exactly the expected row + audit kind; every row links its
pinned provenance and stores the explanation verbatim. FR-9, AC-9.

Audit-kind selection (R204 enum):
  scored (not withheld)                 -> RISK_ASSESSMENT
  withheld, guardrail_failed=False      -> RISK_WITHHELD
  withheld, guardrail_failed=True       -> RISK_GUARDRAIL_FAIL
"""
from __future__ import annotations

from agents.risk_reasoning.persistence import persist_assessment
from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.statuses import Severity, ReviewStatus


def _scored() -> RiskAssessment:
    return RiskAssessment(
        bridge_id="b1", cycle_id="c1", risk_score=50, severity=Severity.WARNING,
        recommendation="monitor", explanation="Vibration at 60% drove the score to 50.",
        contributing_factors=(), confidence=0.9, data_completeness=0.9,
        review_status=ReviewStatus.FINAL, source_analysis_ids=(1, 2),
        baseline_ref="b1:30d", standard_code="IRC:6", standard_version="2017",
        score_weights_version="rev1", model_id="m", model_version="v", trace_id="trace-1",
    )


def _withheld(explanation="coverage below floor") -> RiskAssessment:
    return RiskAssessment(
        bridge_id="b1", cycle_id="c1", risk_score=None, severity=None,
        recommendation="withheld", explanation=explanation,
        contributing_factors=(), confidence=0.2, data_completeness=0.2,
        review_status=ReviewStatus.PENDING_HUMAN_REVIEW, source_analysis_ids=(1,),
        baseline_ref=None, standard_code=None, standard_version=None,
        score_weights_version="rev1", model_id="m", model_version="v", trace_id="trace-2",
    )


def test_scored_assessment_writes_row_and_risk_assessment_audit():
    store = FakeRiskStore()
    rid = persist_assessment(store, _scored())
    assert store.current("b1", "c1").risk_score == 50
    kinds = [a.decision for a in store.audit_rows]
    assert kinds == ["RISK_ASSESSMENT"]
    assert store.get(rid) is not None


def test_withheld_assessment_writes_risk_withheld_audit():
    store = FakeRiskStore()
    persist_assessment(store, _withheld())
    assert store.current("b1", "c1").is_withheld is True
    assert [a.decision for a in store.audit_rows] == ["RISK_WITHHELD"]


def test_guardrail_fail_writes_risk_guardrail_fail_audit():
    store = FakeRiskStore()
    persist_assessment(store, _withheld("guardrail failed closed: cited 48"),
                       guardrail_failed=True)
    assert [a.decision for a in store.audit_rows] == ["RISK_GUARDRAIL_FAIL"]


def test_explanation_is_stored_verbatim():
    store = FakeRiskStore()
    persist_assessment(store, _scored())
    assert store.current("b1", "c1").explanation == "Vibration at 60% drove the score to 50."


def test_provenance_is_pinned_on_the_row():
    store = FakeRiskStore()
    persist_assessment(store, _scored())
    row = store.current("b1", "c1")
    assert row.source_analysis_ids == (1, 2)
    assert row.standard_code == "IRC:6"
    assert row.standard_version == "2017"
    assert row.score_weights_version == "rev1"
    assert row.model_id == "m"
    assert row.trace_id == "trace-1"


def test_audit_reason_names_the_gap_for_withheld():
    store = FakeRiskStore()
    persist_assessment(store, _withheld("coverage below floor"))
    assert "coverage below floor" in store.audit_rows[0].reason


def test_re_persist_same_scope_supersedes_not_duplicates():
    # A second assessment for the same (bridge, cycle) supersedes the first (idempotent scope).
    store = FakeRiskStore()
    persist_assessment(store, _scored())
    updated = RiskAssessment(
        bridge_id="b1", cycle_id="c1", risk_score=70, severity=Severity.WARNING,
        recommendation="monitor", explanation="revised after recompute",
        contributing_factors=(), confidence=0.9, data_completeness=0.9,
        review_status=ReviewStatus.FINAL, source_analysis_ids=(1, 2, 3),
        baseline_ref="b1:30d", standard_code="IRC:6", standard_version="2017",
        score_weights_version="rev1", model_id="m", model_version="v", trace_id="trace-3",
    )
    persist_assessment(store, updated)
    assert store.current("b1", "c1").risk_score == 70   # new current
    # Two rows total (old retained, superseded), not a duplicate-key crash.
    assert len(store.rows) == 2
