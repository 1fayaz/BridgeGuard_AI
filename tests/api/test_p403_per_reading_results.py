"""P403 — a mixed batch returns one result per reading, and the good ones are still stored.

The failure this task exists to prevent is the reasonable-looking one: a batch arrives, one
reading is malformed, the endpoint returns 422, and the gateway retries the whole batch. It
retries forever, because the bad reading never gets better. Meanwhile the other 49 readings
in that batch — perfectly good measurements from a bridge under load — are never stored, and
nothing anywhere records that they were lost. The Pi reports success once the operator
finally deletes the batch.

So the contract is per-reading (AC-1): N results for N readings, positionally indexed, and
the N−k valid readings are appended regardless of the k that failed. One broken sensor
degrades one series, not the bridge.

Two details that look cosmetic and are not:

**Results are positional.** The gateway correlates them against what it sent by index, so a
result set that is reordered, deduplicated, or filtered to failures-only breaks that
correlation silently — the gateway would attribute a rejection to the wrong reading.

**`accepted_count` is derived, never reported separately.** A count that disagrees with the
results array is worse than no count, because a gateway that trusts the summary would believe
readings were stored that were not.

Ties to tasks.md P403, spec AC-1 + §1, plan §4.
"""
from __future__ import annotations

import inspect

import pytest

from api.audit import FakeAuditLog
from api.auth.principal import Principal
from api.ingest.batch import parse_batch
from api.ingest.ownership import SensorRegistry
from api.ingest.processor import IngestOutcome, ReadingResult, process_batch
from api.ingest.reasons import RejectionReason
from api.ingest.raw_store import FakeRawStore

GOOD = {
    "sensor_id": "SENSOR_1",
    "sensor_type": "strain",
    "value": 12.5,
    "unit": "microstrain",
    "sensor_time": "2026-08-03T10:00:00Z",
}
BAD_VALUE = {**GOOD, "value": "twelve"}
BAD_TIME = {**GOOD, "sensor_time": "not-a-time"}
BAD_FIELD = {k: v for k, v in GOOD.items() if k != "unit"}


@pytest.fixture
def store() -> FakeRawStore:
    return FakeRawStore()


class _EverySensorOnOurBridge:
    """Roster stand-in that onboards any sensor id on demand, all on BRIDGE_1.

    P403 is about the per-reading result contract, so ownership must not be the thing failing
    here — the cross-bridge rejection has its own file (P404) with a real two-tenant roster.
    Wrapped in the real `SensorRegistry` so the production lookup code stays in the path.
    """

    def has_sensor(self, sensor_id: str) -> bool:
        return True

    def bridge_of_sensor(self, sensor_id: str) -> str:
        return "BRIDGE_1"

    def get_sensor(self, sensor_id: str):
        return _Unconfigured()


class _Unconfigured:
    """No registered unit, so the unit check never objects."""

    config: dict = {}


def run(payloads: list[dict], store: FakeRawStore) -> IngestOutcome:
    return process_batch(
        parse_batch({"readings": payloads}),
        store=store,
        principal=Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1"),
        registry=SensorRegistry(_EverySensorOnOurBridge()),
        audit=FakeAuditLog(),
    )


# ------------------------------------------------------------ N results for N readings ---
def test_a_batch_of_n_returns_exactly_n_results(store: FakeRawStore):
    outcome = run([GOOD, BAD_VALUE, GOOD, BAD_TIME, GOOD], store)
    assert len(outcome.results) == 5


def test_an_all_good_batch_returns_a_result_per_reading(store: FakeRawStore):
    outcome = run([GOOD] * 3, store)
    assert len(outcome.results) == 3
    assert all(r.accepted for r in outcome.results)


def test_an_all_bad_batch_still_returns_a_result_per_reading(store: FakeRawStore):
    outcome = run([BAD_VALUE, BAD_TIME, BAD_FIELD], store)
    assert len(outcome.results) == 3
    assert not any(r.accepted for r in outcome.results)


def test_an_empty_batch_returns_no_results(store: FakeRawStore):
    outcome = run([], store)
    assert outcome.results == []
    assert outcome.accepted_count == 0


