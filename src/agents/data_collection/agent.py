"""Orchestration (T901) — process_cycle wires Phases 3-8 into one deterministic pass.

One call = one validation cycle over a batch of raw payloads. The pipeline order
(tasks.md T901) is:

  safe-parse (T902)  ->  clock-drift annotate (T905)  ->  dedup first-wins + sort by
  sensor timestamp (T904)  ->  ITERATE THE EXPECTED-SENSOR REGISTRY (T104)  ->  per
  sensor: liveness owns OFFLINE (T301)  ->  range (T401)  ->  spike/PENDING (T502)  ->
  advance any open PENDING (T701)  ->  emit a per-sensor result carrying BOTH status
  axes plus the clock_drift flag.

Key guarantees this layer enforces (its acceptance):
  * ONE result per EXPECTED sensor — including silent ones (iterated from the registry,
    not the batch), so silence surfaces as OFFLINE/NO_DATA, never an absent row.
  * Precedence: a CORRUPT value is CORRUPT, never interpolated or spike-judged; OFFLINE
    (from liveness) co-exists with NO_DATA (reading axis) for a silent sensor.
  * Determinism: the clock is injected (`now`); same inputs -> same output. No LLM, no
    wall-clock, no randomness.

Cross-cycle behaviours (gap interpolation over many cycles, bounded late-arrival
recompute) are delegated to their leaf functions (T601/T801) and exercised across
multiple process_cycle calls in the E2E harness (T1101/T1102). A single cycle resolves
this cycle's readings and advances state.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from agents.data_collection.checks.clock_drift import check_clock_drift
from agents.data_collection.checks.liveness import (
    SensorLivenessState,
    check_liveness,
)
from agents.data_collection.checks.pending import (
    PendingSpike,
    resolve_pending,
)
from agents.data_collection.checks.range_check import check_range
from agents.data_collection.checks.spike import (
    HistoryReading,
    check_spike,
    compute_baseline,
)
from agents.data_collection.config.registry import SensorRegistry
from agents.data_collection.config.sensor_profiles import (
    SensorProfile,
    UnknownSensorType,
    get_profile,
)
from agents.data_collection.dedup import DuplicateConflict, dedup_and_order
from agents.data_collection.parsing import ParseFailure, ParsedReading, safe_parse
from agents.data_collection.statuses import ReadingStatus, SensorHealth


@dataclass(frozen=True, slots=True)
class SensorState:
    """Per-sensor rolling state threaded across cycles.

    last_seen drives liveness; history (OK readings) feeds the spike baseline; pending
    holds an open spike candidate awaiting confirmation.
    """

    sensor_id: str
    last_seen: datetime | None = None
    history: tuple[HistoryReading, ...] = ()
    pending: PendingSpike | None = None


@dataclass(frozen=True, slots=True)
class DecisionEntry:
    """A decision to be logged (mapped to a decision_log row by T903)."""

    sensor_id: str
    decision: str           # LIVENESS | RANGE | SPIKE | PENDING | CLOCK_DRIFT | PARSE ...
    old_status: str | None
    new_status: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class SensorResult:
    """One verdict — both axes + the drift flag. One per READING (a sensor may report
    several in a cycle); a silent sensor produces exactly one with sensor_time=None."""

    sensor_id: str
    sensor_health: SensorHealth | None      # device axis (None = unevaluable config)
    reading_status: ReadingStatus | None    # value axis (None = no reading + no config)
    value: float | None
    clock_drift: bool                        # timing flag, co-exists with any status
    reason: str
    sensor_time: datetime | None = None      # the reading's own timestamp; None if silent


@dataclass(frozen=True, slots=True)
class CycleResult:
    """The full output of one cycle.

    `results` holds the TERMINAL verdict per sensor (one entry — drives sensor_status and
    the existing per-sensor API). `reading_results` holds EVERY reading's verdict in
    chronological order — a sensor that reported N distinct-timestamp readings this cycle
    contributes N entries (drives validated_readings, one row per reading). A silent
    sensor contributes exactly one reading_result (NO_DATA, sensor_time=None).
    """

    results: dict[str, SensorResult]
    reading_results: list[SensorResult] = field(default_factory=list)
    logs: list[DecisionEntry] = field(default_factory=list)
    conflicts: list[DuplicateConflict] = field(default_factory=list)
    parse_failures: list[ParseFailure] = field(default_factory=list)
    next_states: dict[str, SensorState] = field(default_factory=dict)


def process_cycle(
    readings: list[Any],
    registry: SensorRegistry,
    states: dict[str, SensorState],
    now: datetime,
) -> CycleResult:
    """Validate one cycle's batch over the expected-sensor registry. Deterministic.

    Args:
        readings: raw payloads (dicts) in arrival order.
        registry: the expected sensors (T104) — iterated so silent sensors are judged.
        states: per-sensor rolling state, keyed by sensor_id (missing = fresh sensor).
        now: the cycle reference time on the sensor-time axis (injected).

    Returns:
        CycleResult with one SensorResult per expected sensor, decision logs, dropped
        duplicate-conflicts, parse failures, and the advanced next_states.
    """
    logs: list[DecisionEntry] = []
    parse_failures: list[ParseFailure] = []

    # --- Phase A: safe-parse every payload (T902). Bad ones become CORRUPT logs. ---
    parsed: list[ParsedReading] = []
    for payload in readings:
        result = safe_parse(payload)
        if isinstance(result, ParseFailure):
            parse_failures.append(result)
            logs.append(DecisionEntry(
                sensor_id=result.sensor_id or "<unparseable>",
                decision="PARSE",
                old_status=None,
                new_status=ReadingStatus.CORRUPT.value,
                reason=result.reason,
            ))
        else:
            parsed.append(result)

    # --- Phase B: dedup first-wins + order by sensor timestamp (T904). ---
    deduped = dedup_and_order(parsed)
    for conflict in deduped.conflicts:
        logs.append(DecisionEntry(
            sensor_id=conflict.sensor_id,
            decision="DUPLICATE_CONFLICT",
            old_status=None,
            new_status=None,
            reason=(
                f"{conflict.reason} (kept {conflict.kept_value}, "
                f"discarded {conflict.discarded_value})"
            ),
        ))
    # A sensor may report SEVERAL distinct-timestamp readings in one batch (MQTT
    # at-least-once + buffering). Keep ALL of them, grouped and in chronological order —
    # collapsing to one (newest) silently drops readings, their verdicts, and provenance.
    by_sensor: dict[str, list[ParsedReading]] = {}
    for r in deduped.readings:
        by_sensor.setdefault(r.sensor_id, []).append(r)

    # --- Phase C: iterate EXPECTED sensors (registry) — silent ones included. ---
    results: dict[str, SensorResult] = {}
    reading_results: list[SensorResult] = []
    next_states: dict[str, SensorState] = {}

    for expected in registry.all():
        sensor_id = expected.sensor_id
        state = states.get(sensor_id, SensorState(sensor_id=sensor_id))
        profile = get_profile(expected.sensor_type)
        sensor_readings = by_sensor.get(sensor_id, [])

        if not sensor_readings:
            # Silent sensor: exactly one verdict (NO_DATA / OFFLINE), sensor_time=None.
            result, entries, state = _process_one_sensor(
                sensor_id, profile, None, state, now
            )
            results[sensor_id] = result
            reading_results.append(result)
            logs.extend(entries)
        else:
            # Fold over every reading, threading state so each reading sees the prior
            # one's effect (e.g. an open candidate raised by an earlier sample). Each
            # reading gets its OWN validated verdict; the LAST is the terminal one.
            for reading in sensor_readings:
                result, entries, state = _process_one_sensor(
                    sensor_id, profile, reading, state, now
                )
                reading_results.append(result)
                logs.extend(entries)
            results[sensor_id] = result

        next_states[sensor_id] = state

    return CycleResult(
        results=results,
        reading_results=reading_results,
        logs=logs,
        conflicts=list(deduped.conflicts),
        parse_failures=parse_failures,
        next_states=next_states,
    )


def _process_one_sensor(
    sensor_id: str,
    profile: SensorProfile | UnknownSensorType,
    reading: ParsedReading | None,
    state: SensorState,
    now: datetime,
) -> tuple[SensorResult, list[DecisionEntry], SensorState]:
    """Run the per-sensor pipeline. Isolated so one sensor's path never aborts others."""
    logs: list[DecisionEntry] = []

    reading_time = reading.sensor_time if reading is not None else None

    # An unregistered/unprofiled type cannot be validated — CORRUPT, distinct reason.
    if isinstance(profile, UnknownSensorType):
        logs.append(DecisionEntry(sensor_id, "RANGE", None,
                                  ReadingStatus.CORRUPT.value, profile.reason))
        # last_seen still advances so a mid-run profile fix doesn't see it as never-seen.
        new_state = replace(state, last_seen=reading_time or state.last_seen)
        return (
            SensorResult(sensor_id, None, ReadingStatus.CORRUPT,
                         reading.value if reading else None, False, profile.reason,
                         reading_time),
            logs,
            new_state,
        )

    # --- Liveness (owns OFFLINE). Uses this cycle's reading time if present. ---
    last_seen = reading.sensor_time if reading is not None else state.last_seen
    live = check_liveness(SensorLivenessState(sensor_id, last_seen), now, profile)
    if live.health is SensorHealth.OFFLINE:
        logs.append(DecisionEntry(sensor_id, "LIVENESS", None,
                                  live.health.value, live.reason))

    # --- This reading's OWN verdict is computed first and NEVER skipped. ---
    # An open candidate must not exempt the reading from clock-drift, range, or verdict
    # emission. We compute the reading's own status here; candidate resolution (below)
    # is layered on top, never a bypass. `own` = (status, value, reason) or None (silent).
    drift_flag = False
    own: tuple[ReadingStatus, float | None, str] | None = None
    is_clean_value = False  # in-range numeric -> a valid confirmation / spike candidate
    if reading is not None:
        drift = check_clock_drift(reading.sensor_time, reading.ingest_time, profile)
        drift_flag = drift.clock_drift
        if drift.log_required:
            logs.append(DecisionEntry(sensor_id, "CLOCK_DRIFT", None, None, drift.reason))

        if reading.value is None:
            # Explicit null is a legitimate "no reading" -> NO_DATA, not CORRUPT.
            own = (ReadingStatus.NO_DATA, None, f"explicit null reading; {live.reason}")
        else:
            rng = check_range(reading.value, profile)
            if rng.status is ReadingStatus.CORRUPT:
                logs.append(DecisionEntry(sensor_id, "RANGE", None,
                                          ReadingStatus.CORRUPT.value, rng.reason))
                own = (ReadingStatus.CORRUPT, reading.value, rng.reason)
            else:
                is_clean_value = True
                own = (ReadingStatus.OK, reading.value, rng.reason)

    # A CORRUPT/NO_DATA reading must SURFACE its own verdict even while a candidate is
    # open — it is never a valid confirmation and is never masked by the candidate.
    own_overrides = own is not None and own[0] in (
        ReadingStatus.CORRUPT, ReadingStatus.NO_DATA,
    )

    # --- Resolve an OPEN candidate (separate concern; can resolve even on a silent
    #     cycle via OFFLINE/timeout). Only a clean in-range value confirms it. ---
    if state.pending is not None:
        new_subsequent = list(state.pending.subsequent)
        if is_clean_value:
            new_subsequent.append(float(reading.value))
        open_pending = replace(state.pending, subsequent=new_subsequent)
        res = resolve_pending(open_pending, live.health, now, profile)

        if res.resolved:
            logs.append(DecisionEntry(sensor_id, "PENDING",
                                      ReadingStatus.PENDING.value,
                                      res.final_status.value, res.reason))
            new_history = _history_after_resolution(
                state.history, open_pending, res, profile, now
            )
            new_state = replace(state, last_seen=last_seen, history=new_history,
                                pending=None)
            if own_overrides:
                status, value, reason = own
                return (SensorResult(sensor_id, live.health, status, value,
                                     drift_flag, reason, reading_time), logs, new_state)
            return (
                SensorResult(sensor_id, live.health, res.final_status,
                             open_pending.candidate_value, drift_flag, res.reason,
                             reading_time),
                logs, new_state,
            )

        # Still awaiting confirmation. A CORRUPT/NO_DATA reading this cycle still
        # surfaces its own verdict; otherwise re-emit PENDING.
        new_state = replace(state, last_seen=last_seen, pending=open_pending)
        if own_overrides:
            status, value, reason = own
            return (SensorResult(sensor_id, live.health, status, value,
                                 drift_flag, reason, reading_time), logs, new_state)
        return (
            SensorResult(sensor_id, live.health, ReadingStatus.PENDING,
                         open_pending.candidate_value, drift_flag, res.reason,
                         reading_time),
            logs, new_state,
        )

    # --- No open candidate. ---
    if reading is None:
        new_state = replace(state, last_seen=last_seen)
        return (
            SensorResult(sensor_id, live.health, ReadingStatus.NO_DATA, None, False,
                         f"no reading this cycle; {live.reason}", None),
            logs, new_state,
        )

    status, value, reason = own
    if status in (ReadingStatus.CORRUPT, ReadingStatus.NO_DATA):
        # CORRUPT/null do NOT enter the baseline. last_seen still advances.
        new_state = replace(state, last_seen=last_seen)
        return (SensorResult(sensor_id, live.health, status, value, drift_flag, reason,
                             reading_time),
                logs, new_state)

    # --- Clean in-range value: spike-judge it. ---
    baseline = compute_baseline(list(state.history), now, profile)
    spike = check_spike(float(reading.value), baseline, profile)
    if spike.is_candidate:
        logs.append(DecisionEntry(sensor_id, "SPIKE", None,
                                  ReadingStatus.PENDING.value, spike.reason))
        pending = PendingSpike(
            candidate_value=float(reading.value),
            raised_at=reading.sensor_time,
            baseline=baseline,
            subsequent=[],
        )
        new_state = replace(state, last_seen=last_seen, pending=pending)
        return (
            SensorResult(sensor_id, live.health, ReadingStatus.PENDING, reading.value,
                         drift_flag, spike.reason, reading_time),
            logs, new_state,
        )

    # --- Normal OK reading. Append to history for future baselines (G1: OK-only). ---
    hist_entry = HistoryReading(reading.sensor_time, float(reading.value),
                                ReadingStatus.OK, is_interpolated=False)
    new_history = (*state.history, hist_entry)[-profile.baseline_max_n:]
    new_state = replace(state, last_seen=last_seen, history=new_history)
    return (
        SensorResult(sensor_id, live.health, ReadingStatus.OK, reading.value,
                     drift_flag, reason, reading_time),
        logs, new_state,
    )


