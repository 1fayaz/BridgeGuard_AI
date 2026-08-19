"""R502 — get_historical_baseline(bridge_id, window, source) read-only tool (FR-3, tool 2).

[DB-DEP] The live baseline source (sensor-comparison data / prior risk_assessments) does not exist
yet, so the read runs against an in-memory fake. The tool's contract IS verifiable now: returns
the bridge's baseline rows for the window; a no-history bridge -> structured "no baseline" signal
(cold-start trend, not a raise); performs NO mutation.

Open Item (deferred to plan.md): the EXACT baseline contract shape (which sensor-comparison fields,
over what window). This builds a minimal, honest shape — enough for trend context + cold-start —
and is intentionally light so the real contract can fill it in without reshaping the call site.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.risk_reasoning.tools.historical_baseline import (
    get_historical_baseline,
    BaselinePoint,
)


@dataclass
class FakeBaselineSource:
    points: list[BaselinePoint] = field(default_factory=list)
    read_calls: int = 0
    mutated: bool = False

    def baseline_for(self, bridge_id: str, window: str) -> list[BaselinePoint]:
        self.read_calls += 1
        return [p for p in self.points if p.bridge_id == bridge_id]


def _pt(bridge="b1", ref="2026-06-01", score=40) -> BaselinePoint:
    return BaselinePoint(bridge_id=bridge, reference=ref, prior_score=score)


def test_returns_baseline_points_for_bridge():
    src = FakeBaselineSource(points=[_pt(score=40), _pt(ref="2026-06-15", score=45)])
    out = get_historical_baseline("b1", "30d", src)
    assert out.has_baseline is True
    assert len(out.points) == 2


def test_no_history_is_structured_cold_start_not_a_raise():
    src = FakeBaselineSource(points=[])
    out = get_historical_baseline("b1", "30d", src)
    assert out.points == ()
    assert out.has_baseline is False           # cold-start trend, no exception


def test_scopes_by_bridge():
    src = FakeBaselineSource(points=[_pt(bridge="b1"), _pt(bridge="b2")])
    out = get_historical_baseline("b1", "30d", src)
    assert all(p.bridge_id == "b1" for p in out.points)
    assert len(out.points) == 1


def test_read_only_does_not_mutate_source():
    src = FakeBaselineSource(points=[_pt(), _pt(ref="2026-06-15")])
    get_historical_baseline("b1", "30d", src)
    assert src.mutated is False
    assert len(src.points) == 2


def test_baseline_reference_is_carried_for_provenance():
    # The baseline_ref pins WHICH baseline the assessment used (FR-9/FR-10).
    src = FakeBaselineSource(points=[_pt(ref="2026-06-01-30d")])
    out = get_historical_baseline("b1", "30d", src)
    assert out.points[0].reference == "2026-06-01-30d"
