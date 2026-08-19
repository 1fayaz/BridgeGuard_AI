"""T301 — check_liveness function-level acceptance.

Acceptance (tasks.md T301): pure function (clock injected); threshold read from the
profile, not hardcoded; missed-count derived from the sensor's own timestamps; no
other check sets OFFLINE (verified structurally — only this module returns SensorHealth);
never raises. (AC-1 behaviour is exercised separately in T302.)

These tests use a FIXTURE profile with a concrete cadence, because real cadences are
TODO sentinels by design — the logic must not depend on the specific number.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agents.data_collection.checks.liveness import (
    LivenessResult,
    SensorLivenessState,
    check_liveness,
)
from agents.data_collection.config.sensor_profiles import TODO, SensorProfile
from agents.data_collection.statuses import SensorHealth

UTC = timezone.utc

# Concrete cadence so behaviour is testable; real profiles keep cadence_s = TODO.
PROFILE = SensorProfile(
    sensor_type="test_sensor",
    unit="x",
    cadence_s=60.0,          # 1 reading/minute
    phys_min=0.0,
    phys_max=100.0,
    clock_drift_tolerance_s=5.0,
)
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _state(last_seen: datetime | None) -> SensorLivenessState:
    return SensorLivenessState(sensor_id="s-1", last_seen=last_seen)


def test_just_reported_is_live_zero_missed():
    res = check_liveness(_state(NOW), NOW, PROFILE)
    assert res.health is SensorHealth.LIVE
    assert res.missed_count == 0


def test_one_and_two_missed_still_live():
    for missed in (1, 2):
        last = NOW - timedelta(seconds=60.0 * missed)
        res = check_liveness(_state(last), NOW, PROFILE)
        assert res.health is SensorHealth.LIVE, f"{missed} missed should be LIVE"
        assert res.missed_count == missed


def test_three_missed_flips_offline():
    last = NOW - timedelta(seconds=60.0 * 3)
    res = check_liveness(_state(last), NOW, PROFILE)
    assert res.health is SensorHealth.OFFLINE
    assert res.missed_count == 3
    assert "OFFLINE" in res.reason


def test_never_seen_is_offline_not_absent():
    # B1 / AC-1: a sensor that never reported is evaluated as OFFLINE, never dropped.
    res = check_liveness(_state(None), NOW, PROFILE)
    assert res.health is SensorHealth.OFFLINE
    assert "silent" in res.reason.lower()


def test_threshold_comes_from_profile_not_hardcoded():
    # Same elapsed time, different per-type threshold -> different verdict.
    strict = replace(PROFILE, offline_after_n=2)
    lenient = replace(PROFILE, offline_after_n=5)
    last = NOW - timedelta(seconds=60.0 * 3)  # exactly 3 missed
    assert check_liveness(_state(last), NOW, strict).health is SensorHealth.OFFLINE
    assert check_liveness(_state(last), NOW, lenient).health is SensorHealth.LIVE


def test_per_type_cadence_scaling_fast_vs_slow():
    # A fast (10s) and a slow (3600s) sensor both flip at exactly 3 missed, scaled to
    # their own cadence — not a flat wall-clock rule.
    fast = replace(PROFILE, cadence_s=10.0)
    slow = replace(PROFILE, cadence_s=3600.0)
    fast_3 = NOW - timedelta(seconds=30)     # 3 * 10s
    slow_3 = NOW - timedelta(seconds=10800)  # 3 * 3600s
    assert check_liveness(_state(fast_3), NOW, fast).health is SensorHealth.OFFLINE
    assert check_liveness(_state(slow_3), NOW, slow).health is SensorHealth.OFFLINE
    # And the fast sensor's 30s of silence would still be LIVE for the slow sensor.
    assert check_liveness(_state(fast_3), NOW, slow).health is SensorHealth.LIVE


def test_missed_count_derived_from_sensor_timestamp():
    # The count is elapsed // cadence on the SENSOR's own timeline (G4).
    last = NOW - timedelta(seconds=150)  # 2.5 intervals at 60s -> floor 2
    res = check_liveness(_state(last), NOW, PROFILE)
    assert res.missed_count == 2
    assert res.health is SensorHealth.LIVE


def test_pure_no_mutation_of_inputs():
    state = _state(NOW - timedelta(seconds=120))
    before = (state.sensor_id, state.last_seen)
    check_liveness(state, NOW, PROFILE)
    assert (state.sensor_id, state.last_seen) == before  # frozen + untouched


def test_todo_cadence_is_unevaluable_not_guessed():
    # A profile whose cadence is still TODO must NOT be silently assigned a status.
    todo_profile = SensorProfile(
        sensor_type="unconfigured", unit="x",
        cadence_s=TODO, phys_min=0.0, phys_max=1.0,
    )
    res = check_liveness(_state(NOW), NOW, todo_profile)
    assert res.health is None
    assert res.config_incomplete is True
    assert "todo" in res.reason.lower() or "unset" in res.reason.lower()


def test_returns_result_type_never_raises_on_future_timestamp():
    # A reading dated slightly in the future (minor drift) clamps to 0 missed, no crash.
    future = NOW + timedelta(seconds=30)
    res = check_liveness(_state(future), NOW, PROFILE)
    assert isinstance(res, LivenessResult)
    assert res.missed_count == 0
    assert res.health is SensorHealth.LIVE
