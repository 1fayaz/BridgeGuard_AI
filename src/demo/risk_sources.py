"""The demo adapter for Risk's three read-only tool protocols (specs/005-demo-mode-and-approval
§1.3, FR-1.6).

Wraps exactly one SA `DemoAnalysisResult` (`agents.structural_analysis.demo_calc`) to satisfy
`AnalysisSource`/`BaselineSource`/`StandardSource` (`agents.risk_reasoning.tools.*`) — the same
three protocols `assess_bridge` already reads through, unmodified. One object implements all three,
the same pattern the existing test harnesses (`tests/risk_reasoning/_harness.py`'s `HarnessStore`)
already use. No baseline (cold start); a minimal always-available standard, since the demo scenario
is fixed and does not exercise the standard-missing withhold path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import StandardEntry
from agents.structural_analysis.demo_calc import DemoAnalysisResult

DEMO_BRIDGE_TYPE = "demo-fixture"


def _as_analysis_result_row(row: DemoAnalysisResult) -> AnalysisResultRow:
    """Convert SA's own demo shape into Risk's expected tool-read shape. Pure, no logic of its own —
    SA and Risk stay independent (Principle III); this is the one place that knows both shapes."""
    return AnalysisResultRow(
        id=row.id, bridge_id=row.bridge_id, cycle_id=row.cycle_id, sensor_id=row.sensor_id,
        calculation=row.calculation, outcome=row.outcome, reason_code=row.reason_code,
        result=dict(row.result), flags=dict(row.flags),
        source_validated_ids=list(row.source_validated_ids), superseded_by=row.superseded_by,
    )


@dataclass
class DemoRiskSources:
    """One demo analysis result, read through all three of Risk's tool protocols."""

    analysis_row: DemoAnalysisResult
    standards: dict[str, StandardEntry] = field(
        default_factory=lambda: {DEMO_BRIDGE_TYPE: StandardEntry("DEMO", "v1", {})}
    )

    def current_results_for(self, bridge_id: str, cycle_id: str) -> list[AnalysisResultRow]:
        if bridge_id != self.analysis_row.bridge_id or cycle_id != self.analysis_row.cycle_id:
            return []
        return [_as_analysis_result_row(self.analysis_row)]

    def baseline_for(self, bridge_id: str, window: str) -> list:
        return []  # cold start — the demo has no history to trend against.

    def standard_for(self, bridge_type: str) -> StandardEntry | None:
        return self.standards.get(bridge_type)
