"""T502 — check_spike acceptance.

Acceptance (tasks.md T502): a >3σ value yields candidate -> PENDING; a ≤3σ value
yields NORMAL; an insufficient/unusable baseline yields NORMAL (not a false spike).
"""
from __future__ import annotations

import math

from agents.data_collection.checks.spike import (
    BaselineResult,
    SpikeOutcome,
    SpikeResult,
    check_spike,
)
from agents.data_collection.config.sensor_profiles import SensorProfile

PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # zscore_threshold defaults to 3.0

USABLE = BaselineResult(mean=10.0, std=2.0, n=50, usable=True, reason="ok")


def test_beyond_3sigma_is_candidate_pending():
    # mean 10, std 2 -> 3σ band is [4, 16]. 17 is +3.5σ.
    res = check_spike(17.0, USABLE, PROFILE)
    assert res.status is SpikeOutcome.PENDING
    assert res.is_candidate is True
    assert abs(res.z - 3.5) < 1e-9
    assert "candidate" in res.reason.lower()


def test_negative_beyond_3sigma_is_candidate():
    res = check_spike(2.0, USABLE, PROFILE)  # -4σ
    assert res.status is SpikeOutcome.PENDING
    assert res.is_candidate is True
    assert res.z < 0


def test_within_3sigma_is_normal():
    res = check_spike(14.0, USABLE, PROFILE)  # +2σ
    assert res.status is SpikeOutcome.NORMAL
    assert res.is_candidate is False


def test_exactly_3sigma_is_normal_not_spike():
    # Threshold is strict ">": exactly +3σ (value 16) is NORMAL.
    res = check_spike(16.0, USABLE, PROFILE)
    assert abs(res.z - 3.0) < 1e-9
    assert res.status is SpikeOutcome.NORMAL


def test_just_over_3sigma_is_candidate():
    res = check_spike(16.001, USABLE, PROFILE)
    assert res.z > 3.0
    assert res.status is SpikeOutcome.PENDING


def test_unusable_baseline_is_normal_not_false_spike():
    unusable = BaselineResult(mean=math.nan, std=math.nan, n=1, usable=False,
                              reason="insufficient baseline: 1 sample")
    res = check_spike(99999.0, unusable, PROFILE)
    assert res.status is SpikeOutcome.NORMAL  # cannot judge -> not a spike
    assert res.is_candidate is False
    assert math.isnan(res.z)
    assert "cannot judge" in res.reason.lower()


def test_zero_variance_baseline_is_normal():
    zero_var = BaselineResult(mean=42.0, std=0.0, n=10, usable=False,
                              reason="zero-variance baseline")
    res = check_spike(9999.0, zero_var, PROFILE)
    assert res.status is SpikeOutcome.NORMAL
    assert res.is_candidate is False


def test_custom_threshold_from_profile():
    from dataclasses import replace
    strict = replace(PROFILE, zscore_threshold=2.0)
    # value 15 = +2.5σ: NORMAL at threshold 3, candidate at threshold 2.
    assert check_spike(15.0, USABLE, PROFILE).status is SpikeOutcome.NORMAL
    assert check_spike(15.0, USABLE, strict).status is SpikeOutcome.PENDING


def test_returns_spike_result_type():
    assert isinstance(check_spike(10.0, USABLE, PROFILE), SpikeResult)
