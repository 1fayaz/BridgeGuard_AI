"""T701 — resolve_pending function-level acceptance.

Acceptance (tasks.md T701): pure; all three triggers reachable; an on-time 3rd
confirming reading at ~3x cadence resolves via (a) confirmation, NEVER races (c)
timeout (assert the strict `>` + buffer); never returns "still pending" once a terminal
trigger fires. (AC-5 behaviour split across T702/T703.)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.checks.pending import (
    PendingResolution,
    PendingSpike,
    ResolutionTrigger,
    resolve_pending,
)
from agents.data_collection.checks.spike import BaselineResult
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus, SensorHealth

UTC = timezone.utc
RAISED = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # confirm_count=3, pending_timeout_s = 60 * 3 = 180s
BASELINE = BaselineResult(mean=10.0, std=2.0, n=50, usable=True, reason="ok")
TIMEOUT_S = 180.0


def pending(subsequent: list[float]) -> PendingSpike:
    return PendingSpike(
        candidate_value=20.0, raised_at=RAISED, baseline=BASELINE, subsequent=subsequent
    )


# ----- (a) confirmation window -------------------------------------------------

def test_a_window_full_sustained_resolves_ok():
    res = resolve_pending(pending([21.0, 22.0, 23.0]), SensorHealth.LIVE,
                          RAISED + timedelta(seconds=180), PROFILE)
    assert res.resolved is True
    assert res.trigger is ResolutionTrigger.CONFIRMATION
    assert res.final_status is ReadingStatus.OK
    assert res.confirmed is True


def test_a_window_full_not_sustained_resolves_spike():
    res = resolve_pending(pending([10.0, 11.0, 9.0]), SensorHealth.LIVE,
                          RAISED + timedelta(seconds=120), PROFILE)
    assert res.trigger is ResolutionTrigger.CONFIRMATION
    assert res.final_status is ReadingStatus.SPIKE
    assert res.confirmed is False


# ----- (b) sensor offline ------------------------------------------------------

def test_b_offline_before_window_is_spike_unconfirmed():
    # Only 1 confirming reading, but the sensor is OFFLINE -> fail safe to SPIKE.
    res = resolve_pending(pending([21.0]), SensorHealth.OFFLINE,
                          RAISED + timedelta(seconds=90), PROFILE)
    assert res.resolved is True
    assert res.trigger is ResolutionTrigger.OFFLINE
    assert res.final_status is ReadingStatus.SPIKE
    assert res.confirmed is False
    assert "offline" in res.reason.lower()


# ----- (c) timeout -------------------------------------------------------------

def test_c_timeout_strictly_after_3x_cadence_is_spike():
    # Past the timeout with too few confirming readings -> SPIKE (unconfirmed).
    res = resolve_pending(pending([21.0]), SensorHealth.LIVE,
                          RAISED + timedelta(seconds=TIMEOUT_S + 1), PROFILE)
    assert res.resolved is True
    assert res.trigger is ResolutionTrigger.TIMEOUT
    assert res.final_status is ReadingStatus.SPIKE


# ----- G3: the (a)-vs-(c) tie is unreachable -----------------------------------

def test_g3_on_time_third_reading_at_boundary_resolves_via_confirmation():
    # The 3rd confirming reading arrives exactly AT 3x cadence (180s). The window is
    # full AND elapsed == timeout (not > timeout). (a) must win, never (c).
    res = resolve_pending(pending([21.0, 22.0, 23.0]), SensorHealth.LIVE,
                          RAISED + timedelta(seconds=TIMEOUT_S), PROFILE)
    assert res.trigger is ResolutionTrigger.CONFIRMATION  # NOT timeout
    assert res.final_status is ReadingStatus.OK


def test_g3_exactly_at_timeout_without_window_is_still_pending():
    # elapsed == timeout (not strictly greater) and window not full -> NOT yet timed
    # out. Proves the strict `>`: the boundary instant does not fire (c).
    res = resolve_pending(pending([21.0]), SensorHealth.LIVE,
                          RAISED + timedelta(seconds=TIMEOUT_S), PROFILE)
    assert res.resolved is False
    assert res.final_status is None


def test_g3_one_second_past_timeout_fires():
    res = resolve_pending(pending([21.0]), SensorHealth.LIVE,
                          RAISED + timedelta(seconds=TIMEOUT_S + 0.5), PROFILE)
    assert res.trigger is ResolutionTrigger.TIMEOUT


# ----- priority + still-pending ------------------------------------------------

def test_confirmation_beats_offline_when_window_full():
    # Window full AND offline: (a) is checked first, so a full window wins.
    res = resolve_pending(pending([21.0, 22.0, 23.0]), SensorHealth.OFFLINE,
                          RAISED + timedelta(seconds=120), PROFILE)
    assert res.trigger is ResolutionTrigger.CONFIRMATION
    assert res.final_status is ReadingStatus.OK


def test_still_pending_when_no_trigger():
    res = resolve_pending(pending([21.0]), SensorHealth.LIVE,
                          RAISED + timedelta(seconds=60), PROFILE)
    assert res.resolved is False
    assert res.final_status is None
    assert res.trigger is None


def test_none_health_does_not_force_spike():
    # Unevaluable liveness (None) must not be treated as OFFLINE.
    res = resolve_pending(pending([21.0]), None,
                          RAISED + timedelta(seconds=60), PROFILE)
    assert res.resolved is False


def test_returns_resolution_type():
    assert isinstance(
        resolve_pending(pending([]), SensorHealth.LIVE, RAISED, PROFILE),
        PendingResolution,
    )
