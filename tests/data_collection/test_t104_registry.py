"""T104 — expected-sensor registry: silence is evaluated, not an absent row."""
from __future__ import annotations

from agents.data_collection.config.registry import (
    ExpectedSensor,
    SensorRegistry,
)
from agents.data_collection.config.sensor_profiles import (
    SensorProfile,
    UnknownSensorType,
)


def _fixture_registry() -> SensorRegistry:
    return SensorRegistry(
        [
            ExpectedSensor("acc-1", "accelerometer", "bridge-04"),
            ExpectedSensor("strain-1", "strain_gauge", "bridge-04"),
            ExpectedSensor("crack-1", "crack_sensor", "bridge-07"),
        ]
    )


def test_registry_lists_expected_sensors_with_type():
    reg = _fixture_registry()
    assert len(reg) == 3
    acc = reg.get("acc-1")
    assert acc is not None
    assert acc.sensor_type == "accelerometer"
    assert acc.bridge_id == "bridge-04"
    assert reg.is_expected("acc-1") is True
    assert reg.is_expected("ghost") is False


def test_silent_sensor_is_surfaced_not_dropped():
    # B1 core: a sensor in the registry but absent from the batch must still be
    # evaluated. missing_from() is what the orchestrator uses to find silent ones.
    reg = _fixture_registry()
    reporting = {"acc-1"}  # only acc-1 sent a reading this cycle
    missing = reg.missing_from(reporting)
    missing_ids = {s.sensor_id for s in missing}
    assert missing_ids == {"strain-1", "crack-1"}  # these get OFFLINE via liveness
    # The silent sensors are returned as evaluable objects, not omitted.
    assert all(isinstance(s, ExpectedSensor) for s in missing)


def test_all_returns_every_expected_sensor_for_iteration():
    reg = _fixture_registry()
    ids = {s.sensor_id for s in reg.all()}
    assert ids == {"acc-1", "strain-1", "crack-1"}


def test_registered_sensor_resolves_its_profile():
    reg = _fixture_registry()
    acc = reg.get("acc-1")
    assert acc is not None
    assert isinstance(acc.profile(), SensorProfile)


def test_registered_unknown_type_surfaces_signal_no_crash():
    # A registry entry whose type is not profiled must NOT crash — it surfaces the
    # UnknownSensorType signal (feeds CORRUPT/unknown path), per T103 semantics.
    reg = SensorRegistry([ExpectedSensor("weird-1", "ultrasonic_flow", "bridge-09")])
    result = reg.get("weird-1").profile()  # type: ignore[union-attr]
    assert isinstance(result, UnknownSensorType)
    assert result.sensor_type == "ultrasonic_flow"


def test_adding_a_sensor_is_config_only():
    reg = SensorRegistry()
    assert len(reg) == 0
    reg.add(ExpectedSensor("acc-9", "accelerometer", "bridge-99"))
    assert reg.is_expected("acc-9") is True
    assert len(reg) == 1
