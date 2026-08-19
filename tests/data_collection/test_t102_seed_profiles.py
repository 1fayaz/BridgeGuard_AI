"""T102 — the seven sensor types are seeded; every field present; TODOs flagged."""
from __future__ import annotations

from agents.data_collection.config.sensor_profiles import (
    SENSOR_PROFILES,
    SensorProfile,
)

EXPECTED_TYPES = {
    "accelerometer",
    "strain_gauge",
    "crack_sensor",
    "load_cell",
    "temperature",
    "tiltmeter",
    "displacement_lvdt",
}


def test_all_seven_types_present():
    assert set(SENSOR_PROFILES.keys()) == EXPECTED_TYPES
    assert len(SENSOR_PROFILES) == 7


def test_each_profile_has_every_field_and_unit():
    for stype, p in SENSOR_PROFILES.items():
        assert isinstance(p, SensorProfile)
        assert p.sensor_type == stype
        assert p.unit  # non-empty unit string from the README table
        # settled defaults present on every seeded profile
        assert p.offline_after_n == 3
        assert p.confirm_count == 3
        assert p.pending_timeout_mult == 3
        assert p.interp_cap == 2
        assert p.baseline_max_n == 100
        assert p.baseline_max_age_h == 24.0


def test_per_type_constants_are_todo_flagged():
    # Every seeded type must be NOT fully configured: bounds, cadence, and
    # drift tolerance are all TODO until an engineer supplies them.
    for stype, p in SENSOR_PROFILES.items():
        assert p.bounds_are_todo is True, stype
        assert p.cadence_is_todo is True, stype
        assert p.drift_tolerance_is_todo is True, stype
        assert p.is_fully_configured is False, stype


def test_units_match_readme_ingestion_table():
    assert SENSOR_PROFILES["accelerometer"].unit == "m/s^2"
    assert SENSOR_PROFILES["strain_gauge"].unit == "microstrain"
    assert SENSOR_PROFILES["crack_sensor"].unit == "mm"
    assert SENSOR_PROFILES["load_cell"].unit == "kN"
    assert SENSOR_PROFILES["temperature"].unit == "degC"
    assert SENSOR_PROFILES["tiltmeter"].unit == "degrees"
    assert SENSOR_PROFILES["displacement_lvdt"].unit == "mm"
