"""T905 — clock-drift detection (G4): a co-existing flag, not a value verdict.

Acceptance (tasks.md T905): gap > tolerance -> clock_drift=True + a CLOCK_DRIFT log
entry, AND the reading still flows through the normal checks (an in-range drifted
reading is still OK, just flagged); gap <= tolerance -> no flag, no log.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.checks.clock_drift import (
    ClockDriftResult,
    check_clock_drift,
)
from agents.data_collection.checks.range_check import check_range
from agents.data_collection.config.sensor_profiles import TODO, SensorProfile
from agents.data_collection.statuses import ReadingStatus

UTC = timezone.utc
SENSOR_TIME = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=0.0, phys_max=100.0,
    clock_drift_tolerance_s=5.0,
)


def ingest(offset_s: float) -> datetime:
    return SENSOR_TIME + timedelta(seconds=offset_s)


def test_gap_beyond_tolerance_flags_and_logs():
    res = check_clock_drift(SENSOR_TIME, ingest(10.0), PROFILE)  # 10s > 5s
    assert res.clock_drift is True
    assert res.evaluated is True
    assert res.log_required is True
    assert res.gap_s == 10.0
    assert "exceeds tolerance" in res.reason


def test_gap_within_tolerance_no_flag_no_log():
    res = check_clock_drift(SENSOR_TIME, ingest(3.0), PROFILE)  # 3s <= 5s
    assert res.clock_drift is False
    assert res.log_required is False
    assert res.evaluated is True


def test_negative_gap_uses_absolute_value():
    # Ingest BEFORE sensor_time (sensor clock ahead) still counts as drift magnitude.
    res = check_clock_drift(SENSOR_TIME, ingest(-12.0), PROFILE)
    assert res.gap_s == 12.0
    assert res.clock_drift is True


def test_exact_tolerance_is_not_drift():
    # Strict ">": a gap exactly at tolerance is within bounds.
    res = check_clock_drift(SENSOR_TIME, ingest(5.0), PROFILE)
    assert res.clock_drift is False


def test_drifted_in_range_reading_is_still_ok_just_flagged():
    # The defining G4 behaviour: drift co-exists with a normal value verdict.
    drift = check_clock_drift(SENSOR_TIME, ingest(30.0), PROFILE)
    rng = check_range(42.0, PROFILE)  # 42 is within [0, 100]
    assert drift.clock_drift is True              # timing flagged
    assert rng.status is ReadingStatus.OK         # value still OK, NOT replaced
    # The two axes co-exist: an OK reading that also carries clock_drift=True.


def test_drift_does_not_change_reading_status_for_corrupt_either():
    # Drift is orthogonal: an out-of-range value is CORRUPT regardless of drift.
    drift = check_clock_drift(SENSOR_TIME, ingest(30.0), PROFILE)
    rng = check_range(999.0, PROFILE)
    assert drift.clock_drift is True
    assert rng.status is ReadingStatus.CORRUPT     # decided by range, not drift


def test_todo_tolerance_not_evaluated_not_guessed():
    todo_profile = SensorProfile(
        "u", "x", cadence_s=60.0, phys_min=0.0, phys_max=1.0,
        clock_drift_tolerance_s=TODO,
    )
    res = check_clock_drift(SENSOR_TIME, ingest(9999.0), todo_profile)
    assert res.evaluated is False
    assert res.clock_drift is False  # cannot assert drift without a tolerance
    assert "todo" in res.reason.lower() or "unset" in res.reason.lower()


def test_missing_ingest_time_not_evaluated():
    res = check_clock_drift(SENSOR_TIME, None, PROFILE)
    assert res.evaluated is False
    assert res.clock_drift is False
    assert res.log_required is False


def test_returns_result_type():
    assert isinstance(check_clock_drift(SENSOR_TIME, ingest(1.0), PROFILE), ClockDriftResult)
