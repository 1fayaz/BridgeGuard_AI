"""T103 — get_profile: two distinguishable outcomes, never raises.

  * known type            -> SensorProfile
  * known but incomplete  -> SensorProfile with is_fully_configured == False
  * unknown type          -> UnknownSensorType (distinct shape, distinct reason)
"""
from __future__ import annotations

from agents.data_collection.config.sensor_profiles import (
    SensorProfile,
    UnknownSensorType,
    get_profile,
)


def test_known_type_returns_profile():
    result = get_profile("accelerometer")
    assert isinstance(result, SensorProfile)
    assert result.sensor_type == "accelerometer"


def test_unknown_type_returns_unknown_signal_not_raise():
    result = get_profile("nonexistent_sensor")
    assert isinstance(result, UnknownSensorType)
    assert result.sensor_type == "nonexistent_sensor"
    # No exception was raised getting here — that is the FR-6 / AC-7 guarantee.


def test_two_failure_modes_are_structurally_distinguishable():
    # Case 1: registered but not fully configured (TODO bounds) — a real profile.
    known_incomplete = get_profile("crack_sensor")
    assert isinstance(known_incomplete, SensorProfile)
    assert known_incomplete.is_fully_configured is False

    # Case 2: never registered — a different type entirely.
    unknown = get_profile("ghost_sensor")
    assert isinstance(unknown, UnknownSensorType)

    # The whole point: downstream can tell them apart by type.
    assert not isinstance(known_incomplete, UnknownSensorType)
    assert not isinstance(unknown, SensorProfile)


def test_distinct_reasons_for_alerts():
    unknown = get_profile("ghost_sensor")
    assert isinstance(unknown, UnknownSensorType)
    # Unknown-type reason is about REGISTERING the type...
    assert "not registered" in unknown.reason
    assert "ghost_sensor" in unknown.reason
    # ...which is distinct from the "finish configuring" path a known-but-
    # incomplete profile would drive (that one is a SensorProfile, not this signal).


def test_adding_a_type_is_config_only():
    # Every currently-registered type resolves to a profile, never unknown —
    # so registering a new type = adding a SENSOR_PROFILES entry, no logic change.
    from agents.data_collection.config.sensor_profiles import SENSOR_PROFILES

    for stype in SENSOR_PROFILES:
        assert isinstance(get_profile(stype), SensorProfile)
