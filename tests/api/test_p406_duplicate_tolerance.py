"""P406 — a retry is normal traffic, not an error.

A Pi on a bridge has an intermittent uplink. It sends a batch, the connection drops before the
ack arrives, and it sends the same batch again — because from the gateway's side those two
outcomes are indistinguishable, and the only safe thing a field device can do with an
unacknowledged batch is resend it. That is not a fault. It is the protocol working.

The failure mode this task exists to prevent is what happens if we treat it as one. Suppose a
redelivered reading came back rejected, with a `duplicate` reason. The Pi now has a batch it
cannot get accepted and cannot distinguish from a real refusal, so its retry logic either loops
forever or gives up and drops the readings. Both outcomes lose sensor data from a bridge, and
the second one loses it silently — which is the Principle II failure, arriving by way of an
error code that looked reasonable.

So there is no duplicate rejection. A redelivery is accepted, and the append log grows by
another row (P405: two arrivals of one measurement are two facts, and the DCA decides which to
use on its own cycle with the full series in view).

Two things this deliberately does *not* do:

**No idempotency key.** Requiring one would make correctness depend on the gateway's firmware
getting it right, and a Pi that generates a key per attempt rather than per batch would defeat
it while looking compliant. The append log needs no such cooperation.

**No content-hash de-duplication.** Two identical readings a second apart are indistinguishable
from one reading delivered twice, and picking wrong in either direction is a judgment the
boundary is not entitled to make (Principle III). A vibration sensor at rest legitimately
reports the same value repeatedly.

Ties to tasks.md P406, spec §1, plan §4.
"""
from __future__ import annotations

import inspect

import pytest

from api.audit import FakeAuditLog
from api.auth.principal import Principal
from api.ingest.batch import parse_batch
from api.ingest.ownership import SensorRegistry
from api.ingest.processor import process_batch
from api.ingest.raw_store import FakeRawStore
from api.ingest.reasons import REASON_GUIDANCE, RejectionReason

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


def run(payloads: list[dict], store: FakeRawStore):
    return process_batch(
        parse_batch({"readings": payloads}),
        store=store,
        principal=Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1"),
        registry=SensorRegistry(_OurBridge()),
        audit=FakeAuditLog(),
    )


# --------------------------------------------- a redelivery is not reported as a failure ---
def test_a_redelivered_batch_is_accepted(store: FakeRawStore):
    """The headline rule. A retry that comes back rejected has nowhere left to go."""
    run([GOOD], store)
    second = run([GOOD], store)
    assert second.accepted_count == 1
    assert second.rejected_count == 0


def test_a_redelivered_reading_carries_no_rejection_reason(store: FakeRawStore):
    run([GOOD], store)
    second = run([GOOD], store)
    assert second.results[0].reason is None
    assert second.results[0].accepted is True


def test_the_tenth_redelivery_is_still_accepted(store: FakeRawStore):
    """A Pi with a bad uplink may retry many times. There is no attempt budget."""
    for _ in range(10):
        outcome = run([GOOD], store)
        assert outcome.accepted_count == 1


def test_a_redelivery_does_not_raise(store: FakeRawStore):
    """Not an HTTP error either — that would cost the batch's other readings (P403)."""
    run([GOOD, {**GOOD, "value": 20.0}], store)
    second = run([GOOD, {**GOOD, "value": 20.0}], store)
    assert len(second.results) == 2


def test_a_partial_redelivery_is_accepted(store: FakeRawStore):
    """The realistic retry: the gateway resends a window that overlaps what already landed."""
    run([GOOD, {**GOOD, "value": 20.0}], store)
    second = run([{**GOOD, "value": 20.0}, {**GOOD, "value": 30.0}], store)
    assert second.accepted_count == 2


def test_a_redelivered_batch_containing_a_bad_reading_behaves_identically(store: FakeRawStore):
    """A retry must not change the verdict on the readings it carries.

    If the second attempt reported different results from the first, a gateway could not tell a
    genuine data problem from an artefact of having retried.
    """
    first = run([GOOD, BAD_VALUE, GOOD], store)
    second = run([GOOD, BAD_VALUE, GOOD], store)
    assert [r.accepted for r in first.results] == [r.accepted for r in second.results]
    assert [r.reason for r in first.results] == [r.reason for r in second.results]


