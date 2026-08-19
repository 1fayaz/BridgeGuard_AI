"""P408 — every ingest call leaves one audit record: when, who, which tenant, which request.

An audit trail is only worth having if it is worth believing, and the way this one stops being
worth believing is subtle. It is not that a record goes missing — that is visible. It is that a
record is *present and wrong*: the rows landed under MUNI_A and the audit says MUNI_B. An
investigator then has a confident, internally consistent account of something that did not
happen, and every conclusion drawn from it is wrong in a way nothing else in the system will
contradict. `principal.py` already names this: the tenant a request *ran* under and the tenant
it was *audited* as must not be able to diverge.

So the fix is structural rather than careful. `process_batch` no longer takes loose
`municipality_id` / `bridge_id` strings alongside a caller-supplied audit identity; it takes the
`Principal`, and both the tenancy stamped on the rows and the tenancy written to the audit are
read from that one object. There is no second value that could disagree with the first, because
there is no second value.

Three further commitments, each with a specific failure behind it:

**Every call is audited, not every successful call.** A batch where every reading was rejected
stored nothing — and is exactly the event an investigation needs to see. If only writes were
audited, a Pi whose readings are all being refused would leave no trace at all, and the silence
would be indistinguishable from a gateway that never called.

**The causing request is the `batch_id` the gateway was handed.** Not a separate internal id the
caller never sees. An operator holding a Pi's log can quote the id in the ack and land on exactly
one audit row; a private id would make the ack and the audit two things that have to be joined by
guesswork.

**No credential material is recorded.** The audit names *who* by credential class and identity —
never the key that proved it. A device key is the credential most likely to be extracted from a
roadside enclosure, and an audit table is the one place nobody thinks to look for one.

Ties to tasks.md P408, plan §4 + §8 (Audit), INV-5, Principle VI.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.audit import AuditRecord, FakeAuditLog, ingest_audit
from api.auth.principal import CredentialClass, Principal
from api.ingest.batch import parse_batch
from api.ingest.ownership import SensorRegistry
from api.ingest.processor import process_batch
from api.ingest.raw_store import FakeRawStore

AUDIT_MODULE = Path(__file__).resolve().parents[2] / "src" / "api" / "audit.py"

GOOD = {
    "sensor_id": "S_OURS",
    "sensor_type": "strain",
    "value": 12.5,
    "unit": "microstrain",
    "sensor_time": "2026-08-05T10:00:00Z",
}
BAD_VALUE = {**GOOD, "value": "twelve"}


class _OurBridge:
    def has_sensor(self, sensor_id: str) -> bool:
        return True

    def bridge_of_sensor(self, sensor_id: str) -> str:
        return "BRIDGE_1"

    def get_sensor(self, sensor_id: str):
        return _Unconfigured()


class _Unconfigured:
    config: dict = {}


@pytest.fixture
def store() -> FakeRawStore:
    return FakeRawStore()


@pytest.fixture
def audit() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture
def pi() -> Principal:
    return Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1")


def run(payloads: list[dict], store: FakeRawStore, audit: FakeAuditLog, principal: Principal):
    return process_batch(
        parse_batch({"readings": payloads}),
        store=store,
        principal=principal,
        registry=SensorRegistry(_OurBridge()),
        audit=audit,
    )


def _code_only(src: str) -> str:
    """Strip docstrings before scanning, so a module's honest prose about what it refuses to
    hold does not read as it holding it."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    body.pop(0)
    return ast.unparse(tree)


# ------------------------------------------------- the record carries all four required facts ---
def test_one_ingest_call_writes_exactly_one_audit_record(store, audit, pi):
    """Per call, not per reading. The readings themselves are the raw log's job; this row is
    the record that a caller, at a time, caused a write."""
    run([GOOD, GOOD, GOOD], store, audit, pi)
    assert audit.count() == 1


def test_the_record_carries_a_timestamp(store, audit, pi):
    before = datetime.now(UTC)
    run([GOOD], store, audit, pi)
    after = datetime.now(UTC)
    assert before <= audit.records[0].recorded_at <= after


