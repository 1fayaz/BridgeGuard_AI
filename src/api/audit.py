"""P408 — the boundary's audit record: when, who, which tenant, which request.

INV-5 and Principle VI ask for every write to be audited. The interesting design question is
not *whether* to write a row — it is how to stop the row from being confidently wrong.

An audit record that goes missing is a visible gap. An audit record that says MUNI_B when the
readings landed under MUNI_A is worse than the gap, because an investigator gets an internally
consistent account of an event that did not happen, and nothing else in the system will
contradict it. `principal.py` states the same thing from the authentication side: the tenant a
request *ran* under and the tenant it was *audited* as must not be able to diverge.

The mechanism is that they are read from the same object. `build_ingest_record` takes a
`Principal` — not a tenant string plus a separate actor label — so there is no second value that
could disagree with the first. That is also why `process_batch` now takes the principal rather
than loose `municipality_id`/`bridge_id` arguments.

**What is deliberately not here.** No credential material: not the key, not its hash, not a
prefix. The record names *who* by credential class and identity, never by the thing that proved
it. A device key is the credential most likely to be physically extracted from a roadside
enclosure, and an audit table is the last place anyone would think to look for one.

[DB-DEP] `FakeAuditLog` stands in for the durable audit table, and mirrors its discipline by not
having the methods that would violate it — no update, no delete. The live equivalent belongs with
`decision_log` (0004), which is already a total-block table; wiring the boundary's audit into a
migration is a build step for the router (P1006 audits coverage across the whole layer).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from api.auth.principal import CredentialClass, Principal


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One audited event at the boundary.

    Frozen, because a record is testimony rather than a working value. Slotted, so a caller
    cannot staple an extra field on — including one holding the credential this deliberately
    does not record.

    The identity fields mirror `Principal` rather than collapsing into a single `actor` string:
    a collapsed field has to be decoded against the credential class before it can be read at
    all, and a reader who decodes it wrong misattributes the event.
    """

    recorded_at: datetime
    batch_id: str
    municipality_id: str
    credential_class: CredentialClass
    user_id: str | None
    bridge_id: str | None
    accepted_count: int
    rejected_count: int


def ingest_audit(
    principal: Principal,
    *,
    batch_id: str,
    accepted_count: int,
    rejected_count: int,
) -> AuditRecord:
    """Build the record for one ingest call.

    `batch_id` is the id the gateway was handed in its ack, not a private internal one. An
    operator holding a Pi's log can quote it and land on exactly one audit row; a private id
    would make the ack and the audit two things joined by guesswork.

    Timezone-aware UTC, always. A naive timestamp in an audit trail means something different
    depending on which host wrote it, which makes reconstructing an order of events across a
    deployment impossible.
    """
    return AuditRecord(
        recorded_at=datetime.now(UTC),
        batch_id=batch_id,
        municipality_id=principal.municipality_id,
        credential_class=principal.credential_class,
        user_id=principal.user_id,
        bridge_id=principal.bridge_id,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
    )


class FakeAuditLog:
    """Append-only in-memory audit sink. Not thread-safe; tests are serial.

    No `update`, no `delete`, no `clear` — the same absence-as-enforcement the raw store uses
    (P405). An audit trail a regulator relies on is only evidence if it cannot be edited after
    the fact, and a method that edits it is one autocomplete away from being called.
    """

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def record(self, record: AuditRecord) -> None:
        self._records.append(record)

    @property
    def records(self) -> list[AuditRecord]:
        """A copy of the list. The records themselves are frozen, so they need no copying."""
        return list(self._records)

    def count(self) -> int:
        return len(self._records)
