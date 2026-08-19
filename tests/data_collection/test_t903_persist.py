"""T903 — persist cycle to FakeStore + decision log [DB-DEP].

Acceptance (tasks.md T903, fake store): a cycle producing a CORRUPT + a clock-drift + a
dup-conflict yields exactly the expected validated + log rows, each WITH a reason; every
derived validated row links to its raw source id(s); a clean OK reading is recorded by
its validated row, NOT spammed to the decision_log; raw is append-only.

Interpolation and late-arrival CORRECTION are cross-cycle behaviours (T601/T801); their
store-level writes (interpolated validated row, supersede chain) are verified directly
against the store here, and end-to-end across cycles in T1101/T1102. [DB-DEP: live
Supabase enforcement deferred — the FakeStore mirrors the migration guarantees.]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agents.data_collection.agent import process_cycle
from agents.data_collection.config.registry import ExpectedSensor, SensorRegistry
from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES, SensorProfile
from agents.data_collection.statuses import ReadingStatus, SensorHealth
from agents.data_collection.store import (
    FakeStore,
    RawAppendOnlyViolation,
    ValidatedRow,
    persist_cycle,
)

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
TEST_TYPE = "test_persist"
TEST_PROFILE = SensorProfile(
    sensor_type=TEST_TYPE, unit="x", cadence_s=60.0,
    phys_min=-100.0, phys_max=100.0, clock_drift_tolerance_s=5.0,
)


def setup_module(module):
    SENSOR_PROFILES[TEST_TYPE] = TEST_PROFILE


def teardown_module(module):
    SENSOR_PROFILES.pop(TEST_TYPE, None)


def payload(sensor_id, secs, value, ingest_secs=None):
    p = {"sensor_id": sensor_id, "sensor_type": TEST_TYPE,
         "sensor_time": (NOW + timedelta(seconds=secs)).isoformat(), "value": value}
    if ingest_secs is not None:
        p["ingest_time"] = (NOW + timedelta(seconds=ingest_secs)).isoformat()
    return p


def registry(*ids):
    return SensorRegistry([ExpectedSensor(i, TEST_TYPE, "b") for i in ids])


# --- append-only raw ---------------------------------------------------------

def test_raw_is_append_only_and_grows():
    store = FakeStore()
    rid1 = store.append_raw("a", TEST_TYPE, NOW, NOW, 1.0, {})
    rid2 = store.append_raw("a", TEST_TYPE, NOW, NOW, 2.0, {})
    assert store.raw_count() == 2
    assert rid1 != rid2
    with pytest.raises(RawAppendOnlyViolation):
        store._forbid_raw_mutation()  # mirrors the 0001 block trigger


# --- orchestrated cycle -> persisted rows ------------------------------------

def test_corrupt_clockdrift_dupconflict_persist_with_reasons():
    store = FakeStore()
    reg = registry("corrupt", "drift", "dup", "ok")
    batch = [
        payload("corrupt", 0, 999.0),                 # out of range -> CORRUPT
        payload("drift", 0, 5.0, ingest_secs=30),     # 30s drift -> clock_drift flag
        payload("dup", 0, 5.0), payload("dup", 0, 9.0),  # conflicting duplicate
        payload("ok", 0, 10.0),                       # clean OK
    ]
    # Append raw on receipt and remember the ids per sensor (provenance).
    raw_ids: dict[str, list[int]] = {}
    for p in batch:
        rid = store.append_raw(p["sensor_id"], TEST_TYPE,
                               datetime.fromisoformat(p["sensor_time"]),
                               None, p["value"] if isinstance(p["value"], (int, float)) else None,
                               p)
        raw_ids.setdefault(p["sensor_id"], []).append(rid)

    cycle = process_cycle(batch, reg, {}, NOW)
    persist_cycle(store, cycle, raw_ids, NOW)

    # One validated row per expected sensor (4).
    assert len(store.validated_rows) == 4
    by_id = {r.sensor_id: r for r in store.validated_rows}
    assert by_id["corrupt"].status is ReadingStatus.CORRUPT
    assert by_id["drift"].status is ReadingStatus.OK
    assert by_id["drift"].clock_drift is True
    assert by_id["dup"].value == 5.0          # first-received kept
    assert by_id["ok"].status is ReadingStatus.OK

    # Every reporting sensor's validated row links to its raw source id(s).
    for sid in ("corrupt", "drift", "dup", "ok"):
        assert by_id[sid].source_raw_ids == tuple(raw_ids[sid][:1]) or \
               set(by_id[sid].source_raw_ids).issubset(set(raw_ids[sid]))
        assert len(by_id[sid].source_raw_ids) >= 1

    # Decision log: each non-OK event recorded WITH a reason.
    assert {l.decision for l in store.logs_for("corrupt")} == {"RANGE"}
    assert store.logs_of("CLOCK_DRIFT") and store.logs_of("CLOCK_DRIFT")[0].reason
    assert store.logs_of("DUPLICATE_CONFLICT")[0].reason
    assert all(l.reason for l in store.log_rows)  # no reasonless audit entries

    # OK reading is NOT spammed to the decision log.
    assert store.logs_for("ok") == []


def test_silent_sensor_offline_status_and_no_data_row():
    store = FakeStore()
    reg = registry("silent")
    cycle = process_cycle([], reg, {}, NOW)
    persist_cycle(store, cycle, {}, NOW)

    status = store.status_rows["silent"]
    assert status.health is SensorHealth.OFFLINE
    row = store.current_validated("silent")[0]
    assert row.status is ReadingStatus.NO_DATA
    assert row.source_raw_ids == ()   # silence links to no raw row


# --- store-level correction + interpolation (cross-cycle behaviours) ---------

def test_correction_supersede_chain_append_not_overwrite():
    store = FakeStore()
    # Original verdict NO_DATA.
    old = ValidatedRow(store._next_row_id, "a", NOW, None, ReadingStatus.NO_DATA,
                       False, False, (1,), "gap")
    old_id = store.insert_validated(old)
    # A late arrival recomputes to OK: append a NEW row, then supersede the old.
    new = ValidatedRow(store._next_row_id, "a", NOW, 12.5, ReadingStatus.OK,
                       False, False, (1, 2), "late-arrival recompute")
    new_id = store.insert_validated(new)
    store.supersede(old_id, new_id)

    # Old row preserved (not deleted), now points at the new one.
    rows = {r.row_id: r for r in store.validated_rows}
    assert rows[old_id].status is ReadingStatus.NO_DATA      # history intact
    assert rows[old_id].superseded_by == new_id
    # current verdict is the new OK row only.
    current = store.current_validated("a")
    assert len(current) == 1 and current[0].status is ReadingStatus.OK


def test_interpolated_row_persists_with_flag_and_sources():
    store = FakeStore()
    row = ValidatedRow(store._next_row_id, "a", NOW, 15.0, ReadingStatus.INTERPOLATED,
                       True, False, (3, 4), "linear interpolation of 1-slot gap")
    store.insert_validated(row)
    saved = store.validated_rows[0]
    assert saved.status is ReadingStatus.INTERPOLATED
    assert saved.is_interpolated is True
    assert saved.source_raw_ids == (3, 4)   # links to the bracketing raw readings
    assert saved.reason