def test_the_timestamp_is_timezone_aware_utc(store, audit, pi):
    """A naive timestamp in an audit trail is a timestamp whose meaning depends on which host
    wrote it — unusable for reconstructing an order of events across a deployment."""
    recorded_at = ingest_audit(
        Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1"),
        batch_id="b-1",
        accepted_count=0,
        rejected_count=0,
    ).recorded_at
    assert recorded_at.tzinfo is not None
    assert recorded_at.utcoffset().total_seconds() == 0


def test_the_record_carries_the_tenant(store, audit, pi):
    run([GOOD], store, audit, pi)
    assert audit.records[0].municipality_id == "MUNI_A"


def test_the_record_carries_the_credential_class(store, audit, pi):
    """Which *kind* of caller wrote. A device key and an engineer JWT reaching the same
    endpoint are different events, and only one of them is expected."""
    run([GOOD], store, audit, pi)
    assert audit.records[0].credential_class is CredentialClass.DEVICE_KEY


def test_the_record_names_the_device_that_called(store, audit, pi):
    run([GOOD], store, audit, pi)
    assert audit.records[0].bridge_id == "BRIDGE_1"
    assert audit.records[0].user_id is None


def test_an_engineer_principal_records_a_human_identity_instead():
    """The identity fields mirror `Principal` rather than collapsing into one `actor` string.
    A collapsed field would need decoding against the credential class to be read at all."""
    record = ingest_audit(
        Principal.for_engineer(municipality_id="MUNI_A", user_id="eng-7"),
        batch_id="b-1",
        accepted_count=1,
        rejected_count=0,
    )
    assert record.user_id == "eng-7"
    assert record.bridge_id is None


def test_the_record_carries_the_causing_request(store, audit, pi):
    outcome = run([GOOD], store, audit, pi)
    assert audit.records[0].batch_id == outcome.batch_id


def test_the_gateway_can_quote_the_id_it_was_given(store, audit, pi):
    """The point of using the ack's id rather than a private one: a Pi's log line resolves to
    exactly one audit row with no join anyone has to invent."""
    first = run([GOOD], store, audit, pi)
    run([GOOD], store, audit, pi)
    matching = [r for r in audit.records if r.batch_id == first.batch_id]
    assert len(matching) == 1


def test_two_attempts_leave_two_distinguishable_records(store, audit, pi):
    """P406: a redelivery is normal traffic, and the audit has to show it as two deliveries
    rather than one — otherwise a retry storm is invisible."""
    run([GOOD], store, audit, pi)
    run([GOOD], store, audit, pi)
    assert audit.count() == 2
    assert audit.records[0].batch_id != audit.records[1].batch_id


def test_the_record_states_what_the_write_did(store, audit, pi):
    run([GOOD, BAD_VALUE, GOOD], store, audit, pi)
    record = audit.records[0]
    assert record.accepted_count == 2
    assert record.rejected_count == 1


# ------------------------------------- the tenant comes from the credential, never the payload ---
def test_a_payload_naming_another_tenant_does_not_move_the_audit(store, audit, pi):
    """INV-3 at the audit boundary. A supplied id is not a grant, and it is not a testimony
    either."""
    run([{**GOOD, "municipality_id": "MUNI_B", "bridge_id": "BRIDGE_2"}], store, audit, pi)
    assert audit.records[0].municipality_id == "MUNI_A"
    assert audit.records[0].bridge_id == "BRIDGE_1"


def test_the_audited_tenant_is_the_tenant_the_rows_were_stamped_with(store, audit, pi):
    """The failure this task is really about.

    Not a missing record — a present one that confidently testifies to the wrong tenant. The
    two values must be read from the same object, so this can only fail if that stops being
    true.
    """
    run([GOOD], store, audit, pi)
    assert store.rows[0]["municipality_id"] == audit.records[0].municipality_id
    assert store.rows[0]["bridge_id"] == audit.records[0].bridge_id


