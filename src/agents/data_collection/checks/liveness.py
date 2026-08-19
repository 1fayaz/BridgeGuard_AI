"""Liveness check (FR-1) — the SOLE owner of sensor-status OFFLINE/LIVE (G2).

A sensor is judged by its OWN reported timestamps, never the wall clock (G4): we count
how many full cadence intervals have elapsed since its last reading. At
`offline_after_n` missed reports (=3 by default, per-type, configurable) it flips
OFFLINE. There is no global wall-clock rule — a fast sensor and a slow sensor both flip
at exactly 3 missed, scaled to each one's own cadence.

This is the spec's headline guarantee: a sensor that reports NOTHING is still evaluated
(the orchestrator feeds it via the expected-sensor registry, T104) so silence becomes a
visible OFFLINE, never an absent row. Silence must never be mistaken for safety.

Pure function: the reference time is injected (`now`), so it is deterministic and
testable. It returns a status; it never raises (FR-6).

No fabricated config: if the profile's cadence is still the TODO sentinel, liveness
CANNOT be computed. Rather than invent an interval (which would silently mis-judge a
safety-critical sensor), it returns health=None with config_incomplete=True and a loud
reason. A wrong-but-plausible cadence fails silently; an unevaluable one fails loudly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import SensorHealth


@dataclass(frozen=True, slots=True)
class SensorLivenessState:
    """The minimal state liveness needs: when this sensor was last heard from.

    `last_seen` is the sensor's OWN timestamp (G4) of its most recent reading, or None
    if it has never reported in this run.
    """

    sensor_id: str
    last_seen: datetime | None


@dataclass(frozen=True, slots=True)
class LivenessResult:
    """Outcome of a liveness evaluation.

    `health` is None ONLY when the check could not be computed (cadence is TODO);
    callers must treat None as "unevaluable, needs config", never as LIVE.
    """

    sensor_id: str
    health: SensorHealth | None
    missed_count: int
    last_seen: datetime | None
    reason: str
    config_incomplete: bool = False


def check_liveness(
    state: SensorLivenessState,
    now: datetime,
    profile: SensorProfile,
) -> LivenessResult:
    """Evaluate one sensor's device health from its own report timing.

    Args:
        state: the sensor's last-seen sensor-timestamp (or None if never seen).
        now:   the cycle's reference time on the sensor-time axis (injected — pure).
        profile: the per-type profile supplying cadence_s and offline_after_n.

    Returns:
        A LivenessResult. health is OFFLINE/LIVE when evaluable, or None (with
        config_incomplete=True) when the cadence is still the TODO sentinel.
    """
    # Cannot judge liveness without a configured cadence. Do NOT guess one.
    if profile.cadence_is_todo:
        return LivenessResult(
            sensor_id=state.sensor_id,
            health=None,
            missed_count=0,
            last_seen=state.last_seen,
            reason=(
                f"cannot evaluate liveness for '{profile.sensor_type}': cadence_s is "
                f"unset (TODO) — a structural engineer must supply the reporting interval"
            ),
            config_incomplete=True,
        )

    # Never reported: silence is not safety. A registry sensor that has sent nothing
    # is OFFLINE, not absent (FR-1/AC-1, B1).
    if state.last_seen is None:
        return LivenessResult(
            sensor_id=state.sensor_id,
            health=SensorHealth.OFFLINE,
            missed_count=profile.offline_after_n,
            last_seen=None,
            reason="no reading ever received — sensor is silent (OFFLINE)",
        )

    # Count full cadence intervals elapsed since the last reading, by the sensor's own
    # clock. Negative elapsed (a reading at/after `now`) clamps to 0 missed — it just
    # reported. 3 full intervals with no new reading -> 3 missed -> OFFLINE.
    elapsed_s = (now - state.last_seen).total_seconds()
    if elapsed_s < 0:
        elapsed_s = 0.0
    missed = int(elapsed_s // profile.cadence_s)

    if missed >= profile.offline_after_n:
        return LivenessResult(
            sensor_id=state.sensor_id,
            health=SensorHealth.OFFLINE,
            missed_count=missed,
            last_seen=state.last_seen,
            reason=(
                f"{missed} consecutive missed reports "
                f"(>= {profile.offline_after_n} threshold) at {profile.cadence_s}s "
                f"cadence — sensor OFFLINE"
            ),
        )

    return LivenessResult(
        sensor_id=state.sensor_id,
        health=SensorHealth.LIVE,
        missed_count=missed,
        last_seen=state.last_seen,
        reason=(
            f"{missed} missed report(s), below {profile.offline_after_n} threshold — LIVE"
        ),
    )
