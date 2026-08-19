"""R802 — caveat propagation from SA flags into the reasoning (AC-8).

Acceptance (tasks.md R802): an input with clock_drift set -> the assembled context flags it and the
explanation includes the caveat; a frequency-based factor resting on a drifted block is marked less
trustworthy; no flag is dropped. AC-8.

Two pieces: a pure `collect_caveats(results)` that turns SA result flags into human-readable
caveats, and the orchestrator carrying them into the model context so the drafted explanation
surfaces them (not silently dropped).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.risk_reasoning.caveats import collect_caveats
from agents.risk_reasoning.orchestrator import assess_bridge
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.scorer import FactorInput
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import StandardEntry


# --- collect_caveats (pure) -------------------------------------------------------------------
def _row(rid, flags):
    return AnalysisResultRow(
        id=rid, bridge_id="b1", cycle_id="c1", sensor_id=f"s{rid}", calculation="RMS",
        outcome="RAN", reason_code=None, result={"value": 0.6, "limit": 1.0},
        flags=flags, source_validated_ids=[rid], superseded_by=None,
    )


def test_no_flags_no_caveats():
    assert collect_caveats([_row(1, {})]) == ()


def test_clock_drift_flag_becomes_a_caveat():
    cav = collect_caveats([_row(1, {"clock_drift": True})])
    assert any("clock_drift" in c.flag for c in cav)
    assert any("s1" in c.sensor_id for c in cav)


def test_all_four_flag_kinds_are_carried():
    rows = [
        _row(1, {"clock_drift": True}),
        _row(2, {"interpolated_input": True}),
        _row(3, {"rate_mismatch": True}),
        _row(4, {"abnormal_quiet": True}),
    ]
    flags = {c.flag for c in collect_caveats(rows)}
    assert flags == {"clock_drift", "interpolated_input", "rate_mismatch", "abnormal_quiet"}


def test_false_flags_are_not_caveats():
    cav = collect_caveats([_row(1, {"clock_drift": False, "rate_mismatch": True})])
    flags = {c.flag for c in cav}
    assert flags == {"rate_mismatch"}          # only the True flag


def test_multiple_flags_on_one_result_all_surface():
    cav = collect_caveats([_row(1, {"clock_drift": True, "interpolated_input": True})])
    assert {c.flag for c in cav} == {"clock_drift", "interpolated_input"}


# --- propagation through the orchestrator into the explanation ---------------------------------
@dataclass
class FakeStore:
    rows: list = field(default_factory=list)
    standards: dict = field(default_factory=dict)

    def current_results_for(self, b, c):
        return [r for r in self.rows if r.bridge_id == b and r.cycle_id == c and r.superseded_by is None]

    def baseline_for(self, b, w):
        return []

    def standard_for(self, t):
        return self.standards.get(t)


class CaveatEchoModel:
    """A model stub that surfaces the caveats it is handed — proving they reach the context."""

    def draft(self, attempt, context):
        caveats = context.get("caveats", ())
        score = context.get("score")
        parts = [f"The risk score is {score}."]
        for c in caveats:
            parts.append(f"Caveat: {c.sensor_id} carried {c.flag}; treat as less trustworthy.")
        return " ".join(parts)


def _extractor(results, standard):
    return [FactorInput(r.calculation.lower(), r.id, float(r.result["value"]),
                        float(r.result["limit"])) for r in results if r.outcome == "RAN"]


def _assess(store):
    return assess_bridge(
        bridge_id="b1", cycle_id="c1", store=store, bridge_type="girder",
        score_config=ScoreConfig(score_weights_version="rev1", weights=(("rms", 1.0),),
                                 ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
                                 watch_min=25.0, warning_min=50.0, critical_min=75.0),
        coverage_config=CoverageConfig(coverage_floor=0.5, completeness_full_fraction=1.0),
        model=CaveatEchoModel(), factor_extractor=_extractor, expected_calc_count=1,
        model_id="m", model_version="v", trace_id="t",
    )


def test_caveat_reaches_explanation_via_context():
    store = FakeStore(rows=[_row(1, {"clock_drift": True})],
                      standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})})
    a = _assess(store)
    assert a.is_withheld is False
    assert "clock_drift" in a.explanation      # surfaced, not silently dropped (AC-8)
    assert "less trustworthy" in a.explanation


def test_clean_input_has_no_caveat_noise():
    store = FakeStore(rows=[_row(1, {})],
                      standards={"girder": StandardEntry("IRC:6", "2017", {"max": 1.0})})
    a = _assess(store)
    assert "Caveat:" not in a.explanation