def test_a_second_tenants_call_is_audited_under_its_own_tenant(store, audit):
    other = Principal.for_device(municipality_id="MUNI_B", bridge_id="BRIDGE_1")
    run([GOOD], store, audit, other)
    assert audit.records[0].municipality_id == "MUNI_B"
    assert store.rows[0]["municipality_id"] == "MUNI_B"


def test_the_processor_takes_a_principal_not_loose_tenant_strings():
    """Structural, and the whole mechanism.

    Loose `municipality_id`/`bridge_id` arguments alongside an audit identity are two statements
    of the same fact, and a wiring bug at the router could make them disagree with nothing to
    catch it. One object, one source.
    """
    params = set(inspect.signature(process_batch).parameters)
    assert params == {"batch", "store", "principal", "registry", "audit"}
    assert "municipality_id" not in params
    assert "bridge_id" not in params


# ------------------------------------------ every call is audited, not every successful one ---
def test_a_batch_that_stored_nothing_is_still_audited(store, audit, pi):
    """The event an investigation most needs to see. If only writes were audited, a gateway
    whose readings are all refused would be indistinguishable from one that never called."""
    run([BAD_VALUE, BAD_VALUE], store, audit, pi)
    assert store.count() == 0
    assert audit.count() == 1
    assert audit.records[0].accepted_count == 0
    assert audit.records[0].rejected_count == 2


def test_an_empty_batch_is_still_audited(store, audit, pi):
    run([], store, audit, pi)
    assert audit.count() == 1
    assert audit.records[0].accepted_count == 0


def test_the_audited_counts_match_the_ack_the_gateway_received(store, audit, pi):
    """A record that disagrees with what the caller was told is a second version of events."""
    outcome = run([GOOD, BAD_VALUE, GOOD, BAD_VALUE, GOOD], store, audit, pi)
    record = audit.records[0]
    assert record.accepted_count == outcome.accepted_count
    assert record.rejected_count == outcome.rejected_count


def test_the_audited_accepted_count_matches_what_actually_landed(store, audit, pi):
    """Counts derived from intent rather than from the loop would drift the moment a reading
    was rejected after the count was taken."""
    run([GOOD, BAD_VALUE, GOOD], store, audit, pi)
    assert audit.records[0].accepted_count == store.count()


def test_a_cross_bridge_rejection_is_audited_as_a_rejection(store, audit):
    """P404's foreign sensor, seen from the audit side: refused, and the refusal is on record."""
    elsewhere = Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_9")
    run([GOOD], store, audit, elsewhere)
    assert audit.records[0].rejected_count == 1
    assert audit.records[0].bridge_id == "BRIDGE_9"


# ----------------------------------------------------- no credential material is ever recorded ---
def test_the_record_has_no_field_that_could_hold_a_key(store, audit, pi):
    fields = {f.name for f in dataclasses.fields(AuditRecord)}
    for banned in ("api_key", "key", "key_hash", "token", "secret", "password", "credential",
                   "authorization", "bearer"):
        assert banned not in fields, f"the audit record can hold credential material: {banned}"


def test_the_record_is_pinned_to_exactly_the_eight_audited_facts():
    """Pinned so a field cannot be added without a reader of this test noticing what it is."""
    fields = {f.name for f in dataclasses.fields(AuditRecord)}
    assert fields == {
        "recorded_at", "batch_id", "municipality_id", "credential_class",
        "user_id", "bridge_id", "accepted_count", "rejected_count",
    }


def test_a_records_repr_carries_no_credential_material(store, audit, pi):
    """An audit row is printed into operator-facing tooling more than most objects."""
    run([GOOD], store, audit, pi)
    blob = repr(audit.records[0]).lower()
    for banned in ("apikey", "key_hash", "secret", "bearer", "authorization"):
        assert banned not in blob


