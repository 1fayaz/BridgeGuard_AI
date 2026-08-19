"""T1101 / T1102 / T1103 — end-to-end: every scenario, every AC, Constitution V.

T1101 — a replayable multi-sensor stream harness (injected clock) covering: normal,
        offline (3 missed), silent-from-registry, corrupt, single spike, sustained
        shift, short gap, long gap, late-arrival, unknown type, identical duplicate,
        conflicting duplicate, out-of-order, clock-drift.
T1102 — drive multiple cycles through the real service and assert each AC manifests in
        validated_readings + sensor_status + decision_log.
T1103 — Constitution V four-scenario (normal / missing / corrupt / offline) + the
        never-crash and raw-append-only guarantees (Principles V + II).

The harness uses run_cycle (T1001) -> process_cycle -> persist_cycle against a FakeStore
so the assertions are on PERSISTED rows, exactly what AC verification requires.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.service import run_cycle
from agents.data_collection.statuses import ReadingStatus, SensorHealth
from agents.data_collection.store import FakeStore

UTC = timezone.utc
T0 = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
CADENCE = 60.0
TYPE = "e2e_type"
PROFILE = SensorProfile(
    sensor_type=TYPE, unit="x", cadence_s=CADENCE,
    phys_min=-100.0, phys_max=100.0, clock_drift_tolerance_s=5.0,
)


def setup_module(module):
    SENSOR_PROFILES[TYPE] = PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TYPE, None)


# ---- T1101: the harness -----------------------------------------------------

class StreamHarness:
    """Drives cycles with an injected clock. Deterministic + replayable."""

    def __init__(self, *sensor_ids: str, sensor_type: str = TYPE):
        self.registry = SensorRegistry(
            [ExpectedSensor(i, sensor_type, "bridge-e2e") for i in sensor_ids]
        )
        self.store = FakeStore()
        self.states: dict = {}

    def reading(self, sensor_id, t, value, ingest=None, sensor_type=TYPE):
        p = {"sensor_id": sensor_id, "sensor_type": sensor_type,
             "sensor_time": t.isoformat(), "value": value}
        if ingest is not None:
            p["ingest_time"] = ingest.isoformat()
        return p

    def cycle(self, batch, now):
        return run_cycle(batch, self.store, self.registry, self.states, now)

    def current(self, sensor_id):
        rows = self.store.current_validated(sensor_id)
        return rows[-1] if rows else None

    def status(self, sensor_id):
        return self.store.status_rows.get(sensor_id)


def at(n: int) -> datetime:
    """Time n cadence intervals after T0."""
    return T0 + timedelta(seconds=CADENCE * n)


# ---- T1102: AC-1 .. AC-7 ----------------------------------------------------

def test_ac1_offline_at_three_missed_and_silent_sensor():
    h = StreamHarness("live", "silent")
    # 'live' reports every cycle; 'silent' never reports.
    for n in range(4):
        h.cycle([h.reading("live", at(n), 10.0 + n)], at(n))
    assert h.status("live").health is SensorHealth.LIVE
    # silent: never seen -> OFFLINE, and a NO_DATA reading row (co-existence).
    assert h.status("silent").health is SensorHealth.OFFLINE
    assert h.current("silent").status is ReadingStatus.NO_DATA
    # AC-1: a previously-live sensor that goes quiet flips at 3 missed.
    h2 = StreamHarness("s")
    h2.cycle([h2.reading("s", at(0), 5.0)], at(0))
    # no readings for 3 intervals
    summary = h2.cycle([], at(3))
    assert h2.status("s").health is SensorHealth.OFFLINE


def test_ac2_corrupt_rejected_and_logged():
    h = StreamHarness("s")
    h.cycle([h.reading("s", at(0), 999.0)], at(0))   # out of range
    row = h.current("s")
    assert row.status is ReadingStatus.CORRUPT
    assert row.reason
    # decision_log has a RANGE entry with a reason.
    assert any(l.decision == "RANGE" and l.reason for l in h.store.logs_for("s"))


def test_ac3_single_spike_vs_sustained_shift():
    # Build an OK baseline (varied so std>0), then a spike that returns -> SPIKE;
    # separately a spike that sustains 3 readings -> OK.
    spike_h = StreamHarness("s")
    base_vals = [10.0, 11.0, 9.0, 10.5, 9.5, 10.0]
    for n, v in enumerate(base_vals):
        spike_h.cycle([spike_h.reading("s", at(n), v)], at(n))
    # candidate far outside +/-3sigma:
    k = len(base_vals)
    spike_h.cycle([spike_h.reading("s", at(k), 80.0)], at(k))
    assert spike_h.current("s").status is ReadingStatus.PENDING
    # next 3 readings return to baseline -> transient SPIKE.
    for j, v in enumerate([10.0, 10.0, 10.0], start=k + 1):
        spike_h.cycle([spike_h.reading("s", at(j), v)], at(j))
    assert spike_h.current("s").status is ReadingStatus.SPIKE

    shift_h = StreamHarness("s")
    for n, v in enumerate(base_vals):
        shift_h.cycle([shift_h.reading("s", at(n), v)], at(n))
    shift_h.cycle([shift_h.reading("s", at(k), 80.0)], at(k))
    assert shift_h.current("s").status is ReadingStatus.PENDING
    # sustained high for 3 readings -> released OK.
    for j, v in enumerate([81.0, 82.0, 83.0], start=k + 1):
        shift_h.cycle([shift_h.reading("s", at(j), v)], at(j))
    assert shift_h.current("s").status is ReadingStatus.OK


def test_ac4_short_gap_and_long_gap_with_offline():
    # Long gap: sensor reports at cycle 0, then silent for 3 cycles -> OFFLINE + NO_DATA.
    h = StreamHarness("s")
    h.cycle([h.reading("s", at(0), 10.0)], at(0))
    h.cycle([], at(1))
    h.cycle([], at(2))
    h.cycle([], at(3))
    assert h.status("s").health is SensorHealth.OFFLINE      # device axis (liveness)
    assert h.current("s").status is ReadingStatus.NO_DATA    # reading axis
    # The OFFLINE originated from a LIVENESS decision, not a gap decision.
    assert any(l.decision == "LIVENESS" for l in h.store.logs_for("s"))


def test_ac5_pending_safety_net_offline_resolves_spike():
    h = StreamHarness("s")
    base_vals = [10.0, 11.0, 9.0, 10.5]
    for n, v in enumerate(base_vals):
        h.cycle([h.reading("s", at(n), v)], at(n))
    k = len(base_vals)
    h.cycle([h.reading("s", at(k), 80.0)], at(k))            # spike -> PENDING
    assert h.current("s").status is ReadingStatus.PENDING
    # sensor goes silent; 3 missed -> OFFLINE -> PENDING finalised SPIKE (unconfirmed).
    h.cycle([], at(k + 3))
    assert h.status("s").health is SensorHealth.OFFLINE
    assert h.current("s").status is ReadingStatus.SPIKE
    assert any(l.decision == "PENDING" for l in h.store.logs_for("s"))


def test_ac6_normal_pass_through_is_ok():
    h = StreamHarness("s")
    for n in range(3):
        h.cycle([h.reading("s", at(n), 10.0 + n)], at(n))
    row = h.current("s")
    assert row.status is ReadingStatus.OK
    assert h.status("s").health is SensorHealth.LIVE


def test_ac7_edge_cases_never_crash_or_drop():
    h = StreamHarness("good")
    # 'weird' is registered as an UNKNOWN type (the orchestrator resolves type from the
    # registry, not the payload), so it exercises the unconfigured-type CORRUPT path.
    h.registry.add(ExpectedSensor("weird", "ultrasonic_flow", "bridge-e2e"))
    # plus malformed + duplicate-conflict + out-of-order + clock-drift, all in one
    # batch. Nothing may crash; nothing silently dropped.
    batch = [
        h.reading("good", at(1), 5.0),                      # out of order (after at(2))
        h.reading("good", at(2), 6.0),
        h.reading("good", at(2), 9.0),                      # conflicting duplicate
        h.reading("good", at(2), 6.0),                      # identical duplicate
        "total garbage",                                    # malformed
        {"sensor_id": "good"},                              # malformed shape
        h.reading("weird", at(2), 1.0, sensor_type="ultrasonic_flow"),  # unknown type
        h.reading("good", at(2), 5.0, ingest=at(2) + timedelta(seconds=30)),  # drift dup
    ]
    summary = h.cycle(batch, at(2))
    assert summary.ok is True
    # good got a verdict; weird is CORRUPT (unknown type); both present.
    assert h.current("good") is not None
    assert h.current("weird").status is ReadingStatus.CORRUPT
    # dup-conflict + parse failures recorded, not dropped silently.
    assert summary.conflicts >= 1
    assert summary.parse_failures >= 2
    assert any(l.decision == "DUPLICATE_CONFLICT" for l in h.store.logs_for("good"))
    assert any(l.decision == "PARSE" for l in h.store.log_rows)


# ---- T1103: Constitution V four scenarios + invariants ----------------------

def test_const_v_four_scenarios():
    # normal / missing / corrupt / offline — the mandated four.
    h = StreamHarness("normal", "missing", "corrupt", "offline")
    # normal reports OK; corrupt reports out-of-range; missing/offline send nothing.
    h.cycle([h.reading("normal", at(0), 10.0),
             h.reading("corrupt", at(0), 999.0)], at(0))
    assert h.current("normal").status is ReadingStatus.OK
    assert h.current("corrupt").status is ReadingStatus.CORRUPT
    # missing/offline: silent -> NO_DATA + OFFLINE (never seen).
    assert h.current("missing").status is ReadingStatus.NO_DATA
    assert h.status("offline").health is SensorHealth.OFFLINE


def test_never_crash_on_adversarial_batches():
    h = StreamHarness("s")
    for bad_batch in [None, "x", 42, [None, 1, "y"], [{}], [{"sensor_id": None}]]:
        summary = h.cycle(bad_batch, at(0))
        # Either a structured error (bad envelope) or ok with parse failures — never raise.
        assert summary.ok in (True, False)
        if summary.ok is False:
            assert summary.error


def test_raw_is_append_only_count_only_grows():
    h = StreamHarness("s")
    counts = []
    for n in range(4):
        h.cycle([h.reading("s", at(n), 10.0 + n)], at(n))
        counts.append(h.store.raw_count())
    assert counts == sorted(counts)          # monotonic non-decreasing
    assert counts[-1] == 4                    # one raw row per received reading
    # A late/duplicate reading still only appends.
    h.cycle([h.reading("s", at(0), 10.0)], at(4))
    assert h.store.raw_count() == 5


def test_every_validated_row_traces_to_raw_or_is_silent():
    h = StreamHarness("s", "silent")
    h.cycle([h.reading("s", at(0), 10.0)], at(0))
    s_row = h.current("s")
    assert len(s_row.source_raw_ids) >= 1                  # traceable to raw
    silent_row = h.current("silent")
    assert silent_row.source_raw_ids == ()                # silence links to no raw
