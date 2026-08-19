"""T101 — SensorProfile constructs with all fields; constants match decisions."""
from __future__ import annotations

import math

from agents.data_collection.config.sensor_profiles import TODO, SensorProfile


def test_profile_constructs_with_all_fields():
    p = SensorProfile(
        sensor_type="accelerometer",
        unit="m/s^2",
        cadence_s=10.0,
        phys_min=-20.0,
        phys_max=20.0,
        clock_drift_tolerance_s=5.0,
    )
    assert p.sensor_type == "accelerometer"
    assert p.unit == "m/s^2"
    assert p.cadence_s == 10.0
    assert p.phys_min == -20.0
    assert p.phys_max == 20.0
    assert p.clock_drift_tolerance_s == 5.0


def test_default_constants_match_decisions():
    p = SensorProfile("t", "u", cadence_s=10.0, phys_min=0.0, phys_max=1.0)
    assert p.offline_after_n == 3          # 3 missed reports -> OFFLINE
    assert p.zscore_threshold == 3.0       # +/-3 sigma
    assert p.baseline_max_n == 100         # baseline: last 100 readings ...
    assert p.baseline_max_age_h == 24.0    # ... OR 24h, whichever fewer
    assert p.confirm_count == 3            # spike confirmed by next 3
    assert p.pending_timeout_mult == 3     # PENDING timeout = 3x interval
    assert p.interp_cap == 2               # interpolate gaps of 1-2 only


def test_pending_timeout_is_three_times_cadence():
    p = SensorProfile("t", "u", cadence_s=10.0, phys_min=0.0, phys_max=1.0)
    assert p.pending_timeout_s == 30.0


def test_todo_sentinel_is_detected_not_silently_zero():
    # Defaults leave clock_drift_tolerance_s as TODO too.
    p = SensorProfile("t", "u", cadence_s=TODO, phys_min=TODO, phys_max=TODO)
    assert math.isnan(TODO)
    assert p.bounds_are_todo is True
    assert p.cadence_is_todo is True
    assert p.drift_tolerance_is_todo is True
    assert p.is_fully_configured is False


def test_fully_configured_requires_drift_tolerance_too():
    # Bounds + cadence set, but drift tolerance still TODO -> NOT fully configured.
    partial = SensorProfile("t", "u", cadence_s=10.0, phys_min=0.0, phys_max=1.0)
    assert partial.drift_tolerance_is_todo is True
    assert partial.is_fully_configured is False

    full = SensorProfile(
        "t", "u", cadence_s=10.0, phys_min=0.0, phys_max=1.0,
        clock_drift_tolerance_s=5.0,
    )
    assert full.is_fully_configured is True


def test_profile_is_immutable():
    p = SensorProfile("t", "u", cadence_s=10.0, phys_min=0.0, phys_max=1.0)
    try:
        p.cadence_s = 5.0  # type: ignore[misc]
    except (AttributeError, Exception):
        return
    raise AssertionError("SensorProfile should be frozen/immutable")
