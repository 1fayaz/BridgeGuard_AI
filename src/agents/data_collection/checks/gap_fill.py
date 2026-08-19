"""Gap-fill / interpolation (FR-4) — fills small gaps, flags large ones.

A sensor's timeline has one expected slot per cadence interval. When a slot has no
reading it is a gap. Short gaps are recoverable, long gaps are not:

  * 1-2 consecutive missing slots -> linear interpolation between the bracketing
    present values, each filled slot marked INTERPOLATED (is_interpolated=True).
  * 3+ consecutive missing slots   -> NO_DATA (value stays null); the gap is too large
    to fill honestly (interp_cap = 2).

A gap that is not bracketed by a present value on BOTH sides (a gap at the very start
or end of the timeline) cannot be linearly interpolated — there is nothing to
interpolate between, and extrapolating a safety-critical value would be a fabrication.
Such gaps are NO_DATA regardless of length.

G2 — single owner of OFFLINE: gap-fill sets ONLY the reading-status (INTERPOLATED /
NO_DATA). It NEVER sets or returns a sensor-status. A long gap and an OFFLINE device
often coincide (same 3-missed condition), but OFFLINE is written solely by the liveness
check (T301). This module deliberately has no access to sensor-status to make that
impossible to violate.

Pure function: same timeline in -> same filled timeline out. Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus


@dataclass(frozen=True, slots=True)
class TimelineSlot:
    """One expected cadence slot. value is None when no reading arrived for it."""

    sensor_time: datetime
    value: float | None


@dataclass(frozen=True, slots=True)
class FilledSlot:
    """A slot after gap-fill.

    status is one of OK (a real reading was present), INTERPOLATED (filled), or NO_DATA
    (gap too large / unbracketed). There is intentionally NO sensor-status field here
    (G2). is_interpolated mirrors status == INTERPOLATED for convenient display.
    """

    sensor_time: datetime
    value: float | None
    status: ReadingStatus
    is_interpolated: bool
    reason: str


def _present(slot: TimelineSlot) -> bool:
    return slot.value is not None


def fill_gaps(
    timeline: list[TimelineSlot],
    profile: SensorProfile,
) -> list[FilledSlot]:
    """Fill short gaps, flag long ones — reading-status only (G2).

    Args:
        timeline: expected slots for ONE sensor, ordered oldest -> newest. Present
            slots carry a value; gaps have value=None.
        profile: supplies interp_cap (2).

    Returns:
        A FilledSlot per input slot. Present -> OK; short bracketed gap -> INTERPOLATED;
        long or unbracketed gap -> NO_DATA. No sensor-status is ever produced.
    """
    n = len(timeline)
    out: list[FilledSlot] = []
    i = 0
    while i < n:
        slot = timeline[i]
        if _present(slot):
            out.append(FilledSlot(
                sensor_time=slot.sensor_time,
                value=slot.value,
                status=ReadingStatus.OK,
                is_interpolated=False,
                reason="reading present",
            ))
            i += 1
            continue

        # Start of a gap run: find its extent [i, j).
        j = i
        while j < n and not _present(timeline[j]):
            j += 1
        gap_len = j - i

        left_present = i - 1 >= 0 and _present(timeline[i - 1])
        right_present = j < n and _present(timeline[j])
        bracketed = left_present and right_present

        if bracketed and gap_len <= profile.interp_cap:
            left_val = timeline[i - 1].value
            right_val = timeline[j].value
            assert left_val is not None and right_val is not None  # bracketed
            # Linear interpolation across gap_len interior points: step = (R-L)/(gap+1).
            step = (right_val - left_val) / (gap_len + 1)
            for k in range(gap_len):
                interp = left_val + step * (k + 1)
                out.append(FilledSlot(
                    sensor_time=timeline[i + k].sensor_time,
                    value=interp,
                    status=ReadingStatus.INTERPOLATED,
                    is_interpolated=True,
                    reason=(
                        f"linear interpolation of {gap_len}-slot gap between "
                        f"{left_val} and {right_val}"
                    ),
                ))
        else:
            if not bracketed:
                why = "gap not bracketed by readings on both sides (cannot interpolate)"
            else:
                why = (
                    f"gap of {gap_len} slots exceeds interpolation cap "
                    f"{profile.interp_cap} — too large to fill"
                )
            for k in range(gap_len):
                out.append(FilledSlot(
                    sensor_time=timeline[i + k].sensor_time,
                    value=None,
                    status=ReadingStatus.NO_DATA,
                    is_interpolated=False,
                    reason=why,
                ))

        i = j

    return out
