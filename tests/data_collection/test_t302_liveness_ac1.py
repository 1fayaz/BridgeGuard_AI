"""T302 — AC-1 acceptance: offline detection over the expected-sensor registry.

AC-1 (spec): a sensor reporting on time is LIVE; 1-2 missed reports stay LIVE; at 3
missed it goes OFFLINE within one cycle; and a sensor in the registry that reports
NOTHING is evaluated as OFFLINE — never dropped (silence != safety). Fast- and
slow-cadence sensors both flip at exactly 3 missed, scaled to their own cadence.

The full orchestrator (T901) is not built yet, so this test reproduces the
registry-driven sweep it will perform: for every EXPECTED sensor (from T104's
SensorRegistry), derive last_seen from this cycle's batch — or None if the sensor was
silent — and run check_liveness. This is what guarantees one liveness verdict per
expected sensor, including the silent ones.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from agents.data_collection.checks.liveness import (
    LivenessResult,
    SensorLivenessState,
    check_liveness,
)
from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import SensorHealth

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)

# Concrete cadences (real profiles keep cadence_s = TODO). Two types: fast + slow.
FAST = SensorProfile("fast_type", "x", cadence_s=10.0, phys_min=0.0, phys_max=1.0,
                     clock_drift_tolerance_s=1.0)
SLOW = SensorProfile("slow_type", "x", cadence_s=3600.0, phys_min=0.0, phys_max=1.0,
                     clock_drift_tolerance_s=1.0)
PROFILES = {"fast_type": FAST, "slow_type": SLOW}


def sweep_liveness(
    registry: SensorRegistry,
    last_seen_by_id: dict[str, datetime],
    now: datetime,
) -> dict[str, LivenessResult]:
    """Mimic the orchestrator (T901): evaluate EVERY expected sensor, silent or not.

    A sensor absent from `last_seen_by_id` is silent this cycle -> last_seen=None.
    """
    results: dict[str, LivenessResult] = {}
    for sensor in registry.all():
        state = SensorLivenessState(
            sensor_id=sensor.sensor_id,
            last_seen=last_seen_by_id.get(sensor.sensor_id),
        )
        results[sensor.sensor_id] = check_liveness(state, now, PROFILES[sensor.sensor_type])
    return results


def _registry() -> SensorRegistry:
    return SensorRegistry([
        ExpectedSensor("fast-1", "fast_type", "bridge-1"),
        ExpectedSensor("slow-1", "slow_type", "bridge-1"),
        ExpectedSensor("ghost-1", "fast_type", "bridge-1"),  # will stay silent
    ])


def test_ac1_on_time_sensor_is_live():
    reg = _registry()
    res = sweep_liveness(reg, {"fast-1": NOW, "slow-1": NOW, "ghost-1": NOW}, NOW)
    assert res["fast-1"].health is SensorHealth.LIVE
    assert res["slow-1"].health is SensorHealth.LIVE


def test_ac1_one_and_two_missed_stay_live():
    reg = _registry()
    seen = {
        "fast-1": NOW - timedelta(seconds=10 * 1),   # 1 missed
        "slow-1": NOW - timedelta(seconds=3600 * 2),  # 2 missed
        "ghost-1": NOW,
    }
    res = sweep_liveness(reg, seen, NOW)
    assert res["fast-1"].health is SensorHealth.LIVE
    assert res["fast-1"].missed_count == 1
    assert res["slow-1"].health is SensorHealth.LIVE
    assert res["slow-1"].missed_count == 2


def test_ac1_three_missed_offline_within_one_cycle():
    reg = _registry()
    seen = {
        "fast-1": NOW - timedelta(seconds=10 * 3),    # exactly 3 missed
        "slow-1": NOW - timedelta(seconds=3600 * 3),  # exactly 3 missed
        "ghost-1": NOW,
    }
    res = sweep_liveness(reg, seen, NOW)
    assert res["fast-1"].health is SensorHealth.OFFLINE
    assert res["slow-1"].health is SensorHealth.OFFLINE


def test_ac1_silent_registry_sensor_is_offline_not_dropped():
    # The headline: ghost-1 is expected but sent NOTHING. It must produce an OFFLINE
    # verdict, not be missing from the results.
    reg = _registry()
    seen = {"fast-1": NOW, "slow-1": NOW}  # ghost-1 absent from the batch
    res = sweep_liveness(reg, seen, NOW)
    assert "ghost-1" in res, "silent sensor must be evaluated, not dropped"
    assert res["ghost-1"].health is SensorHealth.OFFLINE
    assert "silent" in res["ghost-1"].reason.lower()
    # One verdict per expected sensor — none skipped.
    assert set(res) == {"fast-1", "slow-1", "ghost-1"}


def test_ac1_per_type_scaling_not_flat_wall_clock():
    # 30s of silence: 3 missed for the 10s sensor (OFFLINE) but well within one
    # interval for a 3600s sensor (LIVE). Same elapsed time, different verdict —
    # proving the threshold scales per-type, not by a flat clock.
    reg = SensorRegistry([
        ExpectedSensor("f", "fast_type", "b"),
        ExpectedSensor("s", "slow_type", "b"),
    ])
    thirty_s_ago = NOW - timedelta(seconds=30)
    res = sweep_liveness(reg, {"f": thirty_s_ago, "s": thirty_s_ago}, NOW)
    assert res["f"].health is SensorHealth.OFFLINE   # 30 // 10 = 3 missed
    assert res["s"].health is SensorHealth.LIVE      # 30 // 3600 = 0 missed


def test_ac1_boundary_two_missed_live_three_missed_offline():
    # The exact flip point for a single cadence: 2 -> LIVE, 3 -> OFFLINE.
    reg = SensorRegistry([ExpectedSensor("f", "fast_type", "b")])
    at_2 = NOW - timedelta(seconds=10 * 2)
    at_3 = NOW - timedelta(seconds=10 * 3)
    assert sweep_liveness(reg, {"f": at_2}, NOW)["f"].health is SensorHealth.LIVE
    assert sweep_liveness(reg, {"f": at_3}, NOW)["f"].health is SensorHealth.OFFLINE
