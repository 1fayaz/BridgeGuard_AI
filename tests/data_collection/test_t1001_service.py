"""T1001 — service invocation entrypoint (run_cycle).

Acceptance (tasks.md T1001): given a JSON batch, returns per-sensor statuses; a
malformed batch -> structured error, never a stack trace (FR-6).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.service import CycleSummary, run_cycle
from agents.data_collection.store import FakeStore

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
TEST_TYPE = "test_svc"
TEST_PROFILE = SensorProfile(
    sensor_type=TEST_TYPE, unit="x", cadence_s=60.0,
    phys_min=-100.0, phys_max=100.0, clock_drift_tolerance_s=5.0,
)


def setup_module(module):
    SENSOR_PROFILES[TEST_TYPE] = TEST_PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TEST_TYPE, None)


def payload(sensor_id, value):
    return {"sensor_id": sensor_id, "sensor_type": TEST_TYPE,
            "sensor_time": NOW.isoformat(), "value": value}


def registry(*ids):
    return SensorRegistry([ExpectedSensor(i, TEST_TYPE, "b") for i in ids])


def test_valid_batch_returns_per_sensor_statuses():
    store = FakeStore()
    reg = registry("a", "b")
    summary = run_cycle([payload("a", 5.0), payload("b", 7.0)], store, reg, {}, NOW)
    assert isinstance(summary, CycleSummary)
    assert summary.ok is True
    ids = {s.sensor_id for s in summary.sensors}
    assert ids == {"a", "b"}
    a = next(s for s in summary.sensors if s.sensor_id == "a")
    assert a.reading_status == "OK"
    assert a.sensor_health == "LIVE"


def test_summary_counts_and_raw_appended():
    store = FakeStore()
    reg = registry("a")
    summary = run_cycle([payload("a", 5.0)], store, reg, {}, NOW)
    assert summary.raw_appended == 1
    assert store.raw_count() == 1
    assert summary.validated_written == 1


def test_malformed_batch_not_a_list_is_structured_error():
    store = FakeStore()
    summary = run_cycle({"not": "a list"}, store, registry("a"), {}, NOW)
    assert summary.ok is False
    assert summary.error and "malformed batch" in summary.error
    assert summary.sensors == []   # no partial results


def test_none_batch_is_structured_error():
    summary = run_cycle(None, FakeStore(), registry("a"), {}, NOW)
    assert summary.ok is False
    assert "malformed batch" in summary.error


def test_malformed_readings_inside_batch_do_not_crash():
    # The batch envelope is valid (a list); individual junk is handled per-item.
    store = FakeStore()
    reg = registry("a")
    batch = ["garbage", payload("a", 5.0), {"sensor_id": 5}]
    summary = run_cycle(batch, store, reg, {}, NOW)
    assert summary.ok is True                      # batch still processed
    assert summary.parse_failures >= 1
    a = next(s for s in summary.sensors if s.sensor_id == "a")
    assert a.reading_status == "OK"                # good sensor still got a verdict


def test_empty_batch_returns_silent_sensors():
    store = FakeStore()
    reg = registry("silent")
    summary = run_cycle([], store, reg, {}, NOW)
    assert summary.ok is True
    s = summary.sensors[0]
    assert s.sensor_health == "OFFLINE"
    assert s.reading_status == "NO_DATA"


def test_state_advances_across_calls():
    store = FakeStore()
    reg = registry("a")
    states: dict = {}
    run_cycle([payload("a", 5.0)], store, reg, states, NOW)
    # Second cycle one cadence later; the caller's states dict was updated in place.
    assert "a" in states
    assert states["a"].last_seen == NOW
    later = NOW + timedelta(seconds=60)
    run_cycle([{**payload("a", 6.0), "sensor_time": later.isoformat()}],
              store, reg, states, later)
    assert states["a"].last_seen == later
    assert store.raw_count() == 2   # raw grew across both cycles


def test_summary_is_json_safe_scalars():
    # Statuses are plain strings, not enums, so the summary serialises cleanly for n8n.
    store = FakeStore()
    summary = run_cycle([payload("a", 5.0)], store, registry("a"), {}, NOW)
    s = summary.sensors[0]
    assert isinstance(s.sensor_health, str)
    assert isinstance(s.reading_status, str)
    assert isinstance(s.clock_drift, bool)