def test_the_audit_module_never_names_a_credential():
    """Structural, over code with docstrings stripped. `credential_class` is the one legitimate
    appearance of the word, so the scan targets the material rather than the concept."""
    body = _code_only(AUDIT_MODULE.read_text(encoding="utf-8")).lower()
    for banned in ("api_key", "key_hash", "raw_key", "token", "secret", "password",
                   "authorization", "bearer"):
        assert banned not in body, f"the audit module handles credential material: {banned}"


# ------------------------------------------------------------------- the audit is append-only ---
def test_the_audit_log_offers_no_mutation_method():
    """Same discipline as the raw store (P405), for the same reason: an audit trail a regulator
    relies on is only evidence if it cannot be edited after the fact."""
    for banned in ("update", "delete", "remove", "clear", "truncate", "overwrite", "replace",
                   "pop", "purge", "amend"):
        assert not hasattr(FakeAuditLog, banned), f"FakeAuditLog exposes {banned}"


def test_the_audit_log_exposes_exactly_one_way_in():
    public = {n for n in dir(FakeAuditLog) if not n.startswith("_")}
    assert public == {"record", "records", "count"}


def test_the_records_view_hands_back_a_copy(store, audit, pi):
    run([GOOD], store, audit, pi)
    snapshot = audit.records
    snapshot.clear()
    assert audit.count() == 1


def test_a_record_cannot_be_edited_after_the_fact(store, audit, pi):
    """Frozen: a record is testimony, not a working value."""
    run([GOOD], store, audit, pi)
    with pytest.raises(dataclasses.FrozenInstanceError):
        audit.records[0].municipality_id = "MUNI_B"


def test_a_later_call_appends_rather_than_replacing(store, audit, pi):
    run([GOOD], store, audit, pi)
    first = audit.records[0]
    run([GOOD], store, audit, pi)
    assert audit.count() == 2
    assert audit.records[0] == first


def test_the_processor_only_ever_records(store, audit, pi):
    """Read as source: the ingest path's sole interaction with the audit log."""
    src = inspect.getsource(inspect.getmodule(process_batch))
    calls = [
        node.func.attr
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "audit"
    ]
    assert calls == ["record"], f"the processor touches the audit log otherwise: {calls}"


# ------------------------------------------------------------- the audit cannot be skipped ---
def test_the_audit_cannot_be_skipped_by_omission(store, pi):
    """`audit` has no default, for the same reason `registry` has none (P404).

    An optional audit makes "do not audit" the behaviour a forgotten argument produces, so a
    wiring omission at the router would silently disable INV-5 while every other test passed.
    """
    with pytest.raises(TypeError):
        process_batch(
            parse_batch({"readings": [GOOD]}),
            store=store,
            principal=pi,
            registry=SensorRegistry(_OurBridge()),
        )


class _BrokenAuditLog:
    """An audit sink that cannot write. A dropped connection, a full disk."""

    def record(self, record: AuditRecord) -> None:
        raise RuntimeError("audit unavailable")


def test_an_audit_failure_costs_the_batch_rather_than_going_unaudited(store, pi):
    """The one place this layer deliberately prefers a 500 to a 200.

    Both outcomes are bad, but only one is recoverable. If the audit write is swallowed, the
    rows are durable and permanently unattributed — nothing will ever notice. If it raises, the
    gateway sees a failure and resends, and a redelivery is normal traffic that appends a second
    row and audits properly (P406). A duplicate reading is recoverable; an unauditable write is
    not.
    """
    with pytest.raises(RuntimeError):
        process_batch(
            parse_batch({"readings": [GOOD]}),
            store=store,
            principal=pi,
            registry=SensorRegistry(_OurBridge()),
            audit=_BrokenAuditLog(),
        )


def test_an_audit_failure_is_not_reported_to_the_caller_as_success(store, pi):
    """Restating the above as the property that matters: no path returns an outcome that the
    audit log has no record of."""
    audit = _BrokenAuditLog()
    outcome = None
    try:
        outcome = process_batch(
            parse_batch({"readings": [GOOD]}),
            store=store,
            principal=pi,
            registry=SensorRegistry(_OurBridge()),
            audit=audit,
        )
    except RuntimeError:
        pass
    assert outcome is None
