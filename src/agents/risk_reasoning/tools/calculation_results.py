"""Tool 1 — get_calculation_results (R501, FR-3) — read-only.

Reads the Structural Analysis Agent's CURRENT (non-superseded) analysis_results for one bridge +
cycle and hands them to the reasoner. It never mutates an upstream record and never re-derives the
SA's facts (Principle III — it trusts its upstream contract). A scope with no results returns a
structured-empty result, never a raise.

[DB-DEP] The live source is SA's analysis_results table (migration 0005) + Supabase, neither of
which exists yet. The read is written against a small source PROTOCOL so it runs against an
in-memory fake now and a real Supabase-backed source later with no logic change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AnalysisResultRow:
    """One SA analysis_results row, as this agent reads it (mirrors the 0005 schema shape)."""

    id: int
    bridge_id: str
    cycle_id: str
    sensor_id: str
    calculation: str                       # RMS | FFT | DEFLECTION_LIMIT | THRESHOLD
    outcome: str                           # RAN | SKIPPED | ERROR
    reason_code: str | None
    result: dict[str, Any]                 # calc-specific payload (RMS scalar / FFT peaks / ratio)
    flags: dict[str, bool]                 # interpolated_input / clock_drift / rate_mismatch / abnormal_quiet
    source_validated_ids: list[int]        # provenance chain back to validated_readings (FR-9)
    superseded_by: int | None = None


class AnalysisSource(Protocol):
    """The read port this tool needs — implemented by the fake now, Supabase later."""

    def current_results_for(self, bridge_id: str, cycle_id: str) -> list[AnalysisResultRow]:
        ...


@dataclass(frozen=True, slots=True)
class CalculationResults:
    """The tool's structured return: the current results for the scope (possibly empty)."""

    results: tuple[AnalysisResultRow, ...]

    @property
    def is_empty(self) -> bool:
        return not self.results


def get_calculation_results(
    bridge_id: str,
    cycle_id: str,
    source: AnalysisSource,
) -> CalculationResults:
    """Read the current SA results for a bridge+cycle (FR-3, tool 1). Read-only; never raises."""
    rows = source.current_results_for(bridge_id, cycle_id)
    return CalculationResults(results=tuple(rows))