def _within_band(value: float, baseline, profile: SensorProfile) -> bool:
    """True if a value sits inside the baseline's +/-threshold sigma band.

    Used to decide which resolved-candidate confirmations may seed the OK baseline.
    An unusable baseline cannot judge -> conservatively excluded.
    """
    if not baseline.usable:
        return False
    return abs(value - baseline.mean) / baseline.std <= profile.zscore_threshold


def _history_after_resolution(history, pending, res, profile, now):
    """Baseline history after a PENDING resolution (G1: OK-only, no poisoning).

    OK (sustained) -> the candidate + its confirmations ARE the new normal and seed the
    baseline. SPIKE -> the candidate is excluded (it was the spike), and only the
    confirmations that actually fell back within the baseline band re-enter as OK; an
    elevated, still-out-of-band confirmation (e.g. a real shift cut short by OFFLINE/
    timeout) must NOT be tagged OK and poison the baseline.
    """
    if res.final_status is ReadingStatus.OK:
        cand = HistoryReading(pending.raised_at, pending.candidate_value,
                              ReadingStatus.OK)
        confirms = tuple(HistoryReading(now, v, ReadingStatus.OK)
                         for v in pending.subsequent)
        return (*history, cand, *confirms)[-profile.baseline_max_n:]
    confirms = tuple(
        HistoryReading(now, v, ReadingStatus.OK)
        for v in pending.subsequent
        if _within_band(v, pending.baseline, profile)
    )
    return (*history, *confirms)[-profile.baseline_max_n:]
