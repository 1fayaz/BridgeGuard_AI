"""G303 — get_validated_readings(source_validated_ids, *, max_rows) — read-only.

Reads the DCA validated_readings (0002) named by the SA rows' `source_validated_ids`, for the
report's time-series tables/charts + raw-data appendix. Bounded to `max_rows` (the appendix depth
bound from ReportConfig, so a giant appendix cannot exhaust memory). The agent renders these
values verbatim — it never recomputes them (FR-1). Read-only; a missing set returns a structured
section-gap signal (FR-6), never a raise; truncation to the bound is flagged, not silent.

Acceptance (tasks.md G303): returns the referenced readings up to max_rows (bound honoured,
truncation flagged); missing -> gap signal; no mutation.
"""
from __future__ import annotations

from agents.report_generation.tools.validated_readings_read import (
    ValidatedReadingsReadResult,
    get_validated_readings,
)


class FakeReadingsSource:
    def __init__(self, rows):
        self._by_id = {r["id"]: r for r in rows}
        self.mutations = 0

    def validated_readings_by_ids(self, ids):
        return [dict(self._by_id[i]) for i in ids if i in self._by_id]


def _reading(rid, **over):
    base = dict(
        id=rid,
        sensor_id="sensor-1",
        sensor_time=f"2026-07-06T00:00:{rid:02d}Z",
        value=1.0 + rid,
        unit="mm",
        superseded_by=None,
    )
    base.update(over)
    return base


# ------------------------------------------------------------------ hit ---
def test_returns_referenced_readings_within_bound():
    src = FakeReadingsSource([_reading(1), _reading(2), _reading(3)])
    res = get_validated_readings((1, 2, 3), src, max_rows=10)
    assert res.available is True
    assert [r["id"] for r in res.readings] == [1, 2, 3]
    assert res.truncated is False
    assert res.missing_ids == ()


# ------------------------------------------------------------------ bound ---
def test_truncates_to_max_rows_and_flags_it():
    src = FakeReadingsSource([_reading(i) for i in range(1, 11)])  # 10 readings
    res = get_validated_readings(tuple(range(1, 11)), src, max_rows=4)
    assert res.available is True          # data exists; it is just capped for the appendix
    assert len(res.readings) == 4
    assert res.truncated is True
    assert res.total_available == 10      # the honest full count, for the "N of M shown" note


def test_bound_of_zero_shows_no_rows_but_is_not_a_gap():
    # A zero appendix bound is a presentation choice, not missing data.
    src = FakeReadingsSource([_reading(1), _reading(2)])
    res = get_validated_readings((1, 2), src, max_rows=0)
    assert res.readings == ()
    assert res.truncated is True
    assert res.total_available == 2
    assert res.available is True


# ------------------------------------------------------------------ gaps ---
def test_empty_id_set_is_section_unavailable():
    src = FakeReadingsSource([_reading(1)])
    res = get_validated_readings((), src, max_rows=10)
    assert res.available is False
    assert res.readings == ()


def test_a_missing_id_marks_section_unavailable_and_names_the_gap():
    src = FakeReadingsSource([_reading(1)])
    res = get_validated_readings((1, 2), src, max_rows=10)
    assert res.available is False
    assert 2 in res.missing_ids
    assert [r["id"] for r in res.readings] == [1]  # only what exists


# ------------------------------------------------------------------ read-only ---
def test_read_performs_no_mutation():
    src = FakeReadingsSource([_reading(1), _reading(2)])
    get_validated_readings((1, 2), src, max_rows=10)
    assert src.mutations == 0


def test_returned_readings_are_copies():
    src = FakeReadingsSource([_reading(1)])
    res = get_validated_readings((1,), src, max_rows=10)
    res.readings[0]["value"] = 999.0
    again = get_validated_readings((1,), src, max_rows=10)
    assert again.readings[0]["value"] == 2.0
