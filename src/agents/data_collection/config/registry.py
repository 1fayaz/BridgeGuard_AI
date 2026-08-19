"""Expected-sensor registry (B1) — configuration, not code.

Answers the question the incoming batch cannot: *which sensors are supposed to be
reporting?* Without this, a sensor that sends nothing produces no row at all, and
silence gets mistaken for safety (the spec's headline failure mode). The
orchestrator iterates this registry so a fully-silent expected sensor is still
evaluated and can be flagged OFFLINE (FR-1/AC-1).

This is data, not logic: registering a new sensor (or sensor type) means adding an
entry here, never editing a check. Entries are TODO-seedable — a deployment fills
the real fleet in; the empty default keeps the module importable and testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.data_collection.config.sensor_profiles import (
    SensorProfile,
    UnknownSensorType,
    get_profile,
)


@dataclass(frozen=True, slots=True)
class ExpectedSensor:
    """A sensor the system expects to receive readings from."""

    sensor_id: str
    sensor_type: str
    bridge_id: str

    def profile(self) -> SensorProfile | UnknownSensorType:
        """Resolve this sensor's type profile (T103 semantics, never raises).

        A registry entry whose sensor_type is not in SENSOR_PROFILES surfaces the
        UnknownSensorType signal rather than crashing — a registered-but-unprofiled
        sensor is itself a config error the CORRUPT/unknown path must report.
        """
        return get_profile(self.sensor_type)


class SensorRegistry:
    """The set of sensors expected to report, keyed by sensor_id."""

    def __init__(self, sensors: list[ExpectedSensor] | None = None) -> None:
        self._by_id: dict[str, ExpectedSensor] = {}
        for s in sensors or []:
            self._by_id[s.sensor_id] = s

    def add(self, sensor: ExpectedSensor) -> None:
        self._by_id[sensor.sensor_id] = sensor

    def get(self, sensor_id: str) -> ExpectedSensor | None:
        return self._by_id.get(sensor_id)

    def is_expected(self, sensor_id: str) -> bool:
        return sensor_id in self._by_id

    def all(self) -> list[ExpectedSensor]:
        """Every expected sensor — what the orchestrator iterates each cycle."""
        return list(self._by_id.values())

    def missing_from(self, reporting_ids: set[str]) -> list[ExpectedSensor]:
        """Expected sensors that did NOT appear in this cycle's batch.

        These are exactly the silent sensors that must still be evaluated (→ OFFLINE
        via liveness) instead of vanishing from the output.
        """
        return [s for s in self._by_id.values() if s.sensor_id not in reporting_ids]

    def __len__(self) -> int:
        return len(self._by_id)


# Default fleet registry. Empty until a deployment seeds the real sensors
# (TODO-seedable, per the config-not-code decision). Tests construct their own.
DEFAULT_REGISTRY: SensorRegistry = SensorRegistry()