def test_each_attempt_gets_its_own_batch_id(store: FakeRawStore):
    """So the two attempts are distinguishable in the audit trail.

    A stable content-derived id would collapse them, and then a support investigation could not
    tell one delivery from two.
    """
    first = run([GOOD], store)
    second = run([GOOD], store)
    assert first.batch_id != second.batch_id


# ------------------------------------------------- the append log is not corrupted (P405) ---
def test_a_redelivery_appends_rather_than_replaces(store: FakeRawStore):
    run([GOOD], store)
    run([GOOD], store)
    assert store.count() == 2


def test_the_first_delivery_survives_the_second(store: FakeRawStore):
    first_rows = None
    run([GOOD], store)
    first_rows = store.rows
    run([GOOD], store)
    assert store.rows[: len(first_rows)] == first_rows


def test_repeated_redelivery_leaves_a_complete_history(store: FakeRawStore):
    for _ in range(5):
        run([GOOD], store)
    assert store.count() == 5
    assert len(store.for_sensor("S_OURS")) == 5


def test_the_accepted_count_still_matches_what_was_stored_on_a_retry(store: FakeRawStore):
    """The count must not start describing intent once duplicates are in play."""
    run([GOOD, BAD_VALUE], store)
    before = store.count()
    second = run([GOOD, BAD_VALUE], store)
    assert second.accepted_count == store.count() - before


def test_a_rejected_reading_does_not_accumulate_on_retry(store: FakeRawStore):
    """A retry of a bad reading stores nothing, however many times it arrives."""
    for _ in range(4):
        run([BAD_VALUE], store)
    assert store.count() == 0


# ------------------------------------- there is no such thing as a duplicate rejection ---
def test_the_closed_reason_set_has_no_duplicate_member():
    """Structural. If the reason existed, some call site would eventually emit it."""
    for escape_hatch in ("DUPLICATE", "ALREADY_SEEN", "REDELIVERED", "REPLAY", "CONFLICT",
                         "ALREADY_STORED"):
        assert not hasattr(RejectionReason, escape_hatch), (
            f"{escape_hatch} would make a normal retry look like a fault"
        )


def test_no_guidance_tells_a_gateway_not_to_resend():
    """A retry is the correct behaviour for an unacknowledged batch.

    The one place "do not re-send" appears is the cross-bridge reason (P404), which forbids
    re-sending under a *different key* — a tenancy rule, not a retry rule.
    """
    for reason, text in REASON_GUIDANCE.items():
        if reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE:
            continue
        blob = text.lower()
        assert "do not resend" not in blob
        assert "do not re-send" not in blob


def test_the_ingest_path_requires_no_idempotency_key():
    """Correctness must not depend on the gateway's firmware supplying one correctly."""
    import api.ingest.batch as batch_mod
    import api.ingest.processor as proc_mod

    for mod in (batch_mod, proc_mod):
        src = inspect.getsource(mod).lower()
        for banned in ("idempotency_key", "idempotency-key", "request_id", "dedupe_key",
                       "nonce"):
            assert banned not in src, f"{mod.__name__} expects a caller-supplied {banned}"


def test_an_unknown_extra_idempotency_field_is_simply_ignored(store: FakeRawStore):
    """A gateway that sends one anyway must not be penalised for it."""
    outcome = run([{**GOOD, "idempotency_key": "abc-123"}], store)
    assert outcome.accepted_count == 1


def test_the_ingest_path_computes_no_content_hash():
    """Hashing a reading to spot a repeat would make the boundary decide which arrival was
    real — a judgment, and the DCA's to make (Principle III)."""
    import api.ingest.processor as mod

    src = inspect.getsource(mod).lower()
    for banned in ("hashlib", "sha256", "md5", "content_hash", "fingerprint", "digest"):
        assert banned not in src


def test_a_sensor_reporting_the_same_value_twice_is_not_a_duplicate(store: FakeRawStore):
    """The reason content-hashing is wrong, not merely unnecessary.

    A vibration sensor at rest reports the same value repeatedly. Those readings are distinct
    measurements, and collapsing them would erase evidence that the sensor was reporting at all.
    """
    run([GOOD, GOOD, GOOD], store)
    assert store.count() == 3


def test_two_identical_readings_in_one_batch_both_land(store: FakeRawStore):
    outcome = run([GOOD, GOOD], store)
    assert outcome.accepted_count == 2
    assert store.count() == 2
