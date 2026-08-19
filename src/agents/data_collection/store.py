"""Persistence boundary + FakeStore (T903) [DB-DEP].

Defines the Store protocol the agent writes through, and an in-memory FakeStore that
MIRRORS the four migrations' guarantees so the full pipeline is verifiable without a
live Supabase:

  * raw_readings (0001)      — append-only; raw rows can only grow, never mutate/delete.
  * validated_readings (0002)— every row links to its raw source id(s); corrections are
    appended + supersede, never overwrite.
  * sensor_status (0003)     — one CURRENT row per sensor (latest device health).
  * decision_log (0004)      — append-only audit; one row per reject/flag/interp/
    status-change/correction/clock-drift/dup-conflict, each WITH a reason. A clean OK
    flow is recorded by its validated row, NOT spammed to the log.

When a real Supabase exists, a SupabaseStore implements the same surface and the
migrations enforce these guarantees in the database. Until then the FakeStore is the
system of record for tests, and the live enforcement is [DB-DEP] / deferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from agents.data_collection.agent import CycleResult
from agents.data_collection.statuses import ReadingStatus, SensorHealth


@dataclass(frozen=True, slots=True)
class RawRow:
    raw_id: int
    sensor_id: str
    sensor_type: str
    sensor_time: datetime
    ingest_time: datetime | None
    value: float | None
    raw_payload: Any


@dataclass(frozen=True, slots=True)
class ValidatedRow:
    row_id: int
    sensor_id: str
    sensor_time: datetime | None
    value: float | None
    status: ReadingStatus
    is_interpolated: bool
    clock_drift: bool
    source_raw_ids: tuple[int, ...]
    reason: str | None
    superseded_by: int | None = None


@dataclass(frozen=True, slots=True)
class StatusRow:
    sensor_id: str
    health: SensorHealth | None
    last_seen: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LogRow:
    log_id: int
    sensor_id: str
    decision: str
    old_status: str | None
    new_status: str | None
    reason: str


class RawAppendOnlyViolation(Exception):
    """Raised if anything attempts to mutate/delete a raw row (mirrors the 0001 trigger)."""


class FakeStore:
    """In-memory store mirroring the schema guarantees. Not thread-safe; tests are serial."""

    def __init__(self) -> None:
        self._raw: list[RawRow] = []
        self._validated: list[ValidatedRow] = []
        self._status: dict[str, StatusRow] = {}
        self._logs: list[LogRow] = []
        self._next_raw_id = 1
        self._next_row_id = 1
        self._next_log_id = 1

    # --- raw_readings (append-only) ------------------------------------------
    def append_raw(
        self,
        sensor_id: str,
        sensor_type: str,
        sensor_time: datetime,
        ingest_time: datetime | None,
        value: float | None,
        raw_payload: Any,
    ) -> int:
        """Append one raw row on receipt; returns its id. The ONLY way raw grows."""
        row = RawRow(self._next_raw_id, sensor_id, sensor_type, sensor_time,
                     ingest_time, value, raw_payload)
        self._raw.append(row)
        self._next_raw_id += 1
        return row.raw_id

    def raw_count(self) -> int:
        return len(self._raw)

    @property
    def raw_rows(self) -> list[RawRow]:
        return list(self._raw)

    def _forbid_raw_mutation(self) -> None:
        raise RawAppendOnlyViolation(
            "raw_readings is append-only (Constitution II): UPDATE/DELETE blocked"
        )

    # --- validated_readings --------------------------------------------------
    def insert_validated(self, row: ValidatedRow) -> int:
        """Insert a validated row. The STORE owns the row id — the caller's row_id is
        overwritten with the next sequential id (PREEMPTIVE guard, Fix #8). Today every
        caller passes store._next_row_id so ids stay in lockstep and nothing is broken;
        stamping it here removes id-desync as a possibility for a future caller (e.g.
        late-arrival correction persistence, T801) that might construct a row with a
        guessed or duplicate id. Not a fix of a confirmed live bug — a boundary guard."""
        row = replace(row, row_id=self._next_row_id)
        self._validated.append(row)
        self._next_row_id += 1
        return row.row_id

    def supersede(self, old_row_id: int, new_row_id: int) -> None:
        """Stamp superseded_by on a prior verdict (the only permitted validated update)."""
        for i, r in enumerate(self._validated):
            if r.row_id == old_row_id:
                self._validated[i] = replace(r, superseded_by=new_row_id)
                return

    @property
    def validated_rows(self) -> list[ValidatedRow]:
        return list(self._validated)

    def current_validated(self, sensor_id: str) -> list[ValidatedRow]:
        """Non-superseded rows for a sensor (the current verdicts)."""
        return [r for r in self._validated
                if r.sensor_id == sensor_id and r.superseded_by is None]

    # --- sensor_status (current per sensor) ----------------------------------
    def upsert_status(self, row: StatusRow) -> None:
        self._status[row.sensor_id] = row

    @property
    def status_rows(self) -> dict[str, StatusRow]:
        return dict(self._status)

    # --- decision_log (append-only) ------------------------------------------
    def append_log(self, sensor_id: str, decision: str, old_status: str | None,
                   new_status: str | None, reason: str) -> int:
        row = LogRow(self._next_log_id, sensor_id, decision, old_status, new_status, reason)
        self._logs.append(row)
        self._next_log_id += 1
        return row.log_id

    @property
    def log_rows(self) -> list[LogRow]:
        return list(self._logs)

    def logs_for(self, sensor_id: str) -> list[LogRow]:
        return [r for r in self._logs if r.sensor_id == sensor_id]

    def logs_of(self, decision: str) -> list[LogRow]:
        return [r for r in self._logs if r.decision == decision]


def persist_cycle(
    store: FakeStore,
    cycle: CycleResult,
    raw_ids_by_sensor: dict[str, list[int]],
    now: datetime,
) -> None:
    """Write a completed cycle to the store (validated rows + status + decision log).

    raw_ids_by_sensor maps each reporting sensor to the raw row id(s) appended for it
    this cycle, so every derived validated row links back to immutable source (Const.
    II/VI). A silent sensor has no raw ids -> its NO_DATA verdict links to none.

    The cycle's decision entries (already built by the orchestrator) are appended to the
    log verbatim. A clean OK reading produces a validated row but no extra log spam.
    """
    # Map this cycle's raw ids to their sensor_time so each validated row links to the
    # raw row it actually derived from (a sensor reporting several readings gets several
    # validated rows, each linked to its OWN raw source — Const. II provenance).
    raw_by_id = {r.raw_id: r for r in store.raw_rows}

    # Validated rows: ONE PER READING (a sensor may report several this cycle). Each row
    # carries the reading's OWN timestamp (result.sensor_time) — a silent sensor's
    # NO_DATA row has sensor_time=None, not a stale prior timestamp.
    for result in cycle.reading_results:
        if result.reading_status is None:
            continue
        time_to_ids: dict[Any, list[int]] = {}
        for rid in raw_ids_by_sensor.get(result.sensor_id, ()):
            rr = raw_by_id.get(rid)
            if rr is not None:
                time_to_ids.setdefault(rr.sensor_time, []).append(rid)
        source_ids = tuple(time_to_ids.get(result.sensor_time, ()))
        row = ValidatedRow(
            row_id=store._next_row_id,
            sensor_id=result.sensor_id,
            sensor_time=result.sensor_time,
            value=result.value,
            status=result.reading_status,
            is_interpolated=result.reading_status is ReadingStatus.INTERPOLATED,
            clock_drift=result.clock_drift,
            source_raw_ids=source_ids,
            reason=result.reason,
        )
        store.insert_validated(row)

    # sensor_status: ONE current row per sensor (the terminal verdict's device health).
    for sensor_id, result in cycle.results.items():
        next_state = cycle.next_states.get(sensor_id)
        store.upsert_status(StatusRow(
            sensor_id=sensor_id,
            health=result.sensor_health,
            last_seen=next_state.last_seen if next_state else None,
            updated_at=now,
        ))

    # Decision log: append every entry the orchestrator recorded (incl. PARSE,
    # DUPLICATE_CONFLICT, CLOCK_DRIFT, RANGE, SPIKE, LIVENESS). OK is NOT logged here.
    for entry in cycle.logs:
        store.append_log(entry.sensor_id, entry.decision,
                         entry.old_status, entry.new_status, entry.reason)
