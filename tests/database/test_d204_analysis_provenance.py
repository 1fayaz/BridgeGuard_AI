"""D204 — the analysis layer completes the provenance chain (the two hops 0005 unblocked).

Before migration 0005 existed, the chain raw -> validated -> analysis -> assessment -> report/alert
was broken at the `analysis` hop: risk_assessments.source_analysis_ids pointed at a table that did
not exist. This test walks the two hops 0005 makes possible, over the REAL agent fakes:

  DOWN:  analysis_results.source_validated_ids -> validated_readings   (0005 -> 0002)
  UP:    risk_assessments.source_analysis_ids  -> analysis_results     (0006 -> 0005)

Provenance links are SOFT (BIGINT[] arrays, no hard FK — plan §5), so "resolves" means the id
matches a real row the writing agent produced, asserted here across the three stores.

Ties to spec-002 FR-8 (unbroken provenance chain) and AC-5 (the SA table completes the chain).
"""
from __future__ import annotations

import pytest

from agents.data_collection.store import FakeStore, ValidatedRow
from agents.data_collection.statuses import ReadingStatus
from db.analysis_store import FakeAnalysisStore, AnalysisResult
from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.statuses import Severity, ReviewStatus


def _seed_chain():
    """Build raw -> validated -> analysis -> assessment with real provenance ids across the fakes.

    Returns the three stores + the ids so the walk can be asserted end-to-end.
    """
    dca = FakeStore()
    analysis = FakeAnalysisStore()
    risk = FakeRiskStore()

    # raw -> validated (DCA): one raw reading, one validated verdict tracing to it.
    from datetime import datetime, timezone

    t = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    raw_id = dca.append_raw("S1", "accelerometer", t, t, 0.4, {"v": 0.4})
    vid = dca.insert_validated(ValidatedRow(
        row_id=0, sensor_id="S1", sensor_time=t, value=0.4, status=ReadingStatus.OK,
        is_interpolated=False, clock_drift=False, source_raw_ids=(raw_id,), reason=None,
    ))

    # validated -> analysis (SA): a RAN result whose source_validated_ids point at the validated row.
    aid = analysis.insert(AnalysisResult(
        sensor_id="S1", calculation="RMS", block_id="b1", input_version="v1",
        outcome="RAN", value=0.4, config_version="cfg-1", source_validated_ids=(vid,),
    ))

    # analysis -> assessment (Risk): an assessment whose source_analysis_ids point at the analysis row.
    assessment_id = risk.insert(RiskAssessment(
        bridge_id="BRIDGE_A1", cycle_id="c1", risk_score=40, severity=Severity.WATCH,
        recommendation="Increase inspection frequency.",
        explanation="RMS within band; monitoring.", contributing_factors=(),
        confidence=0.9, data_completeness=0.95, review_status=ReviewStatus.FINAL,
        source_analysis_ids=(aid,), baseline_ref=None, standard_code="IRC:6",
        standard_version="2017", score_weights_version="w1", model_id="m", model_version="1",
        trace_id="trace-1",
    ))
    return dca, analysis, risk, raw_id, vid, aid, assessment_id


def test_down_hop_analysis_to_validated_resolves():
    # analysis_results.source_validated_ids -> validated_readings (the hop 0005 adds).
    dca, analysis, _risk, _raw, vid, aid, _asmt = _seed_chain()
    result = analysis.get(aid).result
    assert result.source_validated_ids == (vid,)
    # every referenced validated id resolves to a real validated row.
    validated_ids = {v.row_id for v in dca.validated_rows}
    for sid in result.source_validated_ids:
        assert sid in validated_ids, f"dangling source_validated_id {sid}"


def test_up_hop_assessment_to_analysis_resolves():
    # risk_assessments.source_analysis_ids -> analysis_results (the hop that was dangling pre-0005).
    _dca, analysis, risk, _raw, _vid, aid, asmt = _seed_chain()
    assessment = risk.get(asmt).assessment
    assert assessment.source_analysis_ids == (aid,)
    analysis_ids = {row.id for row in analysis.rows}
    for sid in assessment.source_analysis_ids:
        assert sid in analysis_ids, f"dangling source_analysis_id {sid}"


def test_full_walk_assessment_to_raw_has_no_missing_hop():
    # Walk every hop assessment -> analysis -> validated -> raw; each link resolves.
    dca, analysis, risk, raw_id, vid, aid, asmt = _seed_chain()

    assessment = risk.get(asmt).assessment
    # hop 1: assessment -> analysis
    (analysis_id,) = assessment.source_analysis_ids
    result = analysis.get(analysis_id).result
    # hop 2: analysis -> validated
    (validated_id,) = result.source_validated_ids
    validated = next(v for v in dca.validated_rows if v.row_id == validated_id)
    # hop 3: validated -> raw
    (raw_ref,) = validated.source_raw_ids
    raw = next(r for r in dca.raw_rows if r.raw_id == raw_ref)

    assert raw.raw_id == raw_id
    assert raw.sensor_id == validated.sensor_id == result.sensor_id == "S1"


def test_chain_is_broken_without_0005_layer():
    # Sanity: if the analysis layer is absent, the assessment's provenance dangles — which is exactly
    # the pre-0005 state D204 proves is now fixed. (An empty analysis store => nothing to resolve to.)
    _dca, _analysis, risk, _raw, _vid, aid, asmt = _seed_chain()
    empty_analysis = FakeAnalysisStore()
    assessment = risk.get(asmt).assessment
    analysis_ids = {row.id for row in empty_analysis.rows}
    assert not any(sid in analysis_ids for sid in assessment.source_analysis_ids), (
        "with no analysis layer the hop cannot resolve — this is the gap 0005 closes"
    )
