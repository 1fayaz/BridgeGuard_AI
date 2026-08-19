"""T401 — check_range function-level acceptance.

Acceptance (tasks.md T401): pure; CORRUPT below min / above max; reason is
human-readable and names the violated bound + unit; unknown profile -> CORRUPT;
None/NaN/non-numeric -> CORRUPT with no crash. (AC-2 behaviour is exercised in T402.)

Uses a fixture profile with concrete bounds, since real bounds are TODO sentinels.
"""
from __future__ import annotations

import math

from agents.data_collection.checks.range_check import RangeResult, check_range
from agents.data_collection.config.sensor_profiles import (
    TODO,
    SensorProfile,
    UnknownSensorType,
)
from agents.data_collection.statuses import ReadingStatus

# Concrete bounds for testing; real profiles keep phys_min/max = TODO.
PROFILE = SensorProfile(
    sensor_type="crack_sensor",
    unit="mm",
    cadence_s=60.0,
    phys_min=0.0,
    phys_max=50.0,
    clock_drift_tolerance_s=5.0,
)


def test_in_range_value_is_ok():
    res = check_range(25.0, PROFILE)
    assert res.status is ReadingStatus.OK


def test_below_min_is_corrupt_reason_names_bound_and_unit():
    res = check_range(-1.0, PROFILE)
    assert res.status is ReadingStatus.CORRUPT
    assert "below" in res.reason
    assert "0.0" in res.reason       # the violated bound
    assert "mm" in res.reason        # the unit
    assert "-1.0" in res.reason      # the offending value


def test_above_max_is_corrupt_reason_names_bound_and_unit():
    res = check_range(75.0, PROFILE)
    assert res.status is ReadingStatus.CORRUPT
    assert "above" in res.reason
    assert "50.0" in res.reason
    assert "mm" in res.reason


def test_exact_boundaries_are_in_range():
    # Boundaries are inclusive: a value AT the limit is valid, not corrupt.
    assert check_range(0.0, PROFILE).status is ReadingStatus.OK
    assert check_range(50.0, PROFILE).status is ReadingStatus.OK


def test_none_is_corrupt_no_crash():
    res = check_range(None, PROFILE)
    assert res.status is ReadingStatus.CORRUPT
    assert "non-numeric" in res.reason


def test_nan_and_inf_are_corrupt():
    assert check_range(math.nan, PROFILE).status is ReadingStatus.CORRUPT
    assert check_range(math.inf, PROFILE).status is ReadingStatus.CORRUPT
    assert check_range(-math.inf, PROFILE).status is ReadingStatus.CORRUPT


def test_non_numeric_string_is_corrupt():
    res = check_range("12.5", PROFILE)
    assert res.status is ReadingStatus.CORRUPT
    assert "non-numeric" in res.reason


def test_bool_is_rejected_not_treated_as_int():
    # True == 1 in Python; a bool is never a valid sensor value.
    res = check_range(True, PROFILE)
    assert res.status is ReadingStatus.CORRUPT


def test_unknown_type_is_corrupt_with_register_reason():
    res = check_range(10.0, UnknownSensorType("ultrasonic_flow"))
    assert res.status is ReadingStatus.CORRUPT
    assert res.config_incomplete is True
    assert "not registered" in res.reason


def test_todo_bounds_are_corrupt_not_guessed():
    # A registered type whose bounds are still TODO must not silently pass/fail.
    todo_profile = SensorProfile(
        "unconfigured", "x", cadence_s=60.0, phys_min=TODO, phys_max=TODO,
    )
    res = check_range(42.0, todo_profile)
    assert res.status is ReadingStatus.CORRUPT
    assert res.config_incomplete is True
    assert "todo" in res.reason.lower() or "unset" in res.reason.lower()


def test_integer_value_accepted():
    res = check_range(25, PROFILE)
    assert res.status is ReadingStatus.OK


def test_returns_range_result_type():
    assert isinstance(check_range(1.0, PROFILE), RangeResult)
