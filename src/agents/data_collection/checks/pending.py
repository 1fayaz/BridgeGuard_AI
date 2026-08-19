"""PENDING resolution (FR-5) — a spike candidate is never left hanging.

When check_spike (T502) raises a candidate it is written PENDING: we do not yet know
if it was a transient glitch (-> SPIKE) or the start of a real shift (-> OK). This
module decides, resolving on the FIRST of three triggers, in this priority order:

  (a) confirmation window filled — the next `confirm_count` (3) readings have arrived,
      so we can make a REAL judgement (confirm_spike, T503/T504): sustained -> OK,
      not sustained -> SPIKE. This is the preferred, evidence-based outcome.
  (b) sensor went OFFLINE — the device stopped reporting before the window filled, so
      confirmation is impossible. Fail safe: SPIKE (unconfirmed). We do NOT release an
      unconfirmed candidate as OK — a safety-critical value must earn its OK.
  (c) timeout — elapsed time is STRICTLY GREATER THAN the PENDING timeout
      (pending_timeout_s = 3x cadence). Confirmation did not complete in time:
      SPIKE (unconfirmed).

G3 — no exact-tie race. (a) is checked before (c), AND (c) requires strict `>`. So an
on-time 3rd confirming reading arriving at ~3x cadence (i.e. AT the timeout boundary)
always resolves via (a): the window is full, and the timeout has not yet *exceeded*
(only reached) its limit. The buffer between "reached" and "exceeded" is what makes the
tie unreachable. A candidate is therefore never simultaneously eligible for (a) and (c).

Pure function: clock injected; same inputs -> same resolution. Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from agents.data_collection.checks.spike import BaselineResult, confirm_spike
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus, SensorHealth


class ResolutionTrigger(str, Enum):
    """Which of the three conditions resolved the PENDING (None while still pending)."""

    CONFIRMATION = "CONFIRMATION"   # (a) window filled
    OFFLINE = "OFFLINE"             # (b) sensor went offline
    TIMEOUT = "TIMEOUT"             # (c) elapsed > 3x cadence


@dataclass(frozen=True, slots=True)
class PendingSpike:
    """A spike candidate awaiting confirmation.

    `subsequent` are the values that have arrived AFTER the candidate so far, in order.
    The window is full when len(subsequent) >= confirm_count.
    """

    candidate_value: float
    raised_at: datetime          # sensor timestamp of the candidate (G4)
    baseline: BaselineResult     # the baseline the candidate was judged against
    subsequent: list[float]


@dataclass(frozen=True, slots=True)
class PendingResolution:
    """Outcome of a resolution attempt.

    resolved=False means none of the triggers fired yet (still PENDING) — final_status
    is None. When resolved, final_status is the terminal OK or SPIKE.
    """

    resolved: bool
    final_status: ReadingStatus | None
    trigger: ResolutionTrigger | None
    confirmed: bool
    reason: str


_STILL_PENDING = "no trigger fired: window not full, sensor live, within timeout"


def resolve_pending(
    pending: PendingSpike,
    sensor_health: SensorHealth | None,
    now: datetime,
    profile: SensorProfile,
) -> PendingResolution:
    """Attempt to resolve a PENDING spike candidate (FR-5).

    Args:
        pending: the candidate + the readings seen since it was raised.
        sensor_health: the sensor's current device status from liveness (T301). None
            is treated as not-offline (unevaluable liveness must not force a SPIKE).
        now: reference time on the sensor-time axis (injected — pure).
        profile: supplies confirm_count and pending_timeout_s (= 3x cadence).

    Returns:
        PendingResolution. resolved=False (final_status=None) if still pending.
    """
    # (a) Confirmation window filled — preferred, evidence-based. Checked FIRST so a
    #     complete window always beats the timeout (G3).
    if len(pending.subsequent) >= profile.confirm_count:
        conf = confirm_spike(
            pending.candidate_value, pending.subsequent, pending.baseline, profile
        )
        return PendingResolution(
            resolved=True,
            final_status=conf.final_status,
            trigger=ResolutionTrigger.CONFIRMATION,
            confirmed=conf.confirmed,
            reason=f"resolved by confirmation window: {conf.reason}",
        )

    # (b) Sensor offline — confirmation impossible; fail safe to SPIKE (unconfirmed).
    if sensor_health is SensorHealth.OFFLINE:
        return PendingResolution(
            resolved=True,
            final_status=ReadingStatus.SPIKE,
            trigger=ResolutionTrigger.OFFLINE,
            confirmed=False,
            reason=(
                "sensor went OFFLINE before confirmation window filled — "
                "finalised SPIKE (unconfirmed)"
            ),
        )

    # (c) Timeout — STRICTLY greater than the 3x-cadence limit (G3 buffer). Cannot fire
    #     at the exact boundary, so an on-time 3rd reading (path a) always wins.
    elapsed_s = (now - pending.raised_at).total_seconds()
    if elapsed_s > profile.pending_timeout_s:
        return PendingResolution(
            resolved=True,
            final_status=ReadingStatus.SPIKE,
            trigger=ResolutionTrigger.TIMEOUT,
            confirmed=False,
            reason=(
                f"elapsed {elapsed_s:.1f}s exceeded PENDING timeout "
                f"{profile.pending_timeout_s:.1f}s (3x cadence) with "
                f"{len(pending.subsequent)}/{profile.confirm_count} confirming "
                f"readings — finalised SPIKE (unconfirmed)"
            ),
        )

    return PendingResolution(
        resolved=False,
        final_status=None,
        trigger=None,
        confirmed=False,
        reason=_STILL_PENDING,
    )
