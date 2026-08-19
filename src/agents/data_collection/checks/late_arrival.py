"""Late-arrival handling (FR-5 / decision: bounded recompute) — correction by append.

A reading can arrive after the cycle it belongs to has already been processed (network
delay, buffered device, clock skew). It is placed by its OWN sensor timestamp (G4), not
by when we received it. Two outcomes, bounded so we never rewrite ancient history:

  * WITHIN the recompute window (sensor timestamp within `pending_timeout_mult` x cadence
    = 3x cadence of `now`): the late reading may change a verdict we already emitted, so
    we RECOMPUTE the affected slot, write a NEW validated row with the corrected verdict,
    point the prior row at it via superseded_by, and log a CORRECTION
    (`old_status -> new_status`, reason "late-arrival recompute").
  * OUTSIDE the window (older than 3x cadence): too late to safely recompute downstream
    results. Keep it as raw only (it is already appended on receipt) and log "outside
    recompute window". No validated row is changed.

Correction is by APPEND, never overwrite (Operational Constraint / Const. II):
  - The prior validated row is NOT mutated except to set superseded_by (a link, T202
    permits exactly that). Its value/status are preserved as history.
  - Raw data is NEVER touched here — this function does not even take the raw store. Raw
    is append-only (T201); a late reading was appended on receipt and stays put. The raw
    row count can only ever grow.

This function is PURE: it takes the already-processed window and returns a CorrectionPlan
describing what to write/log. The actual persistence (insert new row, stamp
superseded_by, append the log) is performed by the store in T903. Keeping it pure makes
the raw-never-overwritten guarantee structural: there is no raw handle to misuse.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus


@dataclass(frozen=True, slots=True)
class ProcessedReading:
    """A verdict already emitted for one slot (a prior validated_readings row).

    `row_id` is the prior row's identity (so superseded_by can point at it). For the
    in-memory/pure layer this may be a surrogate; T903 maps it to the DB id.
    """

    row_id: int
    sensor_id: str
    sensor_time: datetime
    value: float | None
    status: ReadingStatus


@dataclass(frozen=True, slots=True)
class LateReading:
    """A reading that arrived after its cycle was processed."""

    sensor_id: str
    sensor_time: datetime        # the sensor's OWN timestamp (G4) — places the reading
    value: float | None


@dataclass(frozen=True, slots=True)
class CorrectionRow:
    """A NEW validated row to insert, replacing a prior verdict (never an in-place edit)."""

    sensor_id: str
    sensor_time: datetime
    value: float | None
    status: ReadingStatus
    supersedes_row_id: int       # prior row whose superseded_by must point here
    reason: str


@dataclass(frozen=True, slots=True)
class CorrectionLog:
    """A CORRECTION (or 'outside window') decision_log entry to append."""

    sensor_id: str
    sensor_time: datetime
    old_status: ReadingStatus | None
    new_status: ReadingStatus | None
    reason: str


@dataclass(frozen=True, slots=True)
class CorrectionPlan:
    """What the store should do for a late arrival. Empty new_rows = no verdict change.

    within_window distinguishes the two outcomes; recomputed says whether a verdict
    actually changed (a late reading inside the window that matches the prior verdict
    needs a log entry but no new row).
    """

    within_window: bool
    recomputed: bool
    new_rows: list[CorrectionRow] = field(default_factory=list)
    logs: list[CorrectionLog] = field(default_factory=list)


def handle_late_arrival(
    reading: LateReading,
    processed_window: list[ProcessedReading],
    now: datetime,
    profile: SensorProfile,
    recompute_status: ReadingStatus,
) -> CorrectionPlan:
    """Decide how a late reading affects already-processed results (bounded recompute).

    Args:
        reading: the late reading, placed by its own sensor timestamp (G4).
        processed_window: prior verdicts for this sensor (the slots already emitted).
        now: reference time on the sensor-time axis (injected — pure).
        profile: supplies the recompute window (pending_timeout_s = 3x cadence).
        recompute_status: the verdict the validation pipeline produces for this reading
            now that it has arrived (computed by the caller/orchestrator, T901). Passed
            in so this function stays a pure placement/correction decider.

    Returns:
        CorrectionPlan. Raw is never referenced, so raw rows can only grow elsewhere.
    """
    age_s = (now - reading.sensor_time).total_seconds()
    window_s = profile.pending_timeout_s  # 3x cadence (G3/late-arrival share the bound)

    # Outside the bounded lookback: too old to recompute downstream. Raw-only.
    if age_s > window_s:
        return CorrectionPlan(
            within_window=False,
            recomputed=False,
            new_rows=[],
            logs=[CorrectionLog(
                sensor_id=reading.sensor_id,
                sensor_time=reading.sensor_time,
                old_status=None,
                new_status=None,
                reason=(
                    f"outside recompute window: late reading {age_s:.1f}s old exceeds "
                    f"{window_s:.1f}s (3x cadence) - kept raw-only, no recompute"
                ),
            )],
        )

    # Within the window. Find the prior verdict for this exact slot, if any.
    prior = next(
        (p for p in processed_window
         if p.sensor_id == reading.sensor_id and p.sensor_time == reading.sensor_time),
        None,
    )

    # No prior verdict for this slot (e.g. it was a NO_DATA gap we can now fill): the
    # late reading creates a fresh verdict. Still a correction event, logged old=None.
    if prior is None:
        return CorrectionPlan(
            within_window=True,
            recomputed=True,
            new_rows=[CorrectionRow(
                sensor_id=reading.sensor_id,
                sensor_time=reading.sensor_time,
                value=reading.value,
                status=recompute_status,
                supersedes_row_id=-1,  # nothing to supersede; new slot verdict
                reason="late-arrival recompute",
            )],
            logs=[CorrectionLog(
                sensor_id=reading.sensor_id,
                sensor_time=reading.sensor_time,
                old_status=None,
                new_status=recompute_status,
                reason="late-arrival recompute",
            )],
        )

    # A prior verdict exists. If the recomputed status matches it, nothing changed —
    # log the event but write no new row (no churn, no spurious supersede).
    if prior.status is recompute_status and prior.value == reading.value:
        return CorrectionPlan(
            within_window=True,
            recomputed=False,
            new_rows=[],
            logs=[CorrectionLog(
                sensor_id=reading.sensor_id,
                sensor_time=reading.sensor_time,
                old_status=prior.status,
                new_status=recompute_status,
                reason="late-arrival recompute: verdict unchanged",
            )],
        )

    # Verdict changed: append a NEW row, supersede the old one, log old -> new.
    return CorrectionPlan(
        within_window=True,
        recomputed=True,
        new_rows=[CorrectionRow(
            sensor_id=reading.sensor_id,
            sensor_time=reading.sensor_time,
            value=reading.value,
            status=recompute_status,
            supersedes_row_id=prior.row_id,
            reason="late-arrival recompute",
        )],
        logs=[CorrectionLog(
            sensor_id=reading.sensor_id,
            sensor_time=reading.sensor_time,
            old_status=prior.status,
            new_status=recompute_status,
            reason="late-arrival recompute",
        )],
    )
