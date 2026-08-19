"""Fix #3 — multiple distinct-timestamp readings for one sensor must not be dropped.

dedup_and_order keeps readings with the same sensor_id but different sensor_time. The
orchestrator then collapsed them with `{r.sensor_id: r for r in ...}`, keeping only the
newest and silently dropping the rest — no verdict, no log, no provenance. Under MQTT
at-least-once + buffering, a batch routinely carries several samples per sensor. Each
must be evaluated and persisted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.service import run_cycle
from agents.data_collection.statuses import ReadingStatus
from agents.data_collection.store import FakeStore

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
TYPE = "multi_type"
PROFILE = SensorProfile(TYPE, "x", cadence_s=60.0, phys_min=-100.0, phys_max=100.0,
                        clock_drift_tolerance_s=5.0)


def setup_module(module):
    SENSOR_PROFILES[TYPE] = PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TYPE, None)


def reg(*ids):
    return SensorRegistry([ExpectedSensor(i, TYPE, "b") for i in ids])


def payload(sensor_id, secs, value):
    return {"sensor_id": sensor_id, "sensor_type": TYPE,
            "sensor_time": (NOW + timedelta(seconds=secs)).isoformat(), "value": value}


def test_both_readings_get_a_validated_row():
    # One sensor sends two distinct-timestamp readings in one batch. Both must be
    # persisted as validated rows — neither silently dropped.
    store = FakeStore()
    batch = [payload("s", -60, 5.0), payload("s", 0, 6.0)]  # 12:59:00 and 13:00:00
    summary = run_cycle(batch, store, reg("s"), {}, NOW)
    assert summary.ok is True
    rows = [r for r in store.validated_rows if r.sensor_id == "s"]
    assert len(rows) == 2, "both readings must produce a validated row"
    times = sorted(r.sensor_time for r in rows)
    assert times[0] == NOW - timedelta(seconds=60)
    assert times[1] == NOW


def test_earlier_corrupt_reading_is_not_masked_by_later_ok():
    # Reading 1 is out of range (CORRUPT), reading 2 is fine. The CORRUPT verdict must
    # be recorded, not overwritten/dropped by the later OK reading.
    store = FakeStore()
    batch = [payload("s", -60, 9999.0), payload("s", 0, 6.0)]
    run_cycle(batch, store, reg("s"), {}, NOW)
    statuses = {r.status for r in store.validated_rows if r.sensor_id == "s"}
    assert ReadingStatus.CORRUPT in statuses, "earlier CORRUPT reading must be recorded"
    assert ReadingStatus.OK in statuses, "later OK reading must also be recorded"


def test_a_corrupt_reading_logs_range_decision():
    store = FakeStore()
    batch = [payload("s", -60, 9999.0), payload("s", 0, 6.0)]
    run_cycle(batch, store, reg("s"), {}, NOW)
    assert any(l.decision == "RANGE" for l in store.logs_for("s"))
