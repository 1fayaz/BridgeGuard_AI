"""T602 + T603 — AC-4: short gap interpolated, long gap NO_DATA + OFFLINE co-exist.

T602 / AC-4a: 1 and 2 missing -> value = linear interpolation of neighbours,
              is_interpolated=True, status INTERPOLATED. The sensor stays LIVE
              (set by liveness, since <3 consecutive missed).
T603 / AC-4b: 3+ missing -> reading-status NO_DATA (value null) from gap-fill, AND
              sensor-status OFFLINE from LIVENESS (same 3-missed condition). Both axes
              are co-emitted, and the OFFLINE write originates from the liveness path,
              NOT from gap-fill (G2 single owner). = AC-4 + Q4 + G2.

These two checks are deliberately exercised together to prove the two axes co-exist
without either owning the other's status.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.checks.gap_fill import TimelineSlot, fill_gaps
from agents.data_collection.checks.liveness import (
    SensorLivenessState,
    check_liveness,
)
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus, SensorHealth

UTC = timezone.utc
T0 = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # interp_cap=2, offline_after_n=3, cadence 60s


def slot(i: int, value: float | None) -> TimelineSlot:
    return TimelineSlot(sensor_time=T0 + timedelta(seconds=60 * i), value=value)


# ----- T602 / AC-4a: short gap ------------------------------------------------

def test_ac4a_one_missing_interpolated_and_sensor_live():
    timeline = [slot(0, 10.0), slot(1, None), slot(2, 20.0)]
    filled = fill_gaps(timeline, PROFILE)
    assert filled[1].status is ReadingStatus.INTERPOLATED
    assert filled[1].is_interpolated is True
    assert filled[1].value == 15.0

    # Liveness over the same timeline: last real reading is slot(2); evaluate shortly
    # after. Only a 1-slot gap occurred -> well under 3 missed -> LIVE.
    now = T0 + timedelta(seconds=60 * 2 + 30)  # just after the last present slot
    live = check_liveness(
        SensorLivenessState("s", last_seen=slot(2, 20.0).sensor_time), now, PROFILE
    )
    assert live.health is SensorHealth.LIVE


def test_ac4a_two_missing_interpolated_and_sensor_live():
    timeline = [slot(0, 0.0), slot(1, None), slot(2, None), slot(3, 30.0)]
    filled = fill_gaps(timeline, PROFILE)
    assert [s.status for s in filled[1:3]] == [ReadingStatus.INTERPOLATED] * 2
    assert filled[1].value == 10.0 and filled[2].value == 20.0
    # last present slot(3); 2 missed earlier but it has since reported -> LIVE.
    now = T0 + timedelta(seconds=60 * 3 + 10)
    live = check_liveness(
        SensorLivenessState("s", last_seen=slot(3, 30.0).sensor_time), now, PROFILE
    )
    assert live.health is SensorHealth.LIVE


# ----- T603 / AC-4b: long gap + co-existence ----------------------------------

def test_ac4b_long_gap_no_data_and_offline_coexist():
    # 3 consecutive missing after slot(0); no further reading. last_seen = slot(0).
    timeline = [
        slot(0, 5.0), slot(1, None), slot(2, None), slot(3, None),
    ]
    filled = fill_gaps(timeline, PROFILE)

    # Reading-status axis (gap-fill): the 3-slot gap is NO_DATA, value null, not interp.
    gap = filled[1:4]
    assert all(s.status is ReadingStatus.NO_DATA for s in gap)
    assert all(s.value is None for s in gap)
    assert all(s.is_interpolated is False for s in gap)

    # Sensor-status axis (liveness): 3 intervals since the last reading -> OFFLINE.
    now = slot(0, 5.0).sensor_time + timedelta(seconds=60 * 3)
    live = check_liveness(
        SensorLivenessState("s", last_seen=slot(0, 5.0).sensor_time), now, PROFILE
    )
    assert live.health is SensorHealth.OFFLINE

    # Co-existence (Q4 / AC-4): both axes emitted for the same sensor/window — NO_DATA
    # on the reading axis AND OFFLINE on the device axis, neither replacing the other.
    assert gap[0].status is ReadingStatus.NO_DATA
    assert live.health is SensorHealth.OFFLINE


def test_ac4b_offline_originates_from_liveness_not_gap_fill():
    # G2 single owner: gap-fill must NOT be the thing that produces OFFLINE. Structural
    # proof — fill_gaps output has no sensor-status vocabulary at all; OFFLINE comes
    # exclusively from check_liveness.
    timeline = [slot(0, 5.0), slot(1, None), slot(2, None), slot(3, None)]
    filled = fill_gaps(timeline, PROFILE)
    produced_statuses = {s.status for s in filled}
    # Nothing gap-fill produced is a SensorHealth value.
    assert all(not isinstance(s, SensorHealth) for s in produced_statuses)
    assert SensorHealth.OFFLINE not in produced_statuses  # different enum entirely

    # The OFFLINE verdict is only reachable via the liveness call.
    now = slot(0, 5.0).sensor_time + timedelta(seconds=60 * 3)
    live = check_liveness(
        SensorLivenessState("s", last_seen=slot(0, 5.0).sensor_time), now, PROFILE
    )
    assert live.health is SensorHealth.OFFLINE
    assert "missed" in live.reason.lower() or "silent" in live.reason.lower()
