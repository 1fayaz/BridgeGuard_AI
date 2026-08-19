"""Defensive payload parsing (FR-6 / AC-7) — a bad payload is a status, never a crash.

The agent receives raw sensor payloads (dicts off the MQTT/n8n path). They may be
malformed in every imaginable way: missing fields, wrong types, an unparseable
timestamp, a non-numeric value, extra junk. None of these may raise — a single bad
payload must become a CORRUPT verdict with a reason, so the cycle keeps going and the
bad reading is recorded rather than silently dropped or crashing the run.

safe_parse() turns one payload into either a ParsedReading (well-formed enough to
validate) or a ParseFailure (CORRUPT + reason). The raw payload is preserved on both so
provenance survives even total garbage (Const. II — every number traceable; a number we
couldn't parse is still recorded as having arrived).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agents.data_collection.statuses import ReadingStatus


@dataclass(frozen=True, slots=True)
class ParsedReading:
    """A payload parsed into the fields the validation pipeline needs."""

    sensor_id: str
    sensor_type: str
    sensor_time: datetime
    value: float | None      # None is allowed (e.g. an explicit null reading) ...
    ingest_time: datetime | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParseFailure:
    """A payload that could not be parsed -> CORRUPT. raw_payload is kept for forensics."""

    sensor_id: str | None
    raw_payload: Any
    reason: str
    status: ReadingStatus = ReadingStatus.CORRUPT


def _coerce_time(value: Any) -> datetime | None:
    """Parse a timestamp to a TIMEZONE-AWARE datetime. None/invalid -> None.

    Every timestamp is normalised to UTC-aware so downstream datetime arithmetic
    (liveness subtraction, dedup sort, drift gap) never mixes naive and aware values —
    a mixed-awareness batch would otherwise raise TypeError and blind the whole cycle.
    An offset-less input is ASSUMED UTC (the system's canonical zone); a sensor that
    truly needs a different zone must send an explicit offset.
    """
    if isinstance(value, datetime):
        return _to_utc(value)
    if isinstance(value, str):
        try:
            # Accept trailing 'Z' (UTC) which fromisoformat rejects before 3.11-ish.
            return _to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _to_utc(dt: datetime) -> datetime:
    """Make a datetime timezone-aware (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def safe_parse(payload: Any) -> ParsedReading | ParseFailure:
    """Parse one raw payload. NEVER raises.

    A payload must be a mapping with at least: sensor_id (str), sensor_type (str), a
    parseable timestamp (`sensor_time` or `time`), and a numeric `value` (or explicit
    null). Anything else -> ParseFailure(CORRUPT) with a specific reason.
    """
    # Not even a dict: total garbage. Record it, do not crash.
    if not isinstance(payload, dict):
        return ParseFailure(
            sensor_id=None,
            raw_payload=payload,
            reason=f"payload is not an object (got {type(payload).__name__})",
        )

    sensor_id = payload.get("sensor_id")
    if not isinstance(sensor_id, str) or not sensor_id:
        return ParseFailure(
            sensor_id=sensor_id if isinstance(sensor_id, str) else None,
            raw_payload=payload,
            reason="missing or non-string 'sensor_id'",
        )

    sensor_type = payload.get("sensor_type")
    if not isinstance(sensor_type, str) or not sensor_type:
        return ParseFailure(
            sensor_id=sensor_id,
            raw_payload=payload,
            reason="missing or non-string 'sensor_type'",
        )

    raw_time = payload.get("sensor_time", payload.get("time"))
    sensor_time = _coerce_time(raw_time)
    if sensor_time is None:
        return ParseFailure(
            sensor_id=sensor_id,
            raw_payload=payload,
            reason=f"missing or unparseable timestamp (got {raw_time!r})",
        )

    ingest_time = _coerce_time(payload.get("ingest_time"))

    # Value: may be an explicit null (None) — that is a valid "no reading" and flows on
    # to range/liveness which decide its status. But a present non-numeric value (a
    # string, a list) is malformed -> CORRUPT.
    value: float | None = None
    if "value" in payload and payload["value"] is not None:
        raw_value = payload["value"]
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            return ParseFailure(
                sensor_id=sensor_id,
                raw_payload=payload,
                reason=f"non-numeric 'value' {raw_value!r}",
            )
        value = float(raw_value)

    return ParsedReading(
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        sensor_time=sensor_time,
        value=value,
        ingest_time=ingest_time,
        raw_payload=payload,
    )
