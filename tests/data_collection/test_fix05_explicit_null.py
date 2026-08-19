"""Fix #5 — an explicit null value is a legitimate NO_DATA, not CORRUPT.

parsing.py explicitly allows value=None ("an explicit null reading"). The orchestrator
used to fall through to check_range(None) -> CORRUPT, mislabelling a valid null report
as a tampering/bad-sensor signal. It must map to NO_DATA on the reading axis.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.data_collection.agent import process_cycle
from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.statuses import ReadingStatus, SensorHealth

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
TYPE = "null_type"
PROFILE = SensorProfile(TYPE, "x", cadence_s=60.0, phys_min=-100.0, phys_max=100.0,
                        clock_drift_tolerance_s=5.0)


def setup_module(module):
    SENSOR_PROFILES[TYPE] = PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TYPE, None)


def test_explicit_null_value_is_no_data_not_corrupt():
    reg = SensorRegistry([ExpectedSensor("s", TYPE, "b")])
    batch = [{"sensor_id": "s", "sensor_type": TYPE,
              "sensor_time": NOW.isoformat(), "value": None}]
    cyc = process_cycle(batch, reg, {}, NOW)
    r = cyc.results["s"]
    assert r.reading_status is ReadingStatus.NO_DATA
    assert r.reading_status is not ReadingStatus.CORRUPT
    assert r.value is None
    # The sensor is present this cycle, so it is LIVE (not silent).
    assert r.sensor_health is SensorHealth.LIVE
    # An explicit null is not a RANGE violation -> no RANGE decision logged.
    assert not any(e.decision == "RANGE" for e in cyc.logs)


def test_actual_out_of_range_is_still_corrupt():
    # Guard: the null fix must not weaken real range checking.
    reg = SensorRegistry([ExpectedSensor("s", TYPE, "b")])
    cyc = process_cycle(
        [{"sensor_id": "s", "sensor_type": TYPE, "sensor_time": NOW.isoformat(),
          "value": 9999.0}], reg, {}, NOW)
    assert cyc.results["s"].reading_status is ReadingStatus.CORRUPT
