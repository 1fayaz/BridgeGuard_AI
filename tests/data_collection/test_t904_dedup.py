"""T904 — dedup (first-wins + conflict log) + out-of-order ordering (AC-7 / G4).

Acceptance (tasks.md T904): an identical duplicate collapses to one logical reading;
a conflicting duplicate keeps the first-received value, discards the second, and logs
DUPLICATE_CONFLICT with BOTH values + the exact reason string; out-of-order readings
are sorted by sensor timestamp. No averaging.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.dedup import (
    DUPLICATE_CONFLICT_REASON,
    DedupResult,
    dedup_and_order,
)
from agents.data_collection.parsing import ParsedReading

UTC = timezone.utc
T0 = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def reading(sensor_id: str, secs: int, value: float | None) -> ParsedReading:
    return ParsedReading(
        sensor_id=sensor_id,
        sensor_type="t",
        sensor_time=T0 + timedelta(seconds=secs),
        value=value,
        ingest_time=None,
        raw_payload={},
    )


def test_identical_duplicate_collapses_to_one():
    batch = [reading("s", 0, 5.0), reading("s", 0, 5.0)]
    res = dedup_and_order(batch)
    assert len(res.readings) == 1
    assert res.conflicts == []           # identical -> no conflict logged


def test_conflicting_duplicate_first_wins_and_logs_both_values():
    batch = [reading("s", 0, 5.0), reading("s", 0, 9.0)]  # arrival order: 5.0 first
    res = dedup_and_order(batch)
    assert len(res.readings) == 1
    assert res.readings[0].value == 5.0   # first-received kept
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert c.kept_value == 5.0
    assert c.discarded_value == 9.0       # BOTH values recorded
    assert c.reason == DUPLICATE_CONFLICT_REASON  # exact canonical string


def test_no_averaging():
    # The kept value must be exactly the first, never a mean of the two.
    res = dedup_and_order([reading("s", 0, 10.0), reading("s", 0, 20.0)])
    assert res.readings[0].value == 10.0   # not 15.0
    assert res.conflicts[0].kept_value == 10.0


def test_out_of_order_sorted_by_sensor_timestamp():
    batch = [reading("s", 30, 3.0), reading("s", 0, 1.0), reading("s", 15, 2.0)]
    res = dedup_and_order(batch)
    times = [r.sensor_time for r in res.readings]
    assert times == sorted(times)         # chronological by sensor ts
    assert [r.value for r in res.readings] == [1.0, 2.0, 3.0]


def test_first_received_decided_before_sort():
    # Arrival order (not timestamp order) breaks the tie. Both at the SAME timestamp;
    # arrival order is 7.0 then 8.0 -> 7.0 wins regardless of value magnitude.
    res = dedup_and_order([reading("s", 0, 7.0), reading("s", 0, 8.0)])
    assert res.readings[0].value == 7.0
    assert res.conflicts[0].discarded_value == 8.0


def test_different_sensors_same_timestamp_not_deduped():
    batch = [reading("s-1", 0, 1.0), reading("s-2", 0, 2.0)]
    res = dedup_and_order(batch)
    assert len(res.readings) == 2          # different sensors -> both kept
    assert res.conflicts == []


def test_different_timestamps_same_sensor_not_deduped():
    res = dedup_and_order([reading("s", 0, 1.0), reading("s", 60, 1.0)])
    assert len(res.readings) == 2


def test_three_way_conflict_logs_each_discard():
    # First wins; the 2nd and 3rd conflicting values are each logged as discarded.
    batch = [reading("s", 0, 1.0), reading("s", 0, 2.0), reading("s", 0, 3.0)]
    res = dedup_and_order(batch)
    assert res.readings[0].value == 1.0
    assert len(res.conflicts) == 2
    assert {c.discarded_value for c in res.conflicts} == {2.0, 3.0}


def test_empty_batch():
    res = dedup_and_order([])
    assert res.readings == []
    assert res.conflicts == []


def test_returns_dedup_result_type():
    assert isinstance(dedup_and_order([reading("s", 0, 1.0)]), DedupResult)
