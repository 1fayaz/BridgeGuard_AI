"""P403 — process a batch into one positional result per reading.

The failure this exists to prevent: a batch of 50 arrives, one reading is malformed, the
endpoint returns 422, and the gateway retries the whole batch forever — the bad reading never
gets better. The other 49 good measurements are never stored and nothing records that they
were lost.

So a rejection is data, not an exception. `process_batch` never raises: it walks every reading,
appends the ones with no shape objection, and returns a result for each. N in, N out, indexed
by position (AC-1).

Three things that look like polish and are load-bearing:

**Results are positional and complete.** The gateway correlates them against what it sent by
index. Filtering to failures-only, deduplicating, or reordering breaks that correlation
silently — the gateway would attribute a rejection to the wrong reading.

**The counts are derived.** A summary that can disagree with the array it summarises is worse
than no summary, because a gateway trusting it would believe readings were stored that were
not.

**There is no batch-level verdict.** No `ok`, no `status`. A single boolean invites a gateway
author to check it and skip the per-reading array, which puts us right back at losing the
N−k good readings — this time with our own API's encouragement.

`accepted` means *durably appended*, not *valid* (P407). Whether a number is plausible is the
DCA's word on its own cycle, never the boundary's (Principle III).

**Tenancy and audit come from one object** (P408). The caller passes a `Principal`, not a tenant
string plus a separate audit identity. Two statements of the same fact can disagree, and the way
they disagree here is the worst available outcome: rows stamped MUNI_A with an audit row that
confidently says MUNI_B.

Ties to tasks.md P403 + P408, spec AC-1 + §1, plan §4 + §8.
"""
from __future__ import annotations

import uuid
from typing import Final

from pydantic import BaseModel, ConfigDict

from api.audit import ingest_audit
from api.auth.principal import Principal
from api.ingest.batch import IngestBatch, ReadingInput, check_shape
from api.ingest.ownership import SensorRegistry, check_ownership
from api.ingest.reasons import RejectionReason

_NO_OBJECTION: Final = None


class ReadingResult(BaseModel):
    """What happened to one reading. Frozen: a result is a record, not a working value.

    Carries no tenant. The gateway already knows its own scope, and echoing it back would put
    the tenancy model on the wire for no gain (INV-3's spirit at the response boundary).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    sensor_id: str | None
    accepted: bool
    reason: RejectionReason | None = None


class IngestOutcome(BaseModel):
    """The ack for one batch: every reading's result, plus a correlation id.

    Deliberately has no `ok`/`status` field — see the module docstring.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str
    results: list[ReadingResult]

    @property
    def accepted_count(self) -> int:
        return sum(1 for r in self.results if r.accepted)

    @property
    def rejected_count(self) -> int:
        return sum(1 for r in self.results if not r.accepted)


def process_batch(
    batch: IngestBatch,
    *,
    store,
    principal: Principal,
    registry: SensorRegistry,
    audit,
) -> IngestOutcome:
    """Append what can be stored, report on every reading, audit the call.

    Never raises *over a reading* — but see the audit note below for the one thing it does let
    through.

    The loop has no early exit on purpose: a `break` at the first rejection would drop every
    reading after it while still returning a plausible-looking result array.

    Shape is checked before ownership: a reading with no usable `sensor_id` cannot be looked up
    at all, and answering "unknown sensor" for a blank id would send an operator to the
    provisioning system over a payload bug (P404).

    `registry` and `audit` are both required, with no default. An optional one would make "skip
    the check" the behaviour a forgotten argument produces, so a wiring omission at the router
    would silently disable AC-2 or INV-5 while every test here still passed.

    **The audit write is not wrapped.** Every reading-level failure is data, but a failure to
    audit is deliberately allowed to escape as a 500. Swallowing it would leave rows durable and
    permanently unattributed with nothing to notice; raising makes the gateway resend, and a
    redelivery appends a second row and audits properly (P406). A duplicate reading is
    recoverable — an unauditable write is not.

    Audited per call, not per accepted reading: a batch where everything was refused is exactly
    the event an investigation needs to see, and auditing only writes would make a gateway whose
    readings are all rejected indistinguishable from one that never called.
    """
    results: list[ReadingResult] = []

    for index, reading in enumerate(batch.readings):
        reason = check_shape(reading)
        if reason is _NO_OBJECTION:
            reason = check_ownership(
                reading.sensor_id, reading.unit, registry, bridge_id=principal.bridge_id or ""
            )
        if reason is _NO_OBJECTION:
            store.append(
                _row(
                    reading,
                    municipality_id=principal.municipality_id,
                    bridge_id=principal.bridge_id or "",
                )
            )
        results.append(
            ReadingResult(
                index=index,
                sensor_id=_reported_sensor_id(reading),
                accepted=reason is _NO_OBJECTION,
                reason=reason,
            )
        )

    outcome = IngestOutcome(batch_id=str(uuid.uuid4()), results=results)
    audit.record(
        ingest_audit(
            principal,
            batch_id=outcome.batch_id,
            accepted_count=outcome.accepted_count,
            rejected_count=outcome.rejected_count,
        )
    )
    return outcome


def _row(reading: ReadingInput, *, municipality_id: str, bridge_id: str) -> dict:
    """Coerce here, not at parse time: anything check_shape passed is float()-able."""
    return {
        "sensor_id": str(reading.sensor_id).strip(),
        "sensor_type": str(reading.sensor_type).strip(),
        "value": float(reading.value),
        "unit": str(reading.unit).strip(),
        "sensor_time": str(reading.sensor_time).strip(),
        "bridge_id": bridge_id,
        "municipality_id": municipality_id,
    }


def _reported_sensor_id(reading: ReadingInput) -> str | None:
    """Echoed so a gateway can act without holding the body it sent.

    A non-string id was itself the objection, so there is nothing honest to name.
    """
    if not isinstance(reading.sensor_id, str) or not reading.sensor_id.strip():
        return None
    return reading.sensor_id.strip()
