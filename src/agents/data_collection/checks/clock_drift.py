"""Clock-drift detection (FR-7 / decision G4) — a TIMING flag, never a value verdict.

Each reading carries two timestamps: the sensor's own `sensor_time` and our
`ingest_time`. If they diverge by more than the per-type tolerance, the sensor's clock
is suspect. This is recorded as a CO-EXISTING flag, NOT a reading-status:

  * The reading is STILL PROCESSED using its sensor timestamp (G4) — drift changes our
    trust in the *timing*, not the *value*. An in-range reading with clock drift is
    still OK, just additionally flagged clock_drift=True.
  * A CLOCK_DRIFT decision is logged with the measured gap and the tolerance, so the
    drift is auditable and the tolerance is tunable.

This is exactly why clock_drift is a boolean on the result and a flag column in
validated_readings (T202), never a seventh reading-status: a terminal status would
*replace* OK and suppress a value we explicitly still want to keep.

No fabricated config: if the tolerance is the TODO sentinel, drift CANNOT be judged.
Rather than invent a threshold, return evaluated=False with a loud reason — the flag is
left False (we cannot assert drift) but the reason makes the missing config visible.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.data_collection.config.sensor_profiles import SensorProfile


@dataclass(frozen=True, slots=True)
class ClockDriftResult:
    """Outcome of the drift check.

    clock_drift is the co-existing flag set on the reading. gap_s is the measured
    |sensor_time - ingest_time|. evaluated is False when the tolerance is TODO or a
    timestamp is missing — in that case clock_drift stays False (we cannot assert it).
    log_required signals the orchestrator to write a CLOCK_DRIFT decision_log entry.
    """

    clock_drift: bool
    gap_s: float | None
    evaluated: bool
    log_required: bool
    reason: str


def check_clock_drift(
    sensor_time: datetime,
    ingest_time: datetime | None,
    profile: SensorProfile,
) -> ClockDriftResult:
    """Flag a reading whose sensor/ingest timestamps diverge beyond tolerance (G4).

    Args:
        sensor_time: the sensor's own timestamp (also what drives processing).
        ingest_time: when we received the payload. None -> cannot evaluate drift.
        profile: supplies clock_drift_tolerance_s (per-type, may be TODO).

    Returns:
        ClockDriftResult. Never raises. The reading-status is unaffected by this check;
        only the clock_drift flag (and an audit log) come from here.
    """
    # Tolerance unset: do NOT guess a threshold for a safety-critical timing check.
    if profile.drift_tolerance_is_todo:
        return ClockDriftResult(
            clock_drift=False,
            gap_s=None,
            evaluated=False,
            log_required=False,
            reason=(
                f"cannot evaluate clock drift for '{profile.sensor_type}': "
                f"clock_drift_tolerance_s is unset (TODO)"
            ),
        )

    # No ingest time: nothing to compare against. Cannot assert drift.
    if ingest_time is None:
        return ClockDriftResult(
            clock_drift=False,
            gap_s=None,
            evaluated=False,
            log_required=False,
            reason="no ingest_time available — clock drift not evaluated",
        )

    gap_s = abs((ingest_time - sensor_time).total_seconds())
    tolerance = profile.clock_drift_tolerance_s

    if gap_s > tolerance:
        return ClockDriftResult(
            clock_drift=True,
            gap_s=gap_s,
            evaluated=True,
            log_required=True,
            reason=(
                f"clock drift {gap_s:.1f}s exceeds tolerance {tolerance:.1f}s — flagged "
                f"clock_drift; reading still processed using its sensor timestamp"
            ),
        )

    return ClockDriftResult(
        clock_drift=False,
        gap_s=gap_s,
        evaluated=True,
        log_required=False,
        reason=f"clock drift {gap_s:.1f}s within tolerance {tolerance:.1f}s",
    )
