"""Fix #7 — a silent sensor's NO_DATA validated row must NOT inherit a stale timestamp.

persist_cycle used to stamp every validated row with `next_state.last_seen`. For a
sensor that reported in a PRIOR cycle but is silent NOW, last_seen still holds the OLD
reading's time — so this cycle's NO_DATA row claimed a sensor_time it never produced,
breaking "every number traceable to ITS source" (Const. II). A silent cycle produced no
reading, so its validated row's sensor_time must be None.

NOTE: this behaviour was secured by the Fix #3 restructure (SensorResult now carries the
reading's OWN sensor_time, None when silent). This is a regression lock, not a fix of a
still-live bug — it passes on current code.
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
TYPE = "silent_type"
PROFILE = SensorProfile(TYPE, "x", cadence_s=60.0, phys_min=-100.0, phys_max=100.0,
                        clock_drift_tolerance_s=5.0)


def setup_module(module):
    SENSOR_PROFILES[TYPE] = PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TYPE, None)


def reg():
    return SensorRegistry([ExpectedSensor("s", TYPE, "b")])


def payload(secs, value):
    return {"sensor_id": "s", "sensor_type": TYPE,
            "sensor_time": (NOW + timedelta(seconds=secs)).isoformat(), "value": value}


def test_silent_cycle_validated_row_has_no_stale_sensor_time():
    store = FakeStore()
    states: dict = {}
    # Cycle 1: the sensor reports at NOW-... (last_seen advances to a real reading time).
    run_cycle([payload(-120, 5.0)], store, reg(), states, NOW - timedelta(seconds=120))
    # Cycle 2: the sensor is SILENT. Its NO_DATA row must carry sensor_time=None,
    # NOT the prior reading's timestamp.
    run_cycle([], store, reg(), states, NOW)

    no_data_rows = [r for r in store.validated_rows
                    if r.sensor_id == "s" and r.status is ReadingStatus.NO_DATA]
    assert no_data_rows, "a silent sensor must still get a NO_DATA validated row"
    assert all(r.sensor_time is None for r in no_data_rows), (
        "a silent cycle produced no reading -> its row must not claim a stale sensor_time"
    )
    assert no_data_rows[-1].source_raw_ids == (), "NO_DATA links to no raw source"
