"""T702 + T703 — AC-5: a PENDING spike is ALWAYS resolved, three ways.

T702 / AC-5 path (a): 3 confirming readings arriving on schedule resolve to OK (if the
                      shift is sustained) or SPIKE (if not), BEFORE any timeout — the
                      G3 buffer verified at the 3x-cadence boundary.
T703 / AC-5 paths (b)+(c): the safety-net.
   (b) a spike, then the sensor hits 3 missed -> OFFLINE -> PENDING finalised SPIKE
       (unconfirmed). The OFFLINE is derived from the real liveness check (T301).
   (c) a spike, then elapsed > 3x cadence with <3 confirming readings -> SPIKE
       (unconfirmed).
A PENDING is NEVER left unresolved once any terminal trigger fires.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.checks.liveness import (
    SensorLivenessState,
    check_liveness,
)
from agents.data_collection.checks.pending import (
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
)  # cadence 60s, confirm_count 3, pending_timeout_s 180s, offline_after_n 3
BASELINE = BaselineResult(mean=10.0, std=2.0, n=50, usable=True, reason="ok")
TIMEOUT_S = 180.0


def pending(subsequent: list[float]) -> PendingSpike:
    return PendingSpike(20.0, RAISED, BASELINE, subsequent)


# ----- T702 / AC-5 path (a): on-schedule confirmation -------------------------

def test_ac5a_three_on_schedule_sustained_resolves_ok_before_timeout():
    # 3rd reading lands at 3x cadence (180s) — exactly the boundary. Resolves OK via
    # confirmation, before the (strictly-greater) timeout can fire.
    now = RAISED + timedelta(seconds=TIMEOUT_S)
    res = resolve_pending(pending([21.0, 22.0, 23.0]), SensorHealth.LIVE, now, PROFILE)
    assert res.trigger is ResolutionTrigger.CONFIRMATION
    assert res.final_status is ReadingStatus.OK
    assert res.resolved is True


def test_ac5a_three_on_schedule_not_sustained_resolves_spike_before_timeout():
    now = RAISED + timedelta(seconds=TIMEOUT_S)
    res = resolve_pending(pending([10.0, 9.0, 11.0]), SensorHealth.LIVE, now, PROFILE)
    assert res.trigger is ResolutionTrigger.CONFIRMATION
    assert res.final_status is ReadingStatus.SPIKE


def test_ac5a_g3_boundary_window_full_beats_timeout():
    # The defining G3 case: window full AND elapsed == timeout. (a) wins, not (c).
    now = RAISED + timedelta(seconds=TIMEOUT_S)
    res = resolve_pending(pending([21.0, 22.0, 23.0]), SensorHealth.LIVE, now, PROFILE)
    assert res.trigger is not ResolutionTrigger.TIMEOUT


# ----- T703 / AC-5 path (b): sensor goes OFFLINE ------------------------------

def test_ac5b_spike_then_offline_is_spike_unconfirmed():
    # Sensor's last reading was the candidate at RAISED; 3 cadence intervals pass with
    # no new reading -> liveness says OFFLINE. Only 1 confirming reading arrived.
    now = RAISED + timedelta(seconds=60 * 3)
    health = check_liveness(
        SensorLivenessState("s", last_seen=RAISED), now, PROFILE
    ).health
    assert health is SensorHealth.OFFLINE  # derived from real liveness (T301)

    res = resolve_pending(pending([21.0]), health, now, PROFILE)
    assert res.resolved is True
    assert res.trigger is ResolutionTrigger.OFFLINE
    assert res.final_status is ReadingStatus.SPIKE
    assert res.confirmed is False


# ----- T703 / AC-5 path (c): timeout ------------------------------------------

def test_ac5c_spike_then_timeout_with_too_few_confirms_is_spike():
    now = RAISED + timedelta(seconds=TIMEOUT_S + 1)
    res = resolve_pending(pending([21.0, 22.0]), SensorHealth.LIVE, now, PROFILE)
    assert res.resolved is True
    assert res.trigger is ResolutionTrigger.TIMEOUT
    assert res.final_status is ReadingStatus.SPIKE


def test_ac5_pending_is_never_left_unresolved_across_lifetime():
    # Walk a candidate forward in time: pending early, but ALWAYS terminal by the time
    # either the window fills, the sensor offlines, or the timeout passes.
    # Early (60s, 1 reading, live): still pending — acceptable, not yet decidable.
    early = resolve_pending(pending([21.0]), SensorHealth.LIVE,
                            RAISED + timedelta(seconds=60), PROFILE)
    assert early.resolved is False

    # By the timeout+ with still too few readings: MUST be resolved (safety-net c).
    late = resolve_pending(pending([21.0]), SensorHealth.LIVE,
                           RAISED + timedelta(seconds=TIMEOUT_S + 1), PROFILE)
    assert late.resolved is True

    # If the sensor offlines first, resolved even earlier (safety-net b).
    offlined = resolve_pending(pending([21.0]), SensorHealth.OFFLINE,
                               RAISED + timedelta(seconds=90), PROFILE)
    assert offlined.resolved is True
