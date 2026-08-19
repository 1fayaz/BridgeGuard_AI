"""R504 — the three tools are three distinct read-only fetches that mutate nothing (AC-3).

Acceptance (tasks.md R504): each tool returns its typed result against the fake source; each leaves
all stores unmutated (before == after); each returns a structured signal (not a raise) on missing
data. = AC-3 (three distinct read-only fetches, mutates nothing).

Pure integration over the three already-built tools — no new production code.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from agents.risk_reasoning.tools.calculation_results import (
    get_calculation_results, AnalysisResultRow,
)
from agents.risk_reasoning.tools.historical_baseline import (
    get_historical_baseline, BaselinePoint,
)
from agents.risk_reasoning.tools.engineering_standard import (
    get_engineering_standard, StandardEntry,
)


# --- minimal fakes (one per source) -----------------------------------------------------------
@dataclass
class FakeAnalysisSource:
    rows: list[AnalysisResultRow] = field(default_factory=list)

    def current_results_for(self, bridge_id, cycle_id):
        return [r for r in self.rows
                if r.bridge_id == bridge_id and r.cycle_id == cycle_id and r.superseded_by is None]


@dataclass
class FakeBaselineSource:
    points: list[BaselinePoint] = field(default_factory=list)

    def baseline_for(self, bridge_id, window):
        return [p for p in self.points if p.bridge_id == bridge_id]


@dataclass
class FakeStandardSource:
    entries: dict[str, StandardEntry] = field(default_factory=dict)

    def standard_for(self, bridge_type):
        return self.entries.get(bridge_type)


def _analysis_row():
    return AnalysisResultRow(
        id=1, bridge_id="b1", cycle_id="c1", sensor_id="s1", calculation="RMS",
        outcome="RAN", reason_code=None, result={"rms": 0.42}, flags={},
        source_validated_ids=[1], superseded_by=None,
    )


def _populated_sources():
    return (
        FakeAnalysisSource(rows=[_analysis_row()]),
        FakeBaselineSource(points=[BaselinePoint("b1", "2026-06-01", 40)]),
        FakeStandardSource(entries={"girder": StandardEntry("IRC:6", "2017", {"max_strain": 500.0})}),
    )


def test_three_distinct_fetches_each_return_typed_results():
    calc_src, base_src, std_src = _populated_sources()
    calc = get_calculation_results("b1", "c1", calc_src)
    base = get_historical_baseline("b1", "30d", base_src)
    std = get_engineering_standard("girder", std_src)

    assert calc.is_empty is False
    assert base.has_baseline is True
    assert std.available is True
    # Three SEPARATE retrievals — distinct return types, no shared state.
    assert type(calc).__name__ == "CalculationResults"
    assert type(base).__name__ == "HistoricalBaseline"
    assert type(std).__name__ == "EngineeringStandard"


def test_none_of_the_three_mutate_their_source():
    calc_src, base_src, std_src = _populated_sources()
    before = (copy.deepcopy(calc_src), copy.deepcopy(base_src), copy.deepcopy(std_src))

    get_calculation_results("b1", "c1", calc_src)
    get_historical_baseline("b1", "30d", base_src)
    get_engineering_standard("girder", std_src)

    assert calc_src == before[0]    # AC-3: mutates nothing
    assert base_src == before[1]
    assert std_src == before[2]


def test_each_returns_structured_signal_on_missing_data_no_raise():
    # Empty sources -> structured "absent" results, never an exception.
    calc = get_calculation_results("b1", "c1", FakeAnalysisSource())
    base = get_historical_baseline("b1", "30d", FakeBaselineSource())
    std = get_engineering_standard("girder", FakeStandardSource())

    assert calc.is_empty is True
    assert base.has_baseline is False
    assert std.available is False
    assert std.reason                # the standard gap is named (drives FR-6)


def test_tools_are_independent_one_missing_does_not_affect_others():
    # Calc + standard present, baseline absent — each result reflects only its own source.
    calc_src, _, std_src = _populated_sources()
    calc = get_calculation_results("b1", "c1", calc_src)
    base = get_historical_baseline("b1", "30d", FakeBaselineSource())  # empty
    std = get_engineering_standard("girder", std_src)

    assert calc.is_empty is False
    assert base.has_baseline is False
    assert std.available is True
