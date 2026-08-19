"""Fix #1/#4/#6 — the open-PENDING fast-path must not exempt a reading from its checks.

Root cause (code-review): while a spike candidate was open, the orchestrator's
early-return block consumed the cycle's reading purely as a confirmation sample and
skipped range, clock-drift, and verdict emission for it. Three symptoms:

  #1 a CORRUPT (out-of-range) reading was masked — emitted PENDING, no RANGE log.
  #4 elevated confirmations on a SPIKE resolution entered the OK-only baseline.
  #6 clock-drift on a confirmation-window reading was never flagged or logged.

These tests drive process_cycle with a pre-seeded open candidate and assert the
reading is still fully evaluated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.agent import SensorState, process_cycle
from agents.data_collection.checks.pending import PendingSpike
from agents.data_collection.checks.spike import BaselineResult
from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.statuses import ReadingStatus, SensorHealth

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
TYPE = "fastpath_type"
PROFILE = SensorProfile(TYPE, "x", cadence_s=60.0, phys_min=-100.0, phys_max=100.0,
                        clock_drift_tolerance_s=5.0)
BASELINE = BaselineResult(mean=10.0, std=2.0, n=50, usable=True, reason="ok")


def setup_module(module):
    SENSOR_PROFILES[TYPE] = PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TYPE, None)


def reg(*ids):
    return SensorRegistry([ExpectedSensor(i, TYPE, "b") for i in ids])


def payload(sensor_id, secs, value, ingest_secs=None):
    p = {"sensor_id": sensor_id, "sensor_type": TYPE,
         "sensor_time": (NOW + timedelta(seconds=secs)).isoformat(), "value": value}
    if ingest_secs is not None:
        p["ingest_time"] = (NOW + timedelta(seconds=ingest_secs)).isoformat()
    return p


def open_candidate_state(sensor_id, *, raised_secs=-60, subsequent=None):
    """A SensorState with an OPEN spike candidate (raised earlier, not yet resolved)."""
    pending = PendingSpike(
        candidate_value=80.0,
        raised_at=NOW + timedelta(seconds=raised_secs),
        baseline=BASELINE,
        subsequent=list(subsequent or []),
    )
    return SensorState(sensor_id=sensor_id, last_seen=NOW + timedelta(seconds=raised_secs),
                       history=(), pending=pending)


# ---- #1: CORRUPT reading must surface, not be masked by the open candidate ----

def test_fix1_corrupt_reading_under_open_pending_is_emitted_and_logged():
    states = {"s": open_candidate_state("s")}
    # An out-of-range reading arrives while the candidate is open.
    cyc = process_cycle([payload("s", 0, 9999.0)], reg("s"), states, NOW)
    r = cyc.results["s"]
    assert r.reading_status is ReadingStatus.CORRUPT, "out-of-range reading must surface as CORRUPT"
    assert r.value == 9999.0, "the emitted value must be the dangerous reading, not the candidate"
    assert any(e.decision == "RANGE" for e in cyc.logs), "a RANGE decision must be logged"


# ---- #4: elevated confirmations on a SPIKE resolution must not poison baseline ----

def test_fix4_spike_resolution_does_not_admit_elevated_confirms_to_baseline():
    # Candidate open with two ELEVATED in-range confirmations already accumulated.
    # The sensor is silent this cycle and has been so long enough to go OFFLINE, which
    # forces the candidate to resolve SPIKE (unconfirmed). The elevated confirmation
    # values (70, 75 — far above baseline mean 10) must NOT enter history as OK.
    states = {"s": open_candidate_state("s", raised_secs=-300, subsequent=[70.0, 75.0])}
    cyc = process_cycle([], reg("s"), states, NOW)  # silent -> OFFLINE -> resolve SPIKE
    r = cyc.results["s"]
    assert r.reading_status is ReadingStatus.SPIKE
    hist_values = [h.value for h in cyc.next_states["s"].history]
    assert 70.0 not in hist_values, "elevated confirmation poisoned the OK baseline"
    assert 75.0 not in hist_values, "elevated confirmation poisoned the OK baseline"


# ---- #6: clock-drift on a confirmation-window reading must be flagged + logged ----

def test_fix6_clock_drift_flagged_for_confirmation_reading():
    # Candidate open; this cycle's reading is in-range (a confirmation sample) but has
    # sensor/ingest drift beyond tolerance. Drift must still be flagged and logged.
    states = {"s": open_candidate_state("s")}
    cyc = process_cycle([payload("s", 0, 11.0, ingest_secs=30)], reg("s"), states, NOW)
    r = cyc.results["s"]
    assert r.clock_drift is True, "clock drift on a confirmation reading must be flagged"
    assert any(e.decision == "CLOCK_DRIFT" for e in cyc.logs), "CLOCK_DRIFT must be logged"


def test_fix4_ok_resolution_still_admits_sustained_level_as_new_normal():
    # Counter-check: when a candidate resolves OK (sustained), the candidate + its
    # confirmations DO become the new normal and enter the baseline. (Regression guard
    # so the #4 fix doesn't over-correct and drop a genuine sustained shift.)
    states = {"s": open_candidate_state("s", subsequent=[81.0, 82.0])}
    # one more sustained reading fills the window (confirm_count=3) -> OK
    cyc = process_cycle([payload("s", 0, 83.0)], reg("s"), states, NOW)
    r = cyc.results["s"]
    assert r.reading_status is ReadingStatus.OK
    hist_values = [h.value for h in cyc.next_states["s"].history]
    assert 80.0 in hist_values, "sustained candidate should seed the new-normal baseline"
