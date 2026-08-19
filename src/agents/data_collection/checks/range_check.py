"""Range check (FR-2) — CORRUPT detection against per-type physical bounds.

A reading whose value falls outside its sensor type's physical bounds cannot be real
(a crack sensor reading -5mm, an accelerometer at 10^9 m/s^2) and is marked CORRUPT so
it never flows downstream. The reason always names the offending value, the bound it
violated, and the unit — so a human reading the audit log knows exactly what was wrong.

Inputs that are not judgeable numbers — None, NaN, a non-numeric payload, or a value
whose type was never registered — are also CORRUPT, not crashes (FR-6 / AC-7). This
function is total: every input returns a RangeResult, nothing raises.

No fabricated config: if the profile's physical bounds are still the TODO sentinel,
range CANNOT be judged. Rather than invent a bound (which would silently pass or fail a
safety-critical reading), it returns CORRUPT with config_incomplete=True and a loud
reason — a reviewer sees "bounds unset", not a false verdict.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from agents.data_collection.config.sensor_profiles import (
    SensorProfile,
    UnknownSensorType,
)
from agents.data_collection.statuses import ReadingStatus


@dataclass(frozen=True, slots=True)
class RangeResult:
    """Outcome of a range check.

    status is OK (in range) or CORRUPT (out of range / unjudgeable). config_incomplete
    is True only when bounds were TODO — the reading is CORRUPT but the cause is missing
    config, not a bad sensor; callers/alerts should distinguish the two.
    """

    status: ReadingStatus
    reason: str
    config_incomplete: bool = False


def check_range(
    value: object,
    profile: SensorProfile | UnknownSensorType,
) -> RangeResult:
    """Validate a value against its type's physical bounds.

    Args:
        value: the parsed reading value. Accepts `object` deliberately so malformed
            inputs (None, str, NaN, ...) are handled here, not assumed away.
        profile: the per-type SensorProfile, or the UnknownSensorType signal (T103)
            for a type that was never registered.

    Returns:
        RangeResult — OK or CORRUPT. Never raises.
    """
    # Unregistered type: cannot range-check at all (AC-7). Distinct, loud reason.
    if isinstance(profile, UnknownSensorType):
        return RangeResult(
            status=ReadingStatus.CORRUPT,
            reason=profile.reason,
            config_incomplete=True,
        )

    # Not a judgeable number: None, bool, strings, anything non-numeric -> CORRUPT.
    # (bool is an int subclass but is never a valid sensor value, so reject it too.)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return RangeResult(
            status=ReadingStatus.CORRUPT,
            reason=f"non-numeric value {value!r} cannot be range-checked",
        )
    if math.isnan(value) or math.isinf(value):
        return RangeResult(
            status=ReadingStatus.CORRUPT,
            reason=f"value {value} is not a finite number",
        )

    # Bounds unset (TODO): cannot judge. Do NOT guess a physical limit.
    if profile.bounds_are_todo:
        return RangeResult(
            status=ReadingStatus.CORRUPT,
            reason=(
                f"cannot range-check '{profile.sensor_type}': physical bounds are unset "
                f"(TODO) — a structural engineer must supply phys_min/phys_max"
            ),
            config_incomplete=True,
        )

    numeric = float(value)
    if numeric < profile.phys_min:
        return RangeResult(
            status=ReadingStatus.CORRUPT,
            reason=(
                f"value {numeric} {profile.unit} below physical minimum "
                f"{profile.phys_min} {profile.unit}"
            ),
        )
    if numeric > profile.phys_max:
        return RangeResult(
            status=ReadingStatus.CORRUPT,
            reason=(
                f"value {numeric} {profile.unit} above physical maximum "
                f"{profile.phys_max} {profile.unit}"
            ),
        )

    return RangeResult(
        status=ReadingStatus.OK,
        reason=(
            f"value {numeric} {profile.unit} within bounds "
            f"[{profile.phys_min}, {profile.phys_max}] {profile.unit}"
        ),
    )
