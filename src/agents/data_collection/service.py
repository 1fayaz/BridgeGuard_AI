"""Service invocation entrypoint (T1001) — the single callable n8n hits per cycle.

n8n (T1002) batches MQTT messages for one processing cycle and calls run_cycle() with
that batch. This function owns the full boundary sequence:

  1. append every payload to raw_readings ON RECEIPT (before validation) so even a
     payload we later reject is immutably recorded with its raw source id (Const. II);
  2. run the deterministic validation pipeline (process_cycle, T901);
  3. persist the verdicts + decision log (persist_cycle, T903);
  4. return a structured per-cycle SUMMARY (per-sensor statuses + counts).

FR-6 / never-crash: a malformed BATCH (not a list, or None) returns a structured error
result, never a stack trace. Malformed individual readings are already handled per-item
by safe_parse (T902); this guards the batch envelope itself.

Determinism: `now` is injected. Production passes the wall-clock at the boundary here
(the one place a clock enters), keeping every function below it pure and replayable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agents.data_collection.agent import SensorState, process_cycle
from agents.data_collection.parsing import ParsedReading, safe_parse
from agents.data_collection.statuses import ReadingStatus, SensorHealth
from agents.data_collection.store import FakeStore, persist_cycle


@dataclass(frozen=True, slots=True)
class SensorSummary:
    sensor_id: str
    sensor_health: str | None      # device axis as a string for JSON transport
    reading_status: str | None     # value axis
    value: float | None
    clock_drift: bool


@dataclass(frozen=True, slots=True)
class CycleSummary:
    """The structured result n8n receives. ok=False with `error` set on a bad batch."""

    ok: bool
    sensors: list[SensorSummary] = field(default_factory=list)
    raw_appended: int = 0
    validated_written: int = 0
    decisions_logged: int = 0
    conflicts: int = 0
    parse_failures: int = 0
    error: str | None = None


def run_cycle(
    batch: Any,
    store: FakeStore,
    registry,
    states: dict[str, SensorState],
    now: datetime,
) -> CycleSummary:
    """Process one cycle's batch end-to-end. NEVER raises; returns a CycleSummary.

    Args:
        batch: the per-cycle list of raw payloads (dicts) from n8n/MQTT.
        store: the persistence boundary (FakeStore now; SupabaseStore later).
        registry: the expected-sensor registry (T104).
        states: per-sensor rolling state, keyed by sensor_id.
        now: cycle reference time on the sensor-time axis (injected at the boundary).

    Returns:
        CycleSummary. ok=False + error on a malformed batch envelope.
    """
    # Guard the batch ENVELOPE (FR-6). Individual bad readings are safe_parse's job.
    if batch is None or not isinstance(batch, (list, tuple)):
        return CycleSummary(
            ok=False,
            error=f"malformed batch: expected a list of readings, got {type(batch).__name__}",
        )

    try:
        # 1. Append raw on receipt; remember raw ids per sensor for provenance.
        raw_ids: dict[str, list[int]] = {}
        for payload in batch:
            parsed = safe_parse(payload)
            # Append raw for well-formed readings (provenance + source linking). A
            # payload that fails to parse is still recorded as a PARSE decision by the
            # pipeline; it has no clean sensor_id/type/time to key a raw row on.
            if isinstance(parsed, ParsedReading):
                rid = store.append_raw(
                    parsed.sensor_id, parsed.sensor_type, parsed.sensor_time,
                    parsed.ingest_time, parsed.value, parsed.raw_payload,
                )
                raw_ids.setdefault(parsed.sensor_id, []).append(rid)

        # 2. Validate (deterministic).
        cycle = process_cycle(list(batch), registry, states, now)

        # 3. Persist verdicts + decision log.
        persist_cycle(store, cycle, raw_ids, now)

        # 4. Update caller's state for the next cycle.
        states.update(cycle.next_states)

        # 5. Build the structured summary.
        sensors = [
            SensorSummary(
                sensor_id=sid,
                sensor_health=r.sensor_health.value if isinstance(r.sensor_health, SensorHealth) else None,
                reading_status=r.reading_status.value if isinstance(r.reading_status, ReadingStatus) else None,
                value=r.value,
                clock_drift=r.clock_drift,
            )
            for sid, r in cycle.results.items()
        ]
        return CycleSummary(
            ok=True,
            sensors=sensors,
            raw_appended=sum(len(v) for v in raw_ids.values()),
            validated_written=sum(
                1 for r in cycle.reading_results if r.reading_status is not None
            ),
            decisions_logged=len(cycle.logs),
            conflicts=len(cycle.conflicts),
            parse_failures=len(cycle.parse_failures),
        )
    except Exception as exc:  # last-resort safety net — never leak a stack trace
        return CycleSummary(ok=False, error=f"cycle processing error: {exc!r}")
