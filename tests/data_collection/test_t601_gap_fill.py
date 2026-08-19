"""T601 — fill_gaps acceptance.

Acceptance (tasks.md T601): pure; interpolation linear (midpoint exact); cap=2
enforced (3+ -> NO_DATA); gap-fill returns NO sensor-status mutation (G2 single owner
of OFFLINE — asserted by the absence of any sensor-status field on the output).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import fields

from agents.data_collection.checks.gap_fill import (
    FilledSlot,
    TimelineSlot,
    fill_gaps,
)
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus

UTC = timezone.utc
T0 = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # interp_cap = 2


def slot(i: int, value: float | None) -> TimelineSlot:
    return TimelineSlot(sensor_time=T0 + timedelta(seconds=60 * i), value=value)


def test_one_missing_linear_interpolated():
    # present 10 @0, gap @1, present 20 @2 -> filled = 15.0 (exact midpoint).
    out = fill_gaps([slot(0, 10.0), slot(1, None), slot(2, 20.0)], PROFILE)
    assert out[1].status is ReadingStatus.INTERPOLATED
    assert out[1].is_interpolated is True
    assert out[1].value == 15.0


def test_two_missing_linear_interpolated_thirds():
    # present 0 @0, gaps @1,@2, present 30 @3 -> 10.0 and 20.0 (even thirds).
    out = fill_gaps(
        [slot(0, 0.0), slot(1, None), slot(2, None), slot(3, 30.0)], PROFILE
    )
    assert [s.status for s in out[1:3]] == [ReadingStatus.INTERPOLATED] * 2
    assert out[1].value == 10.0
    assert out[2].value == 20.0


def test_three_missing_is_no_data_not_interpolated():
    # Cap=2: a 3-slot gap is NO_DATA, value stays null, never interpolated.
    out = fill_gaps(
        [slot(0, 0.0), slot(1, None), slot(2, None), slot(3, None), slot(4, 40.0)],
        PROFILE,
    )
    gap = out[1:4]
    assert all(s.status is ReadingStatus.NO_DATA for s in gap)
    assert all(s.value is None for s in gap)
    assert all(s.is_interpolated is False for s in gap)
    assert "cap" in gap[0].reason.lower()


def test_present_readings_are_ok():
    out = fill_gaps([slot(0, 5.0), slot(1, 6.0)], PROFILE)
    assert all(s.status is ReadingStatus.OK for s in out)
    assert [s.value for s in out] == [5.0, 6.0]


def test_leading_gap_unbracketed_is_no_data():
    # A gap at the very start has no left value to interpolate from -> NO_DATA even
    # though it's only 1 slot (no fabricating an extrapolated value).
    out = fill_gaps([slot(0, None), slot(1, 10.0)], PROFILE)
    assert out[0].status is ReadingStatus.NO_DATA
    assert "bracketed" in out[0].reason.lower()


def test_trailing_gap_unbracketed_is_no_data():
    out = fill_gaps([slot(0, 10.0), slot(1, None)], PROFILE)
    assert out[1].status is ReadingStatus.NO_DATA


def test_no_sensor_status_field_g2():
    # Structural G2 guarantee: FilledSlot cannot carry a sensor-status at all.
    field_names = {f.name for f in fields(FilledSlot)}
    assert "sensor_status" not in field_names
    assert "health" not in field_names
    # The output vocabulary is strictly the reading-status axis.
    out = fill_gaps([slot(0, 1.0), slot(1, None), slot(2, 3.0)], PROFILE)
    assert {s.status for s in out} <= {
        ReadingStatus.OK, ReadingStatus.INTERPOLATED, ReadingStatus.NO_DATA,
    }


def test_negative_slope_interpolation():
    out = fill_gaps([slot(0, 20.0), slot(1, None), slot(2, 10.0)], PROFILE)
    assert out[1].value == 15.0


def test_pure_does_not_mutate_input():
    timeline = [slot(0, 10.0), slot(1, None), slot(2, 20.0)]
    snapshot = [(s.sensor_time, s.value) for s in timeline]
    fill_gaps(timeline, PROFILE)
    assert [(s.sensor_time, s.value) for s in timeline] == snapshot


def test_multiple_gaps_independent():
    # short gap (1) then long gap (3): first interpolated, second NO_DATA.
    out = fill_gaps(
        [
            slot(0, 0.0), slot(1, None), slot(2, 20.0),         # short -> interp 10
            slot(3, None), slot(4, None), slot(5, None),        # long -> NO_DATA
            slot(6, 60.0),
        ],
        PROFILE,
    )
    assert out[1].status is ReadingStatus.INTERPOLATED and out[1].value == 10.0
    assert all(out[k].status is ReadingStatus.NO_DATA for k in (3, 4, 5))


def test_returns_filled_slot_list():
    out = fill_gaps([slot(0, 1.0)], PROFILE)
    assert isinstance(out[0], FilledSlot)
