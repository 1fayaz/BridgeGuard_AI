"""T501 — compute_baseline acceptance (G1 OK-only + G5 100∩24h intersection).

Acceptance (tasks.md T501):
  (i)   >100 OK readings within 24h -> exactly 100 kept.
  (ii)  <100 readings spanning >24h -> only the within-24h subset kept (both caps
        applied as an intersection, asserted separately).
  (iii) a window polluted with SPIKE/CORRUPT/PENDING/NO_DATA/interpolated values
        excludes them from mean/sigma (G1).
  (iv)  insufficient (<2) and zero-variance handled without error.

Uses a fixture profile with concrete cadence; baseline_max_n/age default to 100/24h.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.data_collection.checks.spike import (
    BaselineResult,
    HistoryReading,
    compute_baseline,
)
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # baseline_max_n=100, baseline_max_age_h=24 (defaults)


def ok(ts: datetime, value: float) -> HistoryReading:
    return HistoryReading(sensor_time=ts, value=value, status=ReadingStatus.OK)


def test_i_more_than_100_within_24h_keeps_exactly_100():
    # 150 OK readings, all within 24h, 1 minute apart.
    history = [ok(NOW - timedelta(minutes=i), value=10.0 + (i % 5)) for i in range(150)]
    res = compute_baseline(history, NOW, PROFILE)
    assert res.usable is True
    assert res.n == 100  # the n=100 cap bites, not the 24h cap


def test_i_keeps_the_MOST_RECENT_100_not_the_oldest():
    # Recent readings are ~100.0; old ones ~0.0. If the newest 100 are kept, mean ~100.
    recent = [ok(NOW - timedelta(minutes=i), 100.0) for i in range(100)]
    old = [ok(NOW - timedelta(minutes=200 + i), 0.0) for i in range(50)]  # still <24h
    res = compute_baseline(recent + old, NOW, PROFILE)
    assert res.n == 100
    assert abs(res.mean - 100.0) < 1e-9  # only the recent block survived


def test_ii_under_100_spanning_over_24h_keeps_only_within_24h():
    # 40 readings within 24h + 30 readings older than 24h. n<100 so the age cap is the
    # one that bites: only the 40 within-24h are kept.
    within = [ok(NOW - timedelta(hours=h), 5.0) for h in range(0, 20)]      # 20, <24h
    within += [ok(NOW - timedelta(hours=23, minutes=m), 5.0) for m in range(20)]  # 20 more <24h
    older = [ok(NOW - timedelta(hours=25 + h), 999.0) for h in range(30)]  # 30, >24h
    res = compute_baseline(within + older, NOW, PROFILE)
    assert res.n == 40                       # only within-24h kept
    assert abs(res.mean - 5.0) < 1e-9        # the 999.0 old values excluded


def test_ii_age_cap_excludes_just_over_24h():
    inside = ok(NOW - timedelta(hours=23, minutes=59), 1.0)
    outside = ok(NOW - timedelta(hours=24, minutes=1), 1000.0)
    res = compute_baseline([inside, outside, ok(NOW, 1.0)], NOW, PROFILE)
    assert res.n == 2  # the >24h reading is excluded; only the two within-24h remain


def test_iii_pollution_excluded_from_mean_and_std():
    # Trustworthy values all 10.0 -> mean 10, std 0... so add a little spread, then
    # pollute with non-OK / interpolated values that would wreck the stats if included.
    base = [
        ok(NOW - timedelta(minutes=1), 9.0),
        ok(NOW - timedelta(minutes=2), 10.0),
        ok(NOW - timedelta(minutes=3), 11.0),
    ]
    polluters = [
        HistoryReading(NOW - timedelta(minutes=4), 1000.0, ReadingStatus.SPIKE),
        HistoryReading(NOW - timedelta(minutes=5), -1000.0, ReadingStatus.CORRUPT),
        HistoryReading(NOW - timedelta(minutes=6), 500.0, ReadingStatus.PENDING),
        HistoryReading(NOW - timedelta(minutes=7), 0.0, ReadingStatus.NO_DATA),
        HistoryReading(NOW - timedelta(minutes=8), 10.0, ReadingStatus.INTERPOLATED,
                       is_interpolated=True),
    ]
    res = compute_baseline(base + polluters, NOW, PROFILE)
    assert res.n == 3                        # only the 3 OK readings counted
    assert abs(res.mean - 10.0) < 1e-9       # polluters did not shift the mean


def test_iv_insufficient_samples_not_usable_no_crash():
    res = compute_baseline([ok(NOW, 5.0)], NOW, PROFILE)  # only 1 sample
    assert res.usable is False
    assert res.n == 1
    assert "insufficient" in res.reason.lower()


def test_iv_empty_history_not_usable():
    res = compute_baseline([], NOW, PROFILE)
    assert res.usable is False
    assert res.n == 0


def test_iv_zero_variance_not_usable_no_div_by_zero():
    # All identical -> std 0 -> any deviation is infinite sigma. Must be flagged unusable.
    history = [ok(NOW - timedelta(minutes=i), 42.0) for i in range(10)]
    res = compute_baseline(history, NOW, PROFILE)
    assert res.usable is False
    assert res.std == 0.0
    assert "zero-variance" in res.reason.lower()


def test_known_mean_and_std_correct():
    # values 2,4,4,4,5,5,7,9 -> mean 5, sample std (n-1) = sqrt(32/7) ~ 2.138...
    vals = [2, 4, 4, 4, 5, 5, 7, 9]
    history = [ok(NOW - timedelta(minutes=i), float(v)) for i, v in enumerate(vals)]
    res = compute_baseline(history, NOW, PROFILE)
    assert res.usable is True
    assert abs(res.mean - 5.0) < 1e-9
    assert abs(res.std - (32 / 7) ** 0.5) < 1e-9


def test_returns_baseline_result_type():
    assert isinstance(compute_baseline([], NOW, PROFILE), BaselineResult)
