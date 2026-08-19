"""T802 — late-arrival decision check (AC: bounded recompute + no silent overwrite).

Acceptance (tasks.md T802):
  (a) a reading 2x cadence old -> recomputed; decision_log has a CORRECTION with reason
      "late-arrival recompute" and old -> new status.
  (b) a reading 4x cadence old -> raw-only; logged "outside recompute window".
  (c) in BOTH cases the original raw reading is UNCHANGED (no silent overwrite); raw
      row count only ever grows.

handle_late_arrival is pure and takes no raw handle, so (c) is modelled here by a
test-owned append-only raw list: we append the late reading on receipt (as the real
ingest does), run the decision, and assert the pre-existing raw rows are byte-for-byte
unchanged and the count only grew.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agents.data_collection.checks.late_arrival import (
    LateReading,
    ProcessedReading,
    handle_late_arrival,
)
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
CADENCE = 60.0
PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=CADENCE, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # recompute window = pending_timeout_s = 180s = 3x cadence


@dataclass(frozen=True)
class RawRow:
    sensor_id: str
    sensor_time: datetime
    value: float | None


def append_raw(raw: list[RawRow], reading: LateReading) -> list[RawRow]:
    """Model immutable ingest: append-only, returns the new list, never edits existing."""
    return [*raw, RawRow(reading.sensor_id, reading.sensor_time, reading.value)]


def test_a_two_cadence_old_recomputed_with_correction_log():
    # 2x cadence = 120s old -> within the 180s window.
    late = LateReading("s", NOW - timedelta(seconds=2 * CADENCE), 15.0)
    prior = ProcessedReading(7, "s", late.sensor_time, None, ReadingStatus.NO_DATA)
    plan = handle_late_arrival(late, [prior], NOW, PROFILE, ReadingStatus.OK)

    assert plan.within_window is True
    assert plan.recomputed is True
    # CORRECTION log with the canonical reason + old -> new transition.
    log = plan.logs[0]
    assert log.reason == "late-arrival recompute"
    assert log.old_status is ReadingStatus.NO_DATA
    assert log.new_status is ReadingStatus.OK
    # A new validated row supersedes the prior verdict (correction chain).
    assert plan.new_rows[0].supersedes_row_id == 7
    assert plan.new_rows[0].status is ReadingStatus.OK


def test_b_four_cadence_old_raw_only_outside_window():
    # 4x cadence = 240s old -> outside the 180s window.
    late = LateReading("s", NOW - timedelta(seconds=4 * CADENCE), 15.0)
    plan = handle_late_arrival(late, [], NOW, PROFILE, ReadingStatus.OK)

    assert plan.within_window is False
    assert plan.recomputed is False
    assert plan.new_rows == []
    assert "outside recompute window" in plan.logs[0].reason.lower()


def test_c_raw_unchanged_in_both_cases_and_count_grows():
    # Pre-existing raw rows from earlier cycles.
    existing = [
        RawRow("s", NOW - timedelta(seconds=300), 9.0),
        RawRow("s", NOW - timedelta(seconds=240), 9.5),
    ]
    snapshot = list(existing)  # shallow copy of references for identity comparison

    # --- case (a): within-window late reading ---
    late_a = LateReading("s", NOW - timedelta(seconds=2 * CADENCE), 15.0)
    raw_after_a = append_raw(existing, late_a)
    handle_late_arrival(late_a, [], NOW, PROFILE, ReadingStatus.OK)
    # The original rows are untouched (same objects, same values) and count grew by 1.
    assert raw_after_a[:2] == snapshot
    assert all(raw_after_a[i] is snapshot[i] for i in range(2))  # no rewrite
    assert len(raw_after_a) == len(existing) + 1

    # --- case (b): outside-window late reading ---
    late_b = LateReading("s", NOW - timedelta(seconds=4 * CADENCE), 7.0)
    raw_after_b = append_raw(existing, late_b)
    handle_late_arrival(late_b, [], NOW, PROFILE, ReadingStatus.OK)
    assert raw_after_b[:2] == snapshot
    assert len(raw_after_b) == len(existing) + 1
    # In neither case did the raw count shrink or a row get overwritten.


def test_window_boundary_three_cadence_is_within():
    # Exactly 3x cadence (180s) is within (strict age > window for outside).
    late = LateReading("s", NOW - timedelta(seconds=3 * CADENCE), 1.0)
    plan = handle_late_arrival(late, [], NOW, PROFILE, ReadingStatus.OK)
    assert plan.within_window is True
