"""Per-sensor-type validation profiles — configuration, not code.

A SensorProfile carries every parameter the four checks need for one sensor type.
Adding a new sensor type means adding a profile entry (T102), never editing check
logic (spec edge-case rule: "without changing the validation logic").

Settled decisions baked in as defaults (see tasks.md):
  offline_after_n     = 3   (3 missed reports -> OFFLINE, per-type, no wall clock)
  zscore_threshold    = 3.0 (+/-3 sigma)
  baseline_max_n      = 100  } sigma baseline = last 100 readings OR 24h,
  baseline_max_age_h  = 24   } whichever yields FEWER samples
  confirm_count       = 3   (spike confirmed/denied by next 3 readings)
  pending_timeout_mult= 3   (PENDING times out after 3x the configured interval)
  interp_cap          = 2   (interpolate gaps of 1-2; 3+ -> NO_DATA)

phys_min / phys_max / cadence_s are per-type and MUST be set by a structural
engineer. Until then they are the TODO sentinel and the profile is NOT production
-ready (see `is_fully_configured`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Sentinel marking a value that a structural engineer must still supply.
# Not 0/None: those are plausible real values and would hide an unset field.
TODO: Final[float] = float("nan")


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value that is not equal to itself


@dataclass(frozen=True, slots=True)
class SensorProfile:
    """Immutable validation profile for one sensor type."""

    sensor_type: str
    unit: str
    cadence_s: float                 # expected seconds between reports (TODO per type)
    phys_min: float                  # CORRUPT below this (TODO per type)
    phys_max: float                  # CORRUPT above this (TODO per type)
    offline_after_n: int = 3
    zscore_threshold: float = 3.0
    baseline_max_n: int = 100
    baseline_max_age_h: float = 24.0
    confirm_count: int = 3
    pending_timeout_mult: int = 3
    interp_cap: int = 2
    # Max allowed |sensor-timestamp - ingest-time| before a reading is flagged
    # clock_drift (G4). Per-type, TODO until a structural engineer supplies it.
    clock_drift_tolerance_s: float = TODO

    @property
    def bounds_are_todo(self) -> bool:
        """True if physical bounds are still unset (TODO sentinel)."""
        return _is_todo(self.phys_min) or _is_todo(self.phys_max)

    @property
    def cadence_is_todo(self) -> bool:
        """True if the expected reporting cadence is still unset."""
        return _is_todo(self.cadence_s)

    @property
    def drift_tolerance_is_todo(self) -> bool:
        """True if the clock-drift tolerance is still unset."""
        return _is_todo(self.clock_drift_tolerance_s)

    @property
    def is_fully_configured(self) -> bool:
        """True only when an engineer has supplied bounds, cadence, AND drift tolerance."""
        return (
            not self.bounds_are_todo
            and not self.cadence_is_todo
            and not self.drift_tolerance_is_todo
        )

    @property
    def pending_timeout_s(self) -> float:
        """Absolute timeout for a PENDING reading = 3x the configured interval."""
        return self.cadence_s * self.pending_timeout_mult


# --- Seed profiles for the seven iot-sensor-ingestion sensor types -----------
#
# Units are taken from skills/bridgeguard-skills-README.md (iot-sensor-ingestion).
# phys_min / phys_max / cadence_s / clock_drift_tolerance_s are TODO sentinels:
# a structural engineer MUST supply real values before production. Behaviour/logic
# does not depend on the specific numbers, only on these being configurable.
#
# NOTE: every per-type numeric here is intentionally TODO. Do NOT invent bounds for
# a safety-critical system — an unset bound is loudly flagged (is_fully_configured)
# rather than silently defaulted to a plausible-looking number.

_SEED_PROFILES: tuple[SensorProfile, ...] = (
    SensorProfile("accelerometer",      "m/s^2",      cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    SensorProfile("strain_gauge",       "microstrain",cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    SensorProfile("crack_sensor",       "mm",         cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    SensorProfile("load_cell",          "kN",         cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    SensorProfile("temperature",        "degC",       cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    SensorProfile("tiltmeter",          "degrees",    cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    SensorProfile("displacement_lvdt",  "mm",         cadence_s=TODO, phys_min=TODO, phys_max=TODO),
)

# Canonical registry of seeded sensor-type profiles, keyed by sensor_type.
SENSOR_PROFILES: Final[dict[str, SensorProfile]] = {
    p.sensor_type: p for p in _SEED_PROFILES
}


@dataclass(frozen=True, slots=True)
class UnknownSensorType:
    """Structured result for a sensor_type that is NOT registered at all.

    This is the spec's "unconfigured sensor type" edge case (AC-7): the type was
    never added to SENSOR_PROFILES. It is DELIBERATELY a different shape from a
    registered-but-incomplete profile (a real SensorProfile reporting
    is_fully_configured == False) so downstream can tell the two apart:

      * UnknownSensorType        -> reject + alert "register this sensor type"
      * SensorProfile, not fully -> reject + alert "finish configuring this type"

    Both still drive the reading to CORRUPT (it cannot be range-checked), but they
    need different engineer-facing messages and alerts. Returning one generic
    "not ready" signal for both would conflate a never-registered type with an
    incomplete-but-known one.
    """

    sensor_type: str

    @property
    def reason(self) -> str:
        return (
            f"unconfigured sensor type '{self.sensor_type}': not registered in "
            f"SENSOR_PROFILES — an engineer must add a profile for this type"
        )


def get_profile(sensor_type: str) -> SensorProfile | UnknownSensorType:
    """Look up a sensor-type profile.

    Returns:
      * the SensorProfile if the type is registered (it may itself report
        is_fully_configured == False if bounds/cadence are still TODO — a
        distinct, registered-but-incomplete state); or
      * an UnknownSensorType signal if the type is not registered at all.

    Never raises — an unknown type is an expected input condition (FR-6), not an
    exception, and feeds the CORRUPT path (AC-7).
    """
    profile = SENSOR_PROFILES.get(sensor_type)
    if profile is None:
        return UnknownSensorType(sensor_type)
    return profile
