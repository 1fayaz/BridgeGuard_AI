"""R1002 — service invocation entrypoint (FR-8, FR-3a).

Acceptance (tasks.md R1002): given a bridge+cycle, returns the assessment summary
(score/severity/review_status or withheld-reason); malformed payload -> structured error, never a
stack trace; idempotent on redelivery (R901 uniqueness -> supersede). = FR-8, FR-3a.

The entrypoint is the single callable n8n hits. It assembles config + the model + the store, runs
assess_bridge, persists, and returns a plain dict summary. It NEVER raises: bad input becomes an
error summary.
"""
from __future__ import annotations

from agents.risk_reasoning.service import run_assessment, AssessmentSummary
from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.fake_model import FakeReasoningModel, Scenario
from agents.risk_reasoning.scorer import FactorInput
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import StandardEntry


class FakeStore(FakeRiskStore):
    """Extends the persistent risk store with the three read ports so one object serves both roles.

    Note: the base class exposes `rows` as a read-only property (the persisted assessments), so the
    SA input rows live under a distinct name (`analysis`) to avoid colliding with it.
    """

    def __init__(self, analysis=None, standards=None):
        super().__init__()
        self.analysis = list(analysis or [])
        self.standards = dict(standards or {})

    def current_results_for(self, b, c):
        return [r for r in self.analysis
                if r.bridge_id == b and r.cycle_id == c and r.superseded_by is None]

    def baseline_for(self, b, w):
        return []

    def standard_for(self, t):
        return self.standards.get(t)


def _row(rid, value):
    return AnalysisResultRow(
        id=rid, bridge_id="b1", cycle_id="c1", sensor_id=f"s{rid}", calculation="RMS",
        outcome="RAN", reason_code=None, result={"value": value, "limit": 1.0},
        flags={}, source_validated_ids=[rid], superseded_by=None,
    )


def _extractor(results, standard):
    return [FactorInput(r.calculation.lower(), r.id, float(r.result["value"]),
                        float(r.result["limit"])) for r in results if r.outcome == "RAN"]


def _cfg():
    return ScoreConfig(score_weights_version="rev1", weights=(("rms", 1.0),),
                       ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
                       watch_min=25.0, warning_min=50.0, critical_min=75.0)


def _run(store, payload, model=None):
    return run_assessment(
        payload, store=store,
        score_config=_cfg(),
        coverage_config=CoverageConfig(coverage_floor=0.5, completeness_full_fraction=1.0),
        model=model or FakeReasoningModel(Scenario.CLEAN),
        factor_extractor=_extractor, expected_calc_count=1,
        model_id="frontier-x", model_version="2026-05",
    )


def _healthy():
    return FakeStore(analysis=[_row(1, 0.60)],
                     standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})})


def test_returns_structured_summary_for_a_scored_run():
    s = _run(_healthy(), {"bridge_id": "b1", "cycle_id": "c1", "bridge_type": "girder"})
    assert isinstance(s, AssessmentSummary)
    assert s.ok is True
    assert s.risk_score == 60
    assert s.severity == "WARNING"
    assert s.review_status == "FINAL"
    assert s.withheld is False


def test_summary_reports_withheld_with_reason():
    store = FakeStore(analysis=[_row(1, 0.60)], standards={})  # no standard -> withhold
    s = _run(store, {"bridge_id": "b1", "cycle_id": "c1", "bridge_type": "girder"})
    assert s.ok is True
    assert s.withheld is True
    assert s.review_status == "PENDING_HUMAN_REVIEW"
    assert "standard" in s.reason.lower()


def test_malformed_payload_returns_structured_error_not_a_raise():
    for bad in [{}, {"bridge_id": "b1"}, {"cycle_id": "c1"}, {"bridge_id": "", "cycle_id": "c1"},
                None, "not-a-dict", {"bridge_id": 1, "cycle_id": 2}]:
        s = _run(_healthy(), bad)
        assert isinstance(s, AssessmentSummary)
        assert s.ok is False              # structured error
        assert s.error                    # names the problem
        # No exception escaped.


def test_persists_the_assessment():
    store = _healthy()
    _run(store, {"bridge_id": "b1", "cycle_id": "c1", "bridge_type": "girder"})
    assert store.current("b1", "c1") is not None


def test_idempotent_on_redelivery_supersedes_not_duplicates():
    store = _healthy()
    payload = {"bridge_id": "b1", "cycle_id": "c1", "bridge_type": "girder"}
    _run(store, payload)
    _run(store, payload)                  # redelivered trigger
    # One current row; history preserved (supersede), no duplicate-key crash.
    assert store.current("b1", "c1") is not None
    assert len(store.rows) == 2


def test_guardrail_fail_summary_is_withheld():
    s = _run(_healthy(), {"bridge_id": "b1", "cycle_id": "c1", "bridge_type": "girder"},
             model=FakeReasoningModel(Scenario.TWO_BAD))
    assert s.withheld is True
    assert s.review_status == "PENDING_HUMAN_REVIEW"


def test_missing_bridge_type_is_a_structured_error():
    s = _run(_healthy(), {"bridge_id": "b1", "cycle_id": "c1"})
    assert s.ok is False
    assert "bridge_type" in s.error
