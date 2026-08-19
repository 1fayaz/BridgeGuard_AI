"""T503 + T504 — AC-3: single-point spike vs confirmed shift (confirm-count=3).

T503 / AC-3a: a >3σ reading whose next 3 readings return to baseline -> finalised
              SPIKE, withheld from downstream.
T504 / AC-3b: a >3σ change sustained across the next 3 readings -> released as OK
              (a real signal, not suppressed).

baseline: mean 10, std 2 -> 3σ band [4, 16]. A candidate at 20 (+5σ) is the spike.
"""
from __future__ import annotations

from agents.data_collection.checks.spike import (
    BaselineResult,
    ConfirmationResult,
    confirm_spike,
)
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus

PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # confirm_count=3, zscore_threshold=3.0
BASELINE = BaselineResult(mean=10.0, std=2.0, n=50, usable=True, reason="ok")
CANDIDATE = 20.0  # +5σ


def test_t503_single_point_spike_returns_to_baseline_is_spike():
    # Next 3 readings back near the mean -> transient -> SPIKE, withheld.
    res = confirm_spike(CANDIDATE, [10.0, 11.0, 9.0], BASELINE, PROFILE)
    assert res.final_status is ReadingStatus.SPIKE
    assert res.confirmed is False
    assert "withheld" in res.reason.lower()


def test_t503_partial_return_still_spike():
    # 2 of 3 sustain but the 2nd drops back -> NOT all sustained -> SPIKE.
    res = confirm_spike(CANDIDATE, [21.0, 10.5, 22.0], BASELINE, PROFILE)
    assert res.final_status is ReadingStatus.SPIKE
    assert res.confirmed is False


def test_t504_sustained_shift_across_3_is_ok():
    # All next 3 stay well above +3σ -> real signal -> released OK.
    res = confirm_spike(CANDIDATE, [21.0, 22.0, 23.0], BASELINE, PROFILE)
    assert res.final_status is ReadingStatus.OK
    assert res.confirmed is True
    assert "real signal" in res.reason.lower()


def test_t504_sustained_uses_exactly_confirm_count_readings():
    # Only the first confirm_count (3) matter; a 4th below-band reading is irrelevant.
    res = confirm_spike(CANDIDATE, [21.0, 22.0, 23.0, 10.0], BASELINE, PROFILE)
    assert res.final_status is ReadingStatus.OK


def test_negative_direction_sustained_is_ok():
    # A downward spike candidate at 0 (-5σ), sustained low -> real shift -> OK.
    res = confirm_spike(0.0, [1.0, 0.5, 1.5], BASELINE, PROFILE)
    assert res.final_status is ReadingStatus.OK
    assert res.confirmed is True


def test_direction_mismatch_is_not_sustained():
    # Downward candidate but subsequent readings spike UP past +3σ: opposite side,
    # not a sustained downward shift -> SPIKE (transient/erratic, withheld).
    res = confirm_spike(0.0, [21.0, 22.0, 23.0], BASELINE, PROFILE)
    assert res.final_status is ReadingStatus.SPIKE
    assert res.confirmed is False


def test_returns_confirmation_result_type():
    assert isinstance(
        confirm_spike(CANDIDATE, [21.0, 22.0, 23.0], BASELINE, PROFILE),
        ConfirmationResult,
    )
