"""R501 — get_calculation_results(bridge_id, cycle_id, source) read-only tool (FR-3, tool 1).

[DB-DEP] SA's analysis_results table (migration 0005) and a live Supabase do not exist yet, so the
read runs against an in-memory fake source mirroring the documented analysis_results shape. The
tool's contract IS verifiable now: returns the bridge+cycle's CURRENT (non-superseded) results
with their outcome/reason_code/result/flags/source_validated_ids; excludes superseded rows; empty
scope -> structured empty (not a raise); performs NO mutation.

The @function_tool decoration + SDK wiring is deferred to R701 [LLM-DEP] — note the SDK's top-level
import name `agents` collides with this repo's own `agents` package, a packaging decision for R701.
Here the read logic is a plain, injectable function (same pure-logic discipline as DCA/SA).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.risk_reasoning.tools.calculation_results import (
    get_calculation_results,
    AnalysisResultRow,
)


@dataclass
class FakeAnalysisSource:
    """In-memory stand-in for SA's analysis_results (mirrors the 0005 schema shape)."""

    rows: list[AnalysisResultRow] = field(default_factory=list)
    read_calls: int = 0
    mutated: bool = False

    def current_results_for(self, bridge_id: str, cycle_id: str) -> list[AnalysisResultRow]:
        self.read_calls += 1
        return [
            r for r in self.rows
            if r.bridge_id == bridge_id and r.cycle_id == cycle_id and r.superseded_by is None
        ]


def _row(rid, bridge="b1", cycle="c1", calc="RMS", outcome="RAN", superseded_by=None,
         reason_code=None, result=None, flags=None, src_ids=(1,)) -> AnalysisResultRow:
    return AnalysisResultRow(
        id=rid, bridge_id=bridge, cycle_id=cycle, sensor_id=f"s{rid}",
        calculation=calc, outcome=outcome, reason_code=reason_code,
        result=result or {"rms": 0.42}, flags=flags or {}, source_validated_ids=list(src_ids),
        superseded_by=superseded_by,
    )


def test_returns_current_results_for_scope():
    src = FakeAnalysisSource(rows=[_row(1), _row(2, calc="FFT")])
    out = get_calculation_results("b1", "c1", src)
    assert {r.id for r in out.results} == {1, 2}
    assert out.is_empty is False


def test_excludes_superseded_rows():
    src = FakeAnalysisSource(rows=[_row(1), _row(2, superseded_by=9)])
    out = get_calculation_results("b1", "c1", src)
    assert {r.id for r in out.results} == {1}   # superseded row 2 excluded


def test_scopes_by_bridge_and_cycle():
    src = FakeAnalysisSource(rows=[
        _row(1, bridge="b1", cycle="c1"),
        _row(2, bridge="b2", cycle="c1"),
        _row(3, bridge="b1", cycle="c2"),
    ])
    out = get_calculation_results("b1", "c1", src)
    assert {r.id for r in out.results} == {1}


def test_surfaces_outcome_reason_flags_and_provenance():
    src = FakeAnalysisSource(rows=[
        _row(1, outcome="SKIPPED", reason_code="NO_CHANGE",
             flags={"clock_drift": True}, src_ids=(11, 12)),
    ])
    out = get_calculation_results("b1", "c1", src)
    r = out.results[0]
    assert r.outcome == "SKIPPED"
    assert r.reason_code == "NO_CHANGE"
    assert r.flags.get("clock_drift") is True
    assert r.source_validated_ids == [11, 12]   # provenance carried through (FR-9)


def test_empty_scope_is_structured_empty_not_a_raise():
    src = FakeAnalysisSource(rows=[])
    out = get_calculation_results("b1", "c1", src)
    assert out.results == ()
    assert out.is_empty is True                 # structured, no exception


def test_read_only_does_not_mutate_source():
    src = FakeAnalysisSource(rows=[_row(1), _row(2)])
    get_calculation_results("b1", "c1", src)
    assert src.mutated is False
    # The source's row list is unchanged (no pops/edits).
    assert {r.id for r in src.rows} == {1, 2}