def test_results_are_positionally_indexed(store: FakeRawStore):
    """The gateway correlates by index; a gap or reorder misattributes a rejection."""
    outcome = run([GOOD, BAD_VALUE, GOOD, BAD_TIME], store)
    assert [r.index for r in outcome.results] == [0, 1, 2, 3]


def test_failures_are_not_filtered_out_of_the_results(store: FakeRawStore):
    """A failures-only or successes-only array breaks positional correlation."""
    outcome = run([BAD_VALUE, GOOD, BAD_TIME], store)
    assert len(outcome.results) == 3
    assert [r.accepted for r in outcome.results] == [False, True, False]


def test_each_result_names_its_sensor(store: FakeRawStore):
    """So a gateway can act without holding the request body it sent."""
    outcome = run([{**GOOD, "sensor_id": "S_A"}, {**GOOD, "sensor_id": "S_B"}], store)
    assert [r.sensor_id for r in outcome.results] == ["S_A", "S_B"]


def test_the_failures_name_the_right_indices(store: FakeRawStore):
    """The headline check: k failures at the positions they actually occupied."""
    outcome = run([GOOD, BAD_VALUE, GOOD, GOOD, BAD_TIME, GOOD], store)
    rejected = [r.index for r in outcome.results if not r.accepted]
    assert rejected == [1, 4]


def test_each_failure_carries_the_right_reason(store: FakeRawStore):
    outcome = run([BAD_VALUE, BAD_TIME, BAD_FIELD], store)
    assert [r.reason for r in outcome.results] == [
        RejectionReason.NON_NUMERIC_VALUE,
        RejectionReason.MALFORMED_TIMESTAMP,
        RejectionReason.MISSING_FIELD,
    ]


def test_an_accepted_result_carries_no_reason(store: FakeRawStore):
    """A reason on an accepted reading would read as a warning the gateway must handle."""
    outcome = run([GOOD], store)
    assert outcome.results[0].reason is None


def test_a_rejected_result_always_carries_a_reason(store: FakeRawStore):
    """A bare `accepted: false` gives the gateway nothing to act on."""
    outcome = run([BAD_VALUE, BAD_TIME, BAD_FIELD], store)
    for r in outcome.results:
        assert r.reason is not None
        assert r.reason in set(RejectionReason)


# ------------------------------------------- the N-k valid readings are still appended ---
def test_the_valid_readings_in_a_mixed_batch_are_appended(store: FakeRawStore):
    """The point of the whole task: one bad sensor must not blind the bridge."""
    run([GOOD, BAD_VALUE, GOOD, BAD_TIME, GOOD], store)
    assert store.count() == 3


def test_rejected_readings_are_not_appended(store: FakeRawStore):
    run([BAD_VALUE, BAD_TIME, BAD_FIELD], store)
    assert store.count() == 0


def test_the_appended_rows_are_the_good_ones(store: FakeRawStore):
    payloads = [
        {**GOOD, "sensor_id": "KEEP_1"},
        {**BAD_VALUE, "sensor_id": "DROP_1"},
        {**GOOD, "sensor_id": "KEEP_2"},
    ]
    run(payloads, store)
    assert sorted(row["sensor_id"] for row in store.rows) == ["KEEP_1", "KEEP_2"]


def test_a_single_bad_reading_does_not_reject_its_neighbours(store: FakeRawStore):
    outcome = run([GOOD] * 20 + [BAD_VALUE] + [GOOD] * 20, store)
    assert outcome.accepted_count == 40
    assert store.count() == 40


def test_processing_does_not_stop_at_the_first_failure(store: FakeRawStore):
    """A `break` on the first rejection would silently drop everything after it."""
    outcome = run([BAD_VALUE, GOOD, GOOD, GOOD], store)
    assert outcome.accepted_count == 3
    assert len(outcome.results) == 4


# ------------------------------------------------------ counts are derived, not asserted ---
def test_the_counts_match_the_results_array(store: FakeRawStore):
    outcome = run([GOOD, BAD_VALUE, GOOD, BAD_TIME, GOOD], store)
    assert outcome.accepted_count == sum(1 for r in outcome.results if r.accepted)
    assert outcome.rejected_count == sum(1 for r in outcome.results if not r.accepted)


