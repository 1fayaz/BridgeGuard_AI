"""T901 — process_cycle orchestration acceptance.

Acceptance (tasks.md T901): returns ONE result per expected sensor (from the registry,
including silent ones); precedence correct (CORRUPT not interpolated; OFFLINE from
liveness co-emitted with NO_DATA from the reading axis); deterministic given the
injected clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.agent import (
    CycleResult,
    SensorResult,
    SensorState,
    process_cycle,
)
from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.statuses import ReadingStatus, SensorHealth

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)

# A registered, fully-configured profile injected into the module's lookup table so the
# orchestrator's get_profile() returns concrete bounds/cadence (real seeds are TODO).
TEST_TYPE = "test_acc"
TEST_PROFILE = SensorProfile(
    sensor_type=TEST_TYPE, unit="m/s^2", cadence_s=60.0,
    phys_min=-100.0, phys_max=100.0, clock_drift_tolerance_s=5.0,
)


def setup_module(module):  # noqa: D401 - pytest hook
    SENSOR_PROFILES[TEST_TYPE] = TEST_PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TEST_TYPE, None)


def payload(sensor_id: str, secs: int, value, ingest_secs: int | None = None) -> dict:
    p = {
        "sensor_id": sensor_id,
        "sensor_type": TEST_TYPE,
        "sensor_time": (NOW + timedelta(seconds=secs)).isoformat(),
        "value": value,
    }
    if ingest_secs is not None:
        p["ingest_time"] = (NOW + timedelta(seconds=ingest_secs)).isoformat()
    return p


def registry(*ids: str) -> SensorRegistry:
    return SensorRegistry([ExpectedSensor(i, TEST_TYPE, "bridge-1") for i in ids])


def test_one_result_per_expected_sensor_including_silent():
    reg = registry("a", "b", "silent")
    # only a and b report; 'silent' sends nothing.
    batch = [payload("a", 0, 10.0), payload("b", 0, 20.0)]
    res = process_cycle(batch, reg, {}, NOW)
    assert isinstance(res, CycleResult)
    assert set(res.results) == {"a", "b", "silent"}     # silent NOT dropped
    assert all(isinstance(r, SensorResult) for r in res.results.values())


def test_silent_sensor_offline_and_no_data_coexist():
    # 'silent' has never reported -> OFFLINE (device) AND NO_DATA (reading) co-emitted.
    reg = registry("silent")
    res = process_cycle([], reg, {}, NOW)
    r = res.results["silent"]
    assert r.sensor_health is SensorHealth.OFFLINE
    assert r.reading_status is ReadingStatus.NO_DATA
    assert r.value is None


def test_in_range_reading_is_ok_and_live():
    reg = registry("a")
    res = process_cycle([payload("a", 0, 5.0)], reg, {}, NOW)
    r = res.results["a"]
    assert r.reading_status is ReadingStatus.OK
    assert r.sensor_health is SensorHealth.LIVE
    assert r.value == 5.0


def test_corrupt_precedence_not_interpolated_or_spiked():
    # Out-of-range value -> CORRUPT; must NOT be re-judged as spike/interpolated.
    reg = registry("a")
    res = process_cycle([payload("a", 0, 999.0)], reg, {}, NOW)
    r = res.results["a"]
    assert r.reading_status is ReadingStatus.CORRUPT
    # A RANGE decision was logged; no SPIKE/PENDING for this sensor.
    decisions = {e.decision for e in res.logs if e.sensor_id == "a"}
    assert "RANGE" in decisions
    assert "SPIKE" not in decisions


def test_clock_drift_flag_coexists_with_ok():
    # ingest 30s after sensor_time -> drift > 5s tolerance; value in range -> OK + flag.
    reg = registry("a")
    res = process_cycle([payload("a", 0, 5.0, ingest_secs=30)], reg, {}, NOW)
    r = res.results["a"]
    assert r.reading_status is ReadingStatus.OK      # value still OK
    assert r.clock_drift is True                     # timing flagged
    assert any(e.decision == "CLOCK_DRIFT" for e in res.logs)


def test_malformed_payload_logged_parse_not_aborting_cycle():
    reg = registry("a", "b")
    batch = ["garbage", payload("a", 0, 5.0), {"sensor_id": "b", "sensor_type": TEST_TYPE,
                                               "sensor_time": "bad", "value": 1.0}]
    res = process_cycle(batch, reg, {}, NOW)
    # 'a' still got a verdict despite the two malformed entries.
    assert res.results["a"].reading_status is ReadingStatus.OK
    assert any(e.decision == "PARSE" for e in res.logs)
    assert len(res.parse_failures) >= 1


def test_duplicate_conflict_first_wins_logged():
    reg = registry("a")
    batch = [payload("a", 0, 5.0), payload("a", 0, 9.0)]  # same ts, conflicting value
    res = process_cycle(batch, reg, {}, NOW)
    assert res.results["a"].value == 5.0                  # first-received kept
    assert len(res.conflicts) == 1
    assert any(e.decision == "DUPLICATE_CONFLICT" for e in res.logs)


def test_deterministic_same_inputs_same_output():
    reg = registry("a", "b", "silent")
    batch = [payload("a", 0, 5.0), payload("b", 0, 7.0)]
    r1 = process_cycle(batch, reg, {}, NOW)
    r2 = process_cycle(batch, reg, {}, NOW)
    sig1 = {k: (v.sensor_health, v.reading_status, v.value) for k, v in r1.results.items()}
    sig2 = {k: (v.sensor_health, v.reading_status, v.value) for k, v in r2.results.items()}
    assert sig1 == sig2


def test_next_states_advance_last_seen():
    reg = registry("a")
    res = process_cycle([payload("a", 0, 5.0)], reg, {}, NOW)
    assert res.next_states["a"].last_seen == NOW
    # OK reading entered history for future baselines.
    assert len(res.next_states["a"].history) == 1


def test_unknown_type_is_corrupt():
    reg = SensorRegistry([ExpectedSensor("weird", "ultrasonic_flow", "b")])
    res = process_cycle(
        [{"sensor_id": "weird", "sensor_type": "ultrasonic_flow",
          "sensor_time": NOW.isoformat(), "value": 1.0}],
        reg, {}, NOW,
    )
    assert res.results["weird"].reading_status is ReadingStatus.CORRUPT
