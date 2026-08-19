"""P401 — the ingest batch contract: cap the batch, shape-check each reading.

The asymmetry between the two checks is the design.

**The batch cap raises.** An oversized batch is refused before any reading is examined,
because the alternative — accept it and store the first N — returns success while losing
readings. A gateway that receives a 200 stops retrying, so the tail is gone with nothing
recording that it existed (Principle II; plan §8: "never accepts a batch and drops
readings"). Checking the cap first also means a hostile 50k-reading payload costs one
comparison rather than 50k parses.

**Shape checks return, never raise.** One malformed reading must not reject its neighbours
(AC-1). A field Pi with one failing sensor would otherwise blind the entire bridge. So
`check_shape` answers with a `RejectionReason` or `None` and has no failure path of its own.

**`None` means "no shape objection", not "valid".** This module makes no judgment about
whether a reading is physically plausible, whether the sensor is drifting, or whether the
timestamp is sane — that is the DCA's verdict on its own cycle (Principle III). The only
question asked here is whether the reading can be stored as raw data at all.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from api.ingest.reasons import RejectionReason
from api.status_policy import ApiError, Failure

# A sensor id longer than this is not a name, it is a payload. Bounded so an id cannot
# become a memory or log-flood vector.
MAX_SENSOR_ID_LENGTH: Final = 128
MAX_FIELD_LENGTH: Final = 128

_DEFAULT_MAX_READINGS: Final = 1000


class ReadingInput(BaseModel):
    """One reading as presented. Every field is optional *here* on purpose.

    Pydantic rejecting a missing field would raise, and a raise at this layer costs the
    whole batch. So the model accepts anything shaped like an object and `check_shape`
    reports what is wrong, per reading.
    """

    # Extras are ignored rather than refused: newer gateway firmware sending a field we do
    # not know about is not a reason to lose its readings.
    model_config = ConfigDict(extra="ignore", strict=False)

    sensor_id: Any = None
    sensor_type: Any = None
    value: Any = None
    unit: Any = None
    sensor_time: Any = None


class IngestBatch(BaseModel):
    readings: list[ReadingInput]


def parse_batch(payload: Any, max_readings: int = _DEFAULT_MAX_READINGS) -> IngestBatch:
    """Parse the batch envelope and enforce the size cap. Raises for batch-level faults.

    Batch-level means "there is nothing to report per reading": a broken envelope, or a
    batch too large to accept. Everything a single reading can get wrong is handled by
    `check_shape` instead.
    """
    if max_readings <= 0:
        # Not an ApiError: a cap of zero rejects all traffic, which is a config bug, and
        # returning 422 to the gateway would blame the caller for our misconfiguration.
        raise ValueError(
            f"max_readings must be positive; got {max_readings}. A cap of zero would "
            "refuse every batch."
        )

    if not isinstance(payload, dict):
        raise ApiError(Failure.VALIDATION, "The request body must be a JSON object.")

    readings = payload.get("readings")
    if not isinstance(readings, list):
        raise ApiError(
            Failure.VALIDATION,
            "The request body must contain a 'readings' array.",
        )

    # Before any per-reading work: a batch we will refuse should not be parsed first.
    if len(readings) > max_readings:
        raise ApiError(
            Failure.VALIDATION,
            f"This batch contains {len(readings)} readings; the limit is {max_readings}. "
            "The batch was refused in full and no readings were stored — resend as "
            "smaller batches.",
        )

    parsed = []
    for item in readings:
        if not isinstance(item, dict):
            # A non-object in the array is a broken gateway, not a bad sample: there is no
            # reading to attach a per-reading reason to.
            raise ApiError(
                Failure.VALIDATION,
                "Every element of 'readings' must be a JSON object.",
            )
        parsed.append(ReadingInput(**item))

    return IngestBatch(readings=parsed)


def check_shape(reading: ReadingInput) -> RejectionReason | None:
    """The shape objection to one reading, or None. Never raises.

    Order matters only in that the first objection found is the one reported; a reading with
    two problems needs one actionable reason, not a list.
    """
    for field in (reading.sensor_id, reading.sensor_type, reading.unit):
        if not isinstance(field, str) or not field.strip():
            return RejectionReason.MISSING_FIELD
        if len(field.strip()) > MAX_FIELD_LENGTH:
            return RejectionReason.MISSING_FIELD

    if len(str(reading.sensor_id).strip()) > MAX_SENSOR_ID_LENGTH:
        return RejectionReason.MISSING_FIELD

    if not _is_finite_number(reading.value):
        return RejectionReason.NON_NUMERIC_VALUE

    if _parse_time(reading.sensor_time) is None:
        return RejectionReason.MALFORMED_TIMESTAMP

    return None


def _is_finite_number(value: Any) -> bool:
    """True for a real numeric reading.

    `bool` is excluded even though it is an `int` subclass: `True` would otherwise be stored
    as 1.0, a fabricated measurement. NaN and infinity are excluded because they pass a type
    check and then poison every downstream aggregate that touches them.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _parse_time(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, or None if it is not one.

    Only strings are accepted. A bare epoch integer is ambiguous between seconds and
    milliseconds, and guessing wrong silently places a reading years away from where it
    belongs — so it is refused rather than interpreted.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
