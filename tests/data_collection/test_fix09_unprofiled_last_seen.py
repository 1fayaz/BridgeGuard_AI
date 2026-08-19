"""Fix #9 — an unprofiled (unknown-type) sensor must still advance last_seen.

The UnknownSensorType branch returned `state` unchanged, so last_seen never moved even
though the device DID report. If its profile is later added, liveness would compute the
gap from a stale (or null) last_seen and wrongly declare it long-OFFLINE — the device
was actually reporting all along. A reporting sensor advances last_seen regardless of
whether we can yet validate its values.

NOTE: secured by the Fix #3 restructure (the UnknownSensorType branch now threads
last_seen=reading_time). Regression lock, passes on current code.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.agent import SensorState, process_cycle
from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.statuses import ReadingStatus

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
UNKNOWN_TYPE = "no_such_profile_type"  # deliberately absent from SENSOR_PROFILES


def reg():
    return SensorRegistry([ExpectedSensor("s", UNKNOWN_TYPE, "b")])


def payload(secs, value):
    return {"sensor_id": "s", "sensor_type": UNKNOWN_TYPE,
            "sensor_time": (NOW + timedelta(seconds=secs)).isoformat(), "value": value}


def test_unprofiled_reporting_sensor_advances_last_seen():
    states = {"s": SensorState(sensor_id="s")}  # never seen before
    reading_time = NOW
    cyc = process_cycle([payload(0, 5.0)], reg(), states, NOW)

    # Still CORRUPT (can't validate an unknown type) ...
    assert cyc.results["s"].reading_status is ReadingStatus.CORRUPT
    # ... but last_seen MUST move to this reading's time, not stay None.
    assert cyc.next_states["s"].last_seen == reading_time, (
        "a reporting unprofiled sensor must advance last_seen so a later profile fix "
        "doesn't see it as never-seen / long-OFFLINE"
    )


def test_unprofiled_silent_sensor_keeps_prior_last_seen():
    prior = NOW - timedelta(seconds=30)
    states = {"s": SensorState(sensor_id="s", last_seen=prior)}
    cyc = process_cycle([], reg(), states, NOW)  # silent this cycle
    assert cyc.next_states["s"].last_seen == prior, (
        "a silent unprofiled sensor keeps its prior last_seen (nothing to advance to)"
    )
