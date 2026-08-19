"""D802 — provenance survives supersession: the pinned version an assessment acted on stays resolvable.

[DB-DEP] No Neon locally; proven over the real agent fakes (FakeAnalysisStore + FakeRiskStore), which
mirror the append/supersede + permanent-history guarantees the SQL enforces. The scenario (spec
FR-7/FR-9, AC-7/AC-8):

  1. An analysis row (id A_old) is produced; a risk assessment pins it via source_analysis_ids = {A_old}.
  2. The analysis is later CORRECTED — a NEW row (A_new) is appended and A_old.superseded_by := A_new
     (correct-by-supersede; the old verdict is never edited in place).
  3. The original assessment STILL resolves to A_old — the exact version it acted on — because
     provenance is pinned by ROW ID, not "whatever is current"; and A_old is STILL READABLE
     (history is permanent, Constitution VI), just marked historical.

This is what makes an audit reproducible: re-reading an old assessment reconstructs the exact inputs
it saw, even after the analysis layer moved on. A provenance link that silently re-pointed to the
current version would falsify the record.

Ties to spec-002 FR-7/FR-9 and AC-7/AC-8.
"""
from __future__ import annotations

import pytest

from db.analysis_store import FakeAnalysisStore, AnalysisResult
from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.statuses import Severity, ReviewStatus


def _analysis(**over) -> AnalysisResult:
    base = dict(
        sensor_id="SENSOR_A1_ACC", calculation="RMS", block_id="blk-1", input_version="v1",
        outcome="RAN", value=0.40, config_version="cfg-1", source_validated_ids=(1,),
    )
    base.update(over)
    return AnalysisResult(**base)


def _assessment(analysis_id: int) -> RiskAssessment:
    return RiskAssessment(
        bridge_id="BRIDGE_A1", cycle_id="cycle-1", risk_score=35, severity=Severity.WATCH,
        recommendation="Increase inspection frequency.",
        explanation="RMS within band, monitoring.", contributing_factors=(),
        confidence=0.9, data_completeness=0.95, review_status=ReviewStatus.FINAL,
        source_analysis_ids=(analysis_id,), baseline_ref=None, standard_code="IRC:6",
        standard_version="2017", score_weights_version="w1", model_id="m", model_version="1",
        trace_id="trace-A1",
    )


def _seed_then_supersede():
    """Build assessment -> analysis(A_old), then supersede the analysis with A_new. Returns the
    stores plus (a_old, a_new, assessment_id)."""
    analysis = FakeAnalysisStore()
    risk = FakeRiskStore()

    a_old = analysis.insert(_analysis(value=0.40))
    assessment_id = risk.insert(_assessment(a_old))

    # the analysis is corrected: a new row is appended and the old one is linked to it.
    a_new = analysis.insert_superseding(a_old, _analysis(value=0.44))
    return analysis, risk, a_old, a_new, assessment_id


def test_assessment_still_pins_the_old_analysis_id():
    analysis, risk, a_old, a_new, asmt = _seed_then_supersede()
    pinned = risk.get(asmt).assessment.source_analysis_ids
    assert pinned == (a_old,), "the assessment must still cite the exact version it acted on, not A_new"
    assert a_new not in pinned


def test_superseded_analysis_row_is_still_readable():
    analysis, risk, a_old, a_new, asmt = _seed_then_supersede()
    old_row = analysis.get(a_old)
    assert old_row is not None, "the superseded analysis row must remain readable (history permanent)"
    # it is retained UNCHANGED (its value is the original), and marked historical.
    assert old_row.result.value == 0.40
    assert old_row.superseded_by == a_new


def test_walk_resolves_to_the_pinned_version_after_supersession():
    analysis, risk, a_old, a_new, asmt = _seed_then_supersede()
    # walk the surviving hop: assessment -> analysis, using the pinned id.
    (analysis_id,) = risk.get(asmt).assessment.source_analysis_ids
    resolved = analysis.get(analysis_id)
    assert resolved is not None and resolved.id == a_old
    assert resolved.result.value == 0.40, "the walk reconstructs the EXACT inputs the assessment saw"


def test_current_pointer_moved_but_provenance_did_not():
    analysis, risk, a_old, a_new, asmt = _seed_then_supersede()
    # the CURRENT analysis for the key is now A_new (the correction)...
    cur = analysis.current(sensor_id="SENSOR_A1_ACC", calculation="RMS", block_id="blk-1", input_version="v1")
    assert cur is not None and cur.value == 0.44
    # ...but the assessment's provenance still points at A_old, not the moved-on current row.
    (pinned,) = risk.get(asmt).assessment.source_analysis_ids
    assert pinned == a_old and pinned != a_new


def test_the_old_analysis_verdict_was_never_edited_in_place():
    # correct-by-supersede: overwriting the old analysis in place is blocked (it's a NEW row instead).
    from db.analysis_store import AnalysisResultImmutableError

    analysis, risk, a_old, a_new, asmt = _seed_then_supersede()
    with pytest.raises(AnalysisResultImmutableError):
        analysis.overwrite(a_old, _analysis(value=999.0))
    # and the old row is untouched by the attempt.
    assert analysis.get(a_old).result.value == 0.40
