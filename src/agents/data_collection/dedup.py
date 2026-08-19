"""Dedup + ordering (AC-7 / decision G4) — first-wins, conflicts logged, never averaged.

Readings can arrive duplicated or out of order (at-least-once MQTT delivery, retries,
network reordering). Before validation we normalise the batch:

  * ORDER by the sensor's OWN timestamp (G4), not arrival order, so the timeline the
    checks see is chronological.
  * DEDUP by (sensor_id, sensor_time):
      - identical value     -> silently collapsed to one logical reading (the raw rows
                               are preserved upstream; this only de-dups the logical
                               stream).
      - conflicting value   -> the FIRST-RECEIVED value wins; the later one is discarded
                               and a DUPLICATE_CONFLICT is logged recording BOTH values
                               with the exact reason string. No averaging, no
                               confidence pick — a deterministic, auditable rule.

"First received" is arrival order, so dedup is decided BEFORE the chronological sort
(sorting by sensor_time would otherwise destroy the arrival order that breaks ties).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.data_collection.parsing import ParsedReading

# The exact, canonical reason string for a duplicate-with-conflict (decision G4).
DUPLICATE_CONFLICT_REASON = "duplicate timestamp, conflicting value, first-received kept"


@dataclass(frozen=True, slots=True)
class DuplicateConflict:
    """A discarded conflicting duplicate, for the DUPLICATE_CONFLICT decision_log entry."""

    sensor_id: str
    sensor_time: datetime
    kept_value: float | None       # the first-received value that won
    discarded_value: float | None  # the later, conflicting value that was dropped
    reason: str = DUPLICATE_CONFLICT_REASON


@dataclass(frozen=True, slots=True)
class DedupResult:
    """The normalised batch: deduped readings (chronological) + any conflict logs."""

    readings: list[ParsedReading]
    conflicts: list[DuplicateConflict]


def dedup_and_order(readings: list[ParsedReading]) -> DedupResult:
    """Dedup by (sensor_id, sensor_time) first-wins, then order by sensor timestamp.

    Args:
        readings: parsed readings in ARRIVAL order (the order matters for first-wins).

    Returns:
        DedupResult with one logical reading per (sensor_id, sensor_time), sorted by
        sensor_time, plus a DuplicateConflict per conflicting duplicate dropped.
    """
    kept: dict[tuple[str, datetime], ParsedReading] = {}
    conflicts: list[DuplicateConflict] = []

    # Pass 1 — dedup in ARRIVAL order so "first received" is well-defined.
    for reading in readings:
        key = (reading.sensor_id, reading.sensor_time)
        existing = kept.get(key)
        if existing is None:
            kept[key] = reading
            continue
        # Same sensor + timestamp already seen.
        if existing.value == reading.value:
            # Identical duplicate: silently collapse (keep the first, drop this one).
            continue
        # Conflicting duplicate: first-received wins; log both values, discard this one.
        conflicts.append(DuplicateConflict(
            sensor_id=reading.sensor_id,
            sensor_time=reading.sensor_time,
            kept_value=existing.value,
            discarded_value=reading.value,
        ))

    # Pass 2 — order the survivors by the sensor's own timestamp (G4).
    ordered = sorted(kept.values(), key=lambda r: r.sensor_time)
    return DedupResult(readings=ordered, conflicts=conflicts)
