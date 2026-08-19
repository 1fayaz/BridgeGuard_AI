"""Fix #2 — tz-naive timestamps must not crash the cycle (code-review finding).

_coerce_time returned a NAIVE datetime for an offset-less ISO string but an AWARE one
for a 'Z' suffix. A batch mixing both formats (normal under MQTT from heterogeneous
devices) made dedup's `sorted(key=sensor_time)` raise TypeError, blinding the whole
cycle. Every parsed timestamp must be normalized to a consistent (UTC-aware) form.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.parsing import ParsedReading, safe_parse
from agents.data_collection.service import run_cycle
from agents.data_collection.store import FakeStore

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
TYPE = "tz_type"
PROFILE = SensorProfile(TYPE, "x", cadence_s=60.0, phys_min=-100.0, phys_max=100.0,
                        clock_drift_tolerance_s=5.0)


def setup_module(module):
    SENSOR_PROFILES[TYPE] = PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TYPE, None)


def test_coerce_time_normalizes_offsetless_to_aware():
    # Offset-less string must parse to a tz-AWARE datetime (UTC assumed), not naive.
    res = safe_parse({"sensor_id": "s", "sensor_type": TYPE,
                      "sensor_time": "2026-06-24T12:00:00", "value": 1.0})
    assert isinstance(res, ParsedReading)
    assert res.sensor_time.tzinfo is not None, "offset-less timestamp must become aware"


def test_mixed_awareness_batch_does_not_crash_cycle():
    # One payload has 'Z' (aware), one has no offset (would be naive). The cycle must
    # process both, not abort with a TypeError in the dedup sort.
    store = FakeStore()
    reg = SensorRegistry([ExpectedSensor("a", TYPE, "b"), ExpectedSensor("c", TYPE, "b")])
    batch = [
        {"sensor_id": "a", "sensor_type": TYPE, "sensor_time": "2026-06-24T12:00:00Z", "value": 1.0},
        {"sensor_id": "c", "sensor_type": TYPE, "sensor_time": "2026-06-24T12:00:01", "value": 2.0},
    ]
    summary = run_cycle(batch, store, reg, {}, NOW)
    assert summary.ok is True, f"cycle aborted: {summary.error}"
    assert {s.sensor_id for s in summary.sensors} == {"a", "c"}


def test_same_instant_different_format_dedups_to_one_key():
    # 'Z' and '+00:00' denote the same instant; after normalization they must be equal
    # so the same instant forms ONE dedup key, not two.
    a = safe_parse({"sensor_id": "s", "sensor_type": TYPE,
                    "sensor_time": "2026-06-24T12:00:00Z", "value": 1.0})
    b = safe_parse({"sensor_id": "s", "sensor_type": TYPE,
                    "sensor_time": "2026-06-24T12:00:00+00:00", "value": 1.0})
    assert a.sensor_time == b.sensor_time
