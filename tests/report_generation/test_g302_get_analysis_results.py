"""G302 — get_analysis_results(source_analysis_ids) — read-only.

Reads the SA analysis_results rows (0005) named by the assessment's `source_analysis_ids`
(current versions), for the report's sensor tables + math-results section. The agent renders these
values verbatim — it never recomputes them (FR-1). Read-only; a missing/empty set returns a
structured "results unavailable" signal that drives a SECTION_UNAVAILABLE mark (FR-6), never a
raise.

Acceptance (tasks.md G302): returns the referenced current rows; a missing id -> the section-gap
signal (no fabrication); no mutation.
"""
from __future__ import annotations

from agents.report_generation.tools.analysis_results_read import (
    AnalysisResultsReadResult,
    get_analysis_results,
)


class FakeAnalysisSource:
    def __init__(self, rows):
        self._by_id = {r["id"]: r for r in rows}
        self.mutations = 0

    def analysis_results_by_ids(self, ids):
        # Returns current rows for the ids it knows; silently omits unknown ids (caller detects gap).
        return [dict(self._by_id[i]) for i in ids if i in self._by_id]


def _row(rid, **over):
    base = dict(
        id=rid,
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        sensor_id=f"sensor-{rid}",
        calculation="DEFLECTION_LIMIT",
        outcome="RAN",
        result={"ratio": 0.62},
        source_validated_ids=[rid * 10],
        superseded_by=None,
    )
    base.update(over)
    return base


# ------------------------------------------------------------------ hit ---
def test_returns_the_referenced_rows_in_order():
    src = FakeAnalysisSource([_row(11), _row(12)])
    res = get_analysis_results((11, 12), src)
    assert res.available is True
    assert [r["id"] for r in res.results] == [11, 12]
    assert res.missing_ids == ()


def test_carries_source_validated_ids_for_the_readings_chain():
    src = FakeAnalysisSource([_row(11), _row(12)])
    res = get_analysis_results((11, 12), src)
    chained = [vid for r in res.results for vid in r["source_validated_ids"]]
    assert chained == [110, 120]  # feeds G303's validated_readings read


# ------------------------------------------------------------------ gaps ---
def test_empty_id_set_is_section_unavailable():
    # The assessment referenced no analysis rows -> the section cannot be built, not fabricated.
    src = FakeAnalysisSource([_row(11)])
    res = get_analysis_results((), src)
    assert res.available is False
    assert res.results == ()


def test_a_missing_id_marks_section_unavailable_and_names_the_gap():
    # 12 is referenced but absent from the store -> section-gap signal names it; no fabrication.
    src = FakeAnalysisSource([_row(11)])
    res = get_analysis_results((11, 12), src)
    assert res.available is False
    assert 12 in res.missing_ids
    assert [r["id"] for r in res.results] == [11]  # only what genuinely exists


def test_all_ids_missing_is_section_unavailable():
    src = FakeAnalysisSource([])
    res = get_analysis_results((11, 12), src)
    assert res.available is False
    assert set(res.missing_ids) == {11, 12}
    assert res.results == ()


# ------------------------------------------------------------------ read-only ---
def test_read_performs_no_mutation():
    src = FakeAnalysisSource([_row(11), _row(12)])
    get_analysis_results((11, 12), src)
    assert src.mutations == 0


def test_returned_rows_are_copies():
    src = FakeAnalysisSource([_row(11)])
    res = get_analysis_results((11,), src)
    res.results[0]["result"]["ratio"] = 9.99
    again = get_analysis_results((11,), src)
    assert again.results[0]["result"]["ratio"] == 0.62
