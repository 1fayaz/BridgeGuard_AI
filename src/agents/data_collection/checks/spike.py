"""Spike / outlier detection (FR-3) — SPIKE vs real-signal.

A reading far from the sensor's recent normal (> +/-zscore_threshold sigma) is a spike
CANDIDATE — but a single outlier is not yet a verdict: it could be a transient glitch
OR the leading edge of a real structural change. So a candidate is written PENDING and
confirmed/denied by the next `confirm_count` readings (T502-T504). This module supplies
the statistical baseline that judgement rests on.

T501 here = compute_baseline. The baseline must reflect only TRUSTWORTHY normal:

  * G1 — built from OK readings ONLY. SPIKE, CORRUPT, PENDING, NO_DATA and interpolated
    values are excluded; folding a spike or a filled gap into the baseline would poison
    the mean/sigma and mask the next real anomaly.
  * G5 — the window is the INTERSECTION of two caps: the most recent
    `baseline_max_n` (100) readings AND only those within `baseline_max_age_h` (24h).
    Whichever yields fewer samples wins — recent enough AND not too many.

Edge cases never divide by zero: < 2 qualifying samples, or zero variance, returns an
`insufficient`/degenerate baseline signal (BaselineResult.usable is False), and the
caller treats the reading as NORMAL because it cannot be judged (T502).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus


class SpikeOutcome(str, Enum):
    """Outcome of the single-reading spike test (T502).

    Intentionally NOT a ReadingStatus: PENDING here means "candidate awaiting the
    confirm_count window" and NORMAL means "let it flow on as OK". The final SPIKE-vs-OK
    verdict is decided later by resolve_pending (T701) once the window fills.
    """

    NORMAL = "NORMAL"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class HistoryReading:
    """A past reading as the baseline sees it.

    Only the fields the baseline filter needs. `status` and `is_interpolated` drive the
    G1 OK-only filter; `sensor_time` drives the 24h cap (G4 — sensor's own clock).
    """

    sensor_time: datetime
    value: float
    status: ReadingStatus
    is_interpolated: bool = False

    @property
    def is_trustworthy(self) -> bool:
        """G1: only a genuine OK, non-interpolated reading may seed the baseline."""
        return self.status is ReadingStatus.OK and not self.is_interpolated


@dataclass(frozen=True, slots=True)
class BaselineResult:
    """The computed baseline, or a signal that it cannot be computed.

    usable is False when there are < 2 qualifying samples or variance is zero — in
    that case mean/std are still reported (for forensics) but must NOT be used to judge
    a spike. reason explains why, for the audit log.
    """

    mean: float
    std: float
    n: int
    usable: bool
    reason: str


def compute_baseline(
    history: list[HistoryReading],
    now: datetime,
    profile: SensorProfile,
) -> BaselineResult:
    """Compute mean/sigma over the trustworthy recent window (G1 + G5).

    Args:
        history: past readings for ONE sensor, any order. Filtered + windowed here.
        now: reference time on the sensor-time axis (injected — pure).
        profile: supplies baseline_max_n (100) and baseline_max_age_h (24h).

    Returns:
        BaselineResult. usable=False (with mean/std=nan) when the window cannot yield a
        sound baseline; never raises, never divides by zero.
    """
    # G1: trustworthy (OK, non-interpolated) readings only.
    trustworthy = [r for r in history if r.is_trustworthy]

    # G5 cap (a): within the age window, by the sensor's own timestamp.
    cutoff = now - timedelta(hours=profile.baseline_max_age_h)
    within_age = [r for r in trustworthy if r.sensor_time >= cutoff]

    # G5 cap (b): the most recent baseline_max_n of those. Intersection = apply (a)
    # then keep the newest N — whichever cap bites harder determines the sample count.
    within_age.sort(key=lambda r: r.sensor_time)          # oldest -> newest
    window = within_age[-profile.baseline_max_n:]          # newest <=N

    n = len(window)
    if n < 2:
        return BaselineResult(
            mean=math.nan, std=math.nan, n=n, usable=False,
            reason=(
                f"insufficient baseline: {n} trustworthy sample(s) in the last "
                f"{profile.baseline_max_age_h}h (need >= 2) — cannot judge spikes"
            ),
        )

    values = [r.value for r in window]
    mean = sum(values) / n
    # Sample variance (n-1): we are estimating the spread of a process from a sample.
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std = math.sqrt(variance)

    if std == 0.0:
        return BaselineResult(
            mean=mean, std=0.0, n=n, usable=False,
            reason=(
                f"zero-variance baseline over {n} samples (all identical) — any "
                f"deviation would be infinite sigma; treat reading as unjudgeable"
            ),
        )

    return BaselineResult(
        mean=mean, std=std, n=n, usable=True,
        reason=f"baseline over {n} trustworthy samples within {profile.baseline_max_age_h}h",
    )


@dataclass(frozen=True, slots=True)
class SpikeResult:
    """Verdict of the single-reading spike test (T502).

    is_candidate=True means the value is > +/-threshold sigma from the baseline and
    must be written PENDING (status here is PENDING) until the next confirm_count
    readings confirm or deny it (T503/T504). Otherwise status is NORMAL.

    NORMAL is also returned when the baseline is unusable — we CANNOT call something a
    spike if we have no sound normal to compare against (that would manufacture false
    spikes from thin history). z is the computed z-score, or nan when unjudgeable.
    """

    status: SpikeOutcome
    z: float
    is_candidate: bool
    reason: str


def check_spike(
    value: float,
    baseline: BaselineResult,
    profile: SensorProfile,
) -> SpikeResult:
    """Judge one value against a precomputed baseline (T501).

    Args:
        value: the reading's numeric value (already range-validated upstream).
        baseline: the BaselineResult from compute_baseline.
        profile: supplies zscore_threshold (default 3.0).

    Returns:
        SpikeResult. A > +/-threshold sigma value -> PENDING candidate; otherwise
        NORMAL. An unusable baseline -> NORMAL (cannot judge). Never raises.
    """
    if not baseline.usable:
        return SpikeResult(
            status=SpikeOutcome.NORMAL,
            z=math.nan,
            is_candidate=False,
            reason=f"baseline unusable, cannot judge spike: {baseline.reason}",
        )

    z = (value - baseline.mean) / baseline.std
    if abs(z) > profile.zscore_threshold:
        return SpikeResult(
            status=SpikeOutcome.PENDING,
            z=z,
            is_candidate=True,
            reason=(
                f"value {value} is {z:.2f} sigma from baseline mean "
                f"{baseline.mean:.4g} (> +/-{profile.zscore_threshold}) — spike "
                f"candidate, written PENDING for confirmation"
            ),
        )

    return SpikeResult(
        status=SpikeOutcome.NORMAL,
        z=z,
        is_candidate=False,
        reason=(
            f"value {value} is {z:.2f} sigma from baseline mean "
            f"{baseline.mean:.4g} (within +/-{profile.zscore_threshold}) — normal"
        ),
    )


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """Outcome of confirming a spike candidate against the next readings (T503/T504).

    final_status is the TERMINAL reading-status for the candidate:
      * OK    — the shift was SUSTAINED by all confirm_count readings: a real signal,
                released downstream (NOT suppressed).
      * SPIKE — the value returned toward baseline within the window: a transient
                glitch, finalised SPIKE and withheld from downstream.
    confirmed mirrors this (True = real shift). reason explains the decision.
    """

    final_status: ReadingStatus
    confirmed: bool
    reason: str


def confirm_spike(
    candidate_value: float,
    subsequent: list[float],
    baseline: BaselineResult,
    profile: SensorProfile,
) -> ConfirmationResult:
    """Confirm or deny a spike candidate using the next readings (FR-3, count=3).

    A candidate is a REAL signal only if the shift PERSISTS: every one of the next
    `confirm_count` readings must stay beyond +/-threshold sigma in the SAME direction
    as the candidate. If any of them returns toward the normal band, the candidate was
    a transient -> finalised SPIKE and withheld.

    Args:
        candidate_value: the spike candidate's value (sets the expected direction).
        subsequent: the readings that arrived after the candidate, in order. Only the
            first `confirm_count` are considered; fewer than that is not yet decidable
            (the caller keeps it PENDING — resolution paths b/c live in T701).
        baseline: the baseline the candidate was judged against.
        profile: supplies confirm_count (3) and zscore_threshold (3.0).

    Returns:
        ConfirmationResult with a terminal OK or SPIKE. Caller must only invoke this
        once enough readings exist; never raises.
    """
    need = profile.confirm_count
    window = subsequent[:need]

    # Direction of the candidate: +1 if above the mean, -1 if below.
    direction = 1 if candidate_value >= baseline.mean else -1

    def sustains(v: float) -> bool:
        z = (v - baseline.mean) / baseline.std
        # Same side AND still beyond the threshold.
        return (z * direction) > profile.zscore_threshold

    sustained = [sustains(v) for v in window]
    if len(window) >= need and all(sustained):
        return ConfirmationResult(
            final_status=ReadingStatus.OK,
            confirmed=True,
            reason=(
                f"shift sustained across {need} readings beyond "
                f"+/-{profile.zscore_threshold} sigma — real signal, released as OK"
            ),
        )

    return ConfirmationResult(
        final_status=ReadingStatus.SPIKE,
        confirmed=False,
        reason=(
            f"candidate not sustained ({sum(sustained)}/{need} readings stayed beyond "
            f"+/-{profile.zscore_threshold} sigma) — transient SPIKE, withheld"
        ),
    )
