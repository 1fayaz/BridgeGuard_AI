"""R1001 — tracing on from first run; trace_id captured on every row (Principle VII) [LLM-DEP].

Acceptance (tasks.md R1001): a run produces a trace_id; the persisted assessment carries it; tracing
is not conditionally disabled in any path (incl. withheld / guardrail-fail / internal error). The
live SDK trace backend is deferred; what is asserted now is that the trace_id WIRING is present and
unconditional — no code path drops it (the DB-visible half of the dual audit, plan §5).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.risk_reasoning.orchestrator import assess_bridge
from agents.risk_reasoning.persistence import persist_assessment
from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.fake_model import FakeReasoningModel, Scenario
from agents.risk_reasoning.scorer import FactorInput
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import StandardEntry


@dataclass
class FakeStore:
    rows: list = field(default_factory=list)
    standards: dict = field(default_factory=dict)
    raise_on_results: bool = False

    def current_results_for(self, b, c):
        if self.raise_on_results:
            raise RuntimeError("injected failure")
        return [r for r in self.rows if r.bridge_id == b and r.cycle_id == c and r.superseded_by is None]

    def baseline_for(self, b, w):
        return []

    def standard_for(self, t):
        return self.standards.get(t)


def _row(rid, value, outcome="RAN"):
    return AnalysisResultRow(
        id=rid, bridge_id="b1", cycle_id="c1", sensor_id=f"s{rid}", calculation="RMS",
        outcome=outcome, reason_code=None if outcome == "RAN" else "NO_CHANGE",
        result={"value": value, "limit": 1.0}, flags={}, source_validated_ids=[rid],
        superseded_by=None,
    )


def _extractor(results, standard):
    return [FactorInput(r.calculation.lower(), r.id, float(r.result["value"]),
                        float(r.result["limit"])) for r in results if r.outcome == "RAN"]


def _assess(store, model, trace_id, expected=1):
    return assess_bridge(
        bridge_id="b1", cycle_id="c1", store=store, bridge_type="girder",
        score_config=ScoreConfig(score_weights_version="rev1", weights=(("rms", 1.0),),
                                 ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
                                 watch_min=25.0, warning_min=50.0, critical_min=75.0),
        coverage_config=CoverageConfig(coverage_floor=0.5, completeness_full_fraction=1.0),
        model=model, factor_extractor=_extractor, expected_calc_count=expected,
        model_id="frontier-x", model_version="2026-05", trace_id=trace_id,
    )


def _healthy():
    return FakeStore(rows=[_row(1, 0.60)],
                     standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})})


def test_scored_run_carries_trace_id():
    a = _assess(_healthy(), FakeReasoningModel(Scenario.CLEAN), "trace-scored")
    assert a.trace_id == "trace-scored"


def test_withheld_run_carries_trace_id():
    store = FakeStore(rows=[_row(1, 0.60, outcome="SKIPPED")],
                      standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})})
    a = _assess(store, FakeReasoningModel(Scenario.CLEAN), "trace-withheld", expected=4)
    assert a.is_withheld is True
    assert a.trace_id == "trace-withheld"


def test_guardrail_fail_run_carries_trace_id():
    a = _assess(_healthy(), FakeReasoningModel(Scenario.TWO_BAD), "trace-guardrail")
    assert a.is_withheld is True
    assert a.trace_id == "trace-guardrail"


def test_internal_error_run_still_carries_trace_id():
    store = _healthy()
    store.raise_on_results = True
    a = _assess(store, FakeReasoningModel(Scenario.CLEAN), "trace-error")
    assert a.is_withheld is True
    assert a.trace_id == "trace-error"       # even the crash-isolation path preserves it


def test_trace_id_persists_onto_the_stored_row():
    # The DB-visible half of the dual audit: the row links to the SDK trace via trace_id.
    store = FakeRiskStore()
    a = _assess(_healthy(), FakeReasoningModel(Scenario.CLEAN), "trace-persist")
    persist_assessment(store, a)
    assert store.current("b1", "c1").trace_id == "trace-persist"


def test_no_path_emits_an_empty_trace_id():
    # Every scenario must yield a non-empty trace id — tracing is never conditionally off.
    scenarios = [
        (_healthy(), FakeReasoningModel(Scenario.CLEAN), 1),
        (_healthy(), FakeReasoningModel(Scenario.TWO_BAD), 1),
    ]
    for store, model, expected in scenarios:
        a = _assess(store, model, "trace-x", expected=expected)
        assert a.trace_id and a.trace_id.strip()