def test_the_counts_sum_to_the_batch_size(store: FakeRawStore):
    """A gateway that sums these and gets less than it sent has lost readings unnoticed."""
    outcome = run([GOOD, BAD_VALUE, GOOD, BAD_TIME], store)
    assert outcome.accepted_count + outcome.rejected_count == 4


def test_the_accepted_count_matches_what_was_actually_stored(store: FakeRawStore):
    """The count must reflect the append, not the intention to append."""
    outcome = run([GOOD, BAD_VALUE, GOOD], store)
    assert outcome.accepted_count == store.count()


def test_the_counts_cannot_be_set_independently_of_the_results():
    """Derived properties, so a count can never contradict the array it summarises."""
    src = inspect.getsource(IngestOutcome)
    assert "def accepted_count" in src, "accepted_count must be derived from results"
    assert "def rejected_count" in src


# --------------------------------------------------- there is no batch-level verdict ---
def test_the_outcome_exposes_no_batch_level_pass_fail(store: FakeRawStore):
    """A batch-level `ok` invites a gateway to check it and ignore the per-reading array."""
    outcome = run([GOOD, BAD_VALUE], store)
    for banned in ("ok", "success", "valid", "passed", "status"):
        assert not hasattr(outcome, banned), f"IngestOutcome exposes a batch verdict: {banned}"


def test_a_mixed_batch_is_a_successful_call_not_an_error(store: FakeRawStore):
    """Per-reading rejections are not HTTP errors (plan §8). Nothing raises here."""
    outcome = run([GOOD, BAD_VALUE, BAD_TIME], store)
    assert isinstance(outcome, IngestOutcome)
    assert outcome.rejected_count == 2


def test_an_entirely_rejected_batch_still_does_not_raise(store: FakeRawStore):
    """Even 0 accepted is a successful call: the gateway learns why, per reading."""
    outcome = run([BAD_VALUE] * 3, store)
    assert outcome.accepted_count == 0
    assert len(outcome.results) == 3


def test_the_batch_carries_an_identifier(store: FakeRawStore):
    """spec §1 output: `batch_id`, so a gateway can correlate a retry with its first attempt."""
    outcome = run([GOOD], store)
    assert outcome.batch_id
    assert isinstance(outcome.batch_id, str)


def test_two_batches_get_different_identifiers(store: FakeRawStore):
    first = run([GOOD], store)
    second = run([GOOD], store)
    assert first.batch_id != second.batch_id


# -------------------------------------------------------------- no verdict, no leakage ---
def test_a_result_carries_no_validation_verdict(store: FakeRawStore):
    """`accepted` means durably appended, not valid (P407). Validity is the DCA's word."""
    outcome = run([GOOD], store)
    for banned in ("valid", "quality", "confidence", "anomaly", "flag", "severity"):
        assert not hasattr(outcome.results[0], banned), (
            f"a per-reading result must not carry {banned}"
        )


def test_a_result_names_no_tenant(store: FakeRawStore):
    """The gateway already knows its own scope; echoing it back leaks the tenancy model."""
    outcome = run([GOOD], store)
    blob = repr(outcome.results[0]).lower()
    assert "muni" not in blob


def test_the_processor_makes_no_verdict_of_its_own():
    import api.ingest.processor as mod

    src = inspect.getsource(mod).lower()
    for banned in ("interpolat", "def clean", "quality_score", "is_anomal"):
        assert banned not in src


def test_the_processor_imports_no_agent():
    import api.ingest.processor as mod

    src = inspect.getsource(mod)
    assert "from agents" not in src
    assert "import agents" not in src


def test_a_reading_result_is_immutable(store: FakeRawStore):
    """A result is a record of what happened; rewriting one would falsify the ack."""
    outcome = run([GOOD], store)
    with pytest.raises((AttributeError, TypeError, ValueError)):
        outcome.results[0].accepted = False  # type: ignore[misc]


def test_a_reading_result_reports_only_the_four_contract_fields(store: FakeRawStore):
    outcome = run([GOOD, BAD_VALUE], store)
    assert set(ReadingResult.model_fields) == {"index", "sensor_id", "accepted", "reason"}
