"""Fix #8 (PREEMPTIVE) — insert_validated must own the row id, not trust the caller's.

insert_validated() appended the row with whatever row_id the caller put on it, then bumped
_next_row_id independently. persist_cycle happens to pass store._next_row_id, so today the
two stay in lockstep and there is NO observed live bug. But the id authority belongs to the
store: a future caller (late-arrival correction persistence, T801, not yet wired to a real
store) that constructs a ValidatedRow with a guessed/duplicate/stale id would silently
create colliding ids. Making insert_validated stamp the id itself removes that whole class
of desync at the boundary. This is a small, safe, defensive change — documented as a guard
for a not-yet-built caller, NOT a fix of a confirmed failure.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.data_collection.statuses import ReadingStatus
from agents.data_collection.store import FakeStore, ValidatedRow

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _row(row_id: int, sensor_id: str = "s") -> ValidatedRow:
    return ValidatedRow(
        row_id=row_id, sensor_id=sensor_id, sensor_time=NOW, value=1.0,
        status=ReadingStatus.OK, is_interpolated=False, clock_drift=False,
        source_raw_ids=(), reason="ok",
    )


def test_store_assigns_id_ignoring_caller_value():
    store = FakeStore()
    # Caller hands in a bogus, colliding id on every row. The store must IGNORE it and
    # assign monotonic unique ids itself.
    id1 = store.insert_validated(_row(999))
    id2 = store.insert_validated(_row(999))
    id3 = store.insert_validated(_row(0))
    assert [id1, id2, id3] == [1, 2, 3], "store must assign sequential ids, not trust caller"
    stored = [r.row_id for r in store.validated_rows]
    assert stored == [1, 2, 3], "persisted rows carry the store-assigned ids"
    assert len(set(stored)) == 3, "no id collisions even when caller passes duplicates"


def test_returned_id_matches_persisted_row():
    store = FakeStore()
    rid = store.insert_validated(_row(42))
    assert store.validated_rows[-1].row_id == rid, "returned id must match the stored row"
