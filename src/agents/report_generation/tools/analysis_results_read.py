"""Read port — get_analysis_results(source_analysis_ids) (G302) — read-only.

Reads the Structural Analysis Agent's analysis_results rows (0005) named by an assessment's
`source_analysis_ids`, for the report's sensor tables + math-results section. The agent renders
these numbers verbatim — it never recomputes the SA's facts (FR-1, Principle III). Read-only; if
the id set is empty or any referenced id is absent, the read returns a structured "results
unavailable" signal that drives a SECTION_UNAVAILABLE mark (FR-6) — it never fabricates a row.

[DB-DEP] The live source is SA's analysis_results table (0005) + Neon, neither of which exists
locally. The read is written against a source PROTOCOL so it runs against an in-memory fake now.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Protocol


class AnalysisResultsSource(Protocol):
    """The read port this tool needs — implemented by the fake now, Neon later."""

    def analysis_results_by_ids(self, ids: tuple[int, ...]) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True, slots=True)
class AnalysisResultsReadResult:
    """Structured result: the referenced rows, plus which requested ids were missing.

    `available` is True only when EVERY requested id was found and at least one id was requested;
    otherwise the report's analysis section is marked unavailable rather than partially fabricated.
    """

    available: bool
    results: tuple[dict[str, Any], ...]
    missing_ids: tuple[int, ...]


def get_analysis_results(
    source_analysis_ids: tuple[int, ...],
    source: AnalysisResultsSource,
) -> AnalysisResultsReadResult:
    """Read the SA analysis rows an assessment referenced (G302). Read-only; never raises."""
    requested = tuple(source_analysis_ids)
    rows = source.analysis_results_by_ids(requested)
    # Deep-copy so a caller mutating a nested payload cannot corrupt the store's row.
    found = tuple(copy.deepcopy(r) for r in rows)

    found_ids = {r["id"] for r in found}
    missing = tuple(i for i in requested if i not in found_ids)

    # Available only when something was requested AND nothing referenced is missing.
    available = bool(requested) and not missing
    return AnalysisResultsReadResult(available=available, results=found, missing_ids=missing)
