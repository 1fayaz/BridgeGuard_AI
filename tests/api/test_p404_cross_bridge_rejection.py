"""P404 — a reading for someone else's sensor is rejected per-reading, never re-attributed.

This is the ingest-layer face of AC-2, and the temptation it guards against is the helpful one.
A Pi sends a batch under BRIDGE_1's key and one reading names a sensor that lives on BRIDGE_2.
The obliging thing to do is look the sensor up, see which bridge it really belongs to, and file
the reading there — the data is real, after all, and it would otherwise be lost.

That is the worst available outcome. The credential is the only statement of tenancy we have
(INV-3: a supplied id is never a grant). A gateway that can name a sensor id can then write into
whatever tenant owns it, which means one municipality's compromised or misconfigured Pi becomes
a write path into another municipality's data — and the row would look perfectly legitimate
afterwards, correctly attributed and consistent, with nothing to distinguish it from a real
reading. No alarm, no audit trail, no way back.

So the answer is a plain per-reading rejection. **Not** an HTTP error (that would cost the
batch's other readings, P403), **not** a silent drop (P402: the gateway must be able to act),
and **not** a re-attribution. Three distinct reasons, because they call for three different
human actions:

- `UNKNOWN_SENSOR` — nobody has provisioned this. An operator must onboard it.
- `SENSOR_NOT_ON_THIS_BRIDGE` — the sensor is real and belongs elsewhere. Someone has the wrong
  key on the wrong Pi, or the wrong sensor id in a config file.
- `UNIT_MISMATCH` — the sensor is right but the reading is in the wrong unit. Refused rather
  than converted: converting would put a number in raw storage that no sensor ever reported
  (Principle II).

One detail that reads as pedantic and is the whole point: the rejection reason must not tell
the gateway *which* bridge the sensor actually belongs to. That would answer a question the
caller has no standing to ask, and turn a rejection into a tenancy-enumeration oracle.

Ties to tasks.md P404, spec AC-1 + AC-2 + §1, plan §4. [DB-DEP] — the ownership chain is the
in-memory FakeTenantStore; the live equivalent is the 0014/0015 FKs plus 0016 RLS.
"""
from __future__ import annotations

import inspect

import pytest

from api.audit import FakeAuditLog
from api.auth.principal import Principal
from api.ingest.batch import parse_batch
from api.ingest.ownership import SensorRegistry, check_ownership
from api.ingest.processor import process_batch
from api.ingest.raw_store import FakeRawStore
from api.ingest.reasons import RejectionReason
from db.tenant_store import FakeTenantStore

GOOD = {
    "sensor_id": "S_OURS",
    "sensor_type": "strain",
    "value": 12.5,
    "unit": "microstrain",
    "sensor_time": "2026-08-04T10:00:00Z",
}


@pytest.fixture
def tenants() -> FakeTenantStore:
    """Two municipalities, one bridge each, one sensor each. The minimum shape that can be
    got wrong: our sensor, and a real sensor that is not ours."""
    store = FakeTenantStore()
    store.add_municipality("MUNI_A", name="Alpha")
    store.add_municipality("MUNI_B", name="Beta")
    store.add_bridge("BRIDGE_1", municipality_id="MUNI_A", name="Ours")
    store.add_bridge("BRIDGE_2", municipality_id="MUNI_B", name="Theirs")
    store.add_sensor(
        "S_OURS", bridge_id="BRIDGE_1", sensor_type="strain",
        config={"unit": "microstrain"},
    )
    store.add_sensor(
        "S_THEIRS", bridge_id="BRIDGE_2", sensor_type="strain",
        config={"unit": "microstrain"},
    )
    return store


@pytest.fixture
def registry(tenants: FakeTenantStore) -> SensorRegistry:
    return SensorRegistry(tenants)


@pytest.fixture
def store() -> FakeRawStore:
    return FakeRawStore()


def run(payloads: list[dict], store: FakeRawStore, registry: SensorRegistry):
    return process_batch(
        parse_batch({"readings": payloads}),
        store=store,
        principal=Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1"),
        registry=registry,
        audit=FakeAuditLog(),
    )


# ------------------------------------------------------------- the ownership check itself ---
def test_our_own_sensor_passes(registry: SensorRegistry):
    assert check_ownership(GOOD["sensor_id"], GOOD["unit"], registry, bridge_id="BRIDGE_1") is None


def test_an_unprovisioned_sensor_is_unknown(registry: SensorRegistry):
    reason = check_ownership("S_NOBODY", "microstrain", registry, bridge_id="BRIDGE_1")
    assert reason is RejectionReason.UNKNOWN_SENSOR


def test_another_bridges_sensor_is_not_on_this_bridge(registry: SensorRegistry):
    """The headline case: a real sensor, the wrong key."""
    reason = check_ownership("S_THEIRS", "microstrain", registry, bridge_id="BRIDGE_1")
    assert reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE


def test_the_wrong_unit_on_our_own_sensor_is_a_mismatch(registry: SensorRegistry):
    reason = check_ownership("S_OURS", "millimetres", registry, bridge_id="BRIDGE_1")
    assert reason is RejectionReason.UNIT_MISMATCH


def test_unknown_beats_unit_mismatch(registry: SensorRegistry):
    """An unprovisioned sensor has no registered unit to disagree with; saying 'unit mismatch'
    would send an operator to fix a config file for a sensor that does not exist."""
    reason = check_ownership("S_NOBODY", "furlongs", registry, bridge_id="BRIDGE_1")
    assert reason is RejectionReason.UNKNOWN_SENSOR


def test_wrong_bridge_beats_unit_mismatch(registry: SensorRegistry):
    """Reporting the unit would confirm the sensor's registered unit — a detail about another
    tenant's equipment, disclosed to a caller with no standing to ask."""
    reason = check_ownership("S_THEIRS", "furlongs", registry, bridge_id="BRIDGE_1")
    assert reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE


def test_the_unit_comparison_ignores_surrounding_whitespace(registry: SensorRegistry):
    assert check_ownership("S_OURS", "  microstrain\n", registry, bridge_id="BRIDGE_1") is None


def test_the_unit_comparison_is_case_insensitive(registry: SensorRegistry):
    """A gateway sending 'Microstrain' is a formatting difference, not a wrong unit."""
    assert check_ownership("S_OURS", "MicroStrain", registry, bridge_id="BRIDGE_1") is None


def test_a_sensor_with_no_registered_unit_accepts_any_unit(registry: SensorRegistry,
                                                           tenants: FakeTenantStore):
    """Unit is per-sensor config (0014 `config` JSONB), and not every sensor has it set yet.
    An unset unit must not become a rejection — that would refuse readings from every sensor
    onboarded before the field existed."""
    tenants.add_sensor("S_NOUNIT", bridge_id="BRIDGE_1", sensor_type="tilt", config={})
    assert check_ownership("S_NOUNIT", "degrees", registry, bridge_id="BRIDGE_1") is None


def test_the_ownership_check_never_raises(registry: SensorRegistry):
    """One escaping exception here costs the whole batch — the P403 failure, relocated."""
    for sensor_id in ("", "   ", "S" * 5000, "S_OURS"):
        outcome = check_ownership(sensor_id, "microstrain", registry, bridge_id="BRIDGE_1")
        assert outcome is None or isinstance(outcome, RejectionReason)


def test_a_missing_bridge_scope_rejects_rather_than_passes(registry: SensorRegistry):
    """Fail closed: with no bridge to compare against, nothing can be shown to be ours."""
    reason = check_ownership("S_OURS", "microstrain", registry, bridge_id="")
    assert reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE


class _BrokenRoster:
    """A roster that cannot answer. Stands in for the live failure modes — a dropped Neon
    connection, a timeout, an RLS scope that was never set."""

    def has_sensor(self, sensor_id: str) -> bool:
        return True

    def bridge_of_sensor(self, sensor_id: str) -> str:
        raise RuntimeError("roster unavailable")

    def get_sensor(self, sensor_id: str):
        raise RuntimeError("roster unavailable")


def test_an_unresolvable_roster_rejects_rather_than_admits():
    """The direction of the failure is the whole point.

    If a lookup error meant "assume it's ours", then losing the sensor roster — a connection
    drop, a timeout, an unset RLS scope — would silently turn the ownership check off while
    ingest carried on returning 200s. Fail closed: unproven is refused.
    """
    reason = check_ownership(
        "S_OURS", "microstrain", SensorRegistry(_BrokenRoster()), bridge_id="BRIDGE_1"
    )
    assert reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE


def test_an_unresolvable_roster_writes_nothing(store: FakeRawStore):
    """And the refusal has to reach the store, not just the reason."""
    outcome = process_batch(
        parse_batch({"readings": [GOOD] * 3}),
        store=store,
        principal=Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1"),
        registry=SensorRegistry(_BrokenRoster()),
        audit=FakeAuditLog(),
    )
    assert outcome.accepted_count == 0
    assert store.count() == 0


def test_a_roster_failure_is_not_an_exception_out_of_the_batch(store: FakeRawStore):
    """Fail closed, but still per-reading: a roster outage must not raise past the boundary."""
    outcome = process_batch(
        parse_batch({"readings": [GOOD, GOOD]}),
        store=store,
        principal=Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1"),
        registry=SensorRegistry(_BrokenRoster()),
        audit=FakeAuditLog(),
    )
    assert len(outcome.results) == 2
    assert all(r.reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE for r in outcome.results)


# ------------------------------------------- rejected per-reading, not as an HTTP error ---
def test_a_cross_bridge_reading_is_not_an_http_error(store: FakeRawStore,
                                                     registry: SensorRegistry):
    """A 4xx would discard the batch's good readings — the failure P403 exists to prevent."""
    outcome = run([{**GOOD, "sensor_id": "S_THEIRS"}], store, registry)
    assert outcome.rejected_count == 1
    assert outcome.results[0].reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE


def test_the_rest_of_the_batch_still_processes(store: FakeRawStore, registry: SensorRegistry):
    """The acceptance criterion: one foreign sensor costs one reading, not the bridge."""
    outcome = run(
        [GOOD, {**GOOD, "sensor_id": "S_THEIRS"}, GOOD, {**GOOD, "sensor_id": "S_NOBODY"}, GOOD],
        store,
        registry,
    )
    assert outcome.accepted_count == 3
    assert outcome.rejected_count == 2
    assert store.count() == 3


def test_every_reading_still_gets_a_positional_result(store: FakeRawStore,
                                                      registry: SensorRegistry):
    outcome = run(
        [GOOD, {**GOOD, "sensor_id": "S_THEIRS"}, {**GOOD, "sensor_id": "S_NOBODY"}],
        store,
        registry,
    )
    assert [r.index for r in outcome.results] == [0, 1, 2]
    assert [r.accepted for r in outcome.results] == [True, False, False]


def test_the_three_ownership_reasons_all_reach_the_response(store: FakeRawStore,
                                                           registry: SensorRegistry):
    outcome = run(
        [
            {**GOOD, "sensor_id": "S_NOBODY"},
            {**GOOD, "sensor_id": "S_THEIRS"},
            {**GOOD, "unit": "furlongs"},
        ],
        store,
        registry,
    )
    assert [r.reason for r in outcome.results] == [
        RejectionReason.UNKNOWN_SENSOR,
        RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE,
        RejectionReason.UNIT_MISMATCH,
    ]


def test_a_shape_failure_is_reported_before_ownership_is_consulted(store: FakeRawStore,
                                                                  registry: SensorRegistry):
    """A reading with no usable sensor_id cannot be looked up at all; reporting 'unknown
    sensor' for a blank id would misdirect the operator to the provisioning system."""
    outcome = run([{**GOOD, "sensor_id": "   ", "value": "twelve"}], store, registry)
    assert outcome.results[0].reason is RejectionReason.MISSING_FIELD


# ------------------------------------------------------- NOT silently re-attributed (AC-2) ---
def test_no_row_is_written_under_the_other_bridge(store: FakeRawStore,
                                                  registry: SensorRegistry):
    """The invariant: the reading is refused, not filed somewhere else."""
    run([{**GOOD, "sensor_id": "S_THEIRS"}], store, registry)
    assert store.count() == 0


def test_no_row_anywhere_names_the_other_tenant(store: FakeRawStore, registry: SensorRegistry):
    """Even in a batch that partly succeeds, nothing lands under MUNI_B or BRIDGE_2."""
    run([GOOD, {**GOOD, "sensor_id": "S_THEIRS"}, GOOD], store, registry)
    for row in store.rows:
        assert row["municipality_id"] == "MUNI_A"
        assert row["bridge_id"] == "BRIDGE_1"


def test_an_accepted_row_is_stamped_from_the_credential_not_the_payload(
    store: FakeRawStore, registry: SensorRegistry
):
    """INV-3: tenancy comes from the key. A payload that names a tenant is not believed."""
    run([{**GOOD, "municipality_id": "MUNI_B", "bridge_id": "BRIDGE_2"}], store, registry)
    assert store.count() == 1
    assert store.rows[0]["municipality_id"] == "MUNI_A"
    assert store.rows[0]["bridge_id"] == "BRIDGE_1"


def test_the_foreign_sensor_is_never_looked_up_into_a_write(store: FakeRawStore,
                                                           registry: SensorRegistry):
    run([{**GOOD, "sensor_id": "S_THEIRS"}] * 5, store, registry)
    assert store.for_sensor("S_THEIRS") == []


def test_the_processor_never_resolves_a_readings_own_tenancy():
    """A structural guard: the moment the ingest path can resolve a sensor to *its* tenant, the
    re-attribution bug is one plausible-looking line away. The check may ask 'is this sensor on
    my bridge?' — never 'whose is it?'."""
    import api.ingest.ownership as own
    import api.ingest.processor as proc

    for mod in (own, proc):
        src = inspect.getsource(mod)
        for banned in ("municipality_of_sensor", "attribute_reading", "ownership_chain"):
            assert banned not in src, f"{mod.__name__} resolves a reading's own tenancy: {banned}"


# -------------------------------------------------- the rejection is not an oracle (INV-3) ---
def test_the_reason_does_not_name_the_owning_bridge(store: FakeRawStore,
                                                    registry: SensorRegistry):
    """A rejection that says 'that's on BRIDGE_2' enumerates another tenant's estate."""
    outcome = run([{**GOOD, "sensor_id": "S_THEIRS"}], store, registry)
    blob = repr(outcome.results[0]).lower()
    assert "bridge_2" not in blob
    assert "muni_b" not in blob


def test_the_reason_values_are_identical_regardless_of_who_owns_the_sensor(
    store: FakeRawStore, registry: SensorRegistry, tenants: FakeTenantStore
):
    """Two foreign sensors on two different bridges must be indistinguishable in the response,
    so a caller cannot map the estate by probing ids."""
    tenants.add_bridge("BRIDGE_3", municipality_id="MUNI_B", name="Third")
    tenants.add_sensor("S_THIRD", bridge_id="BRIDGE_3", sensor_type="strain", config={})
    outcome = run(
        [{**GOOD, "sensor_id": "S_THEIRS"}, {**GOOD, "sensor_id": "S_THIRD"}], store, registry
    )
    first, second = outcome.results
    assert first.reason is second.reason is RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE


def test_the_guidance_for_the_cross_bridge_reason_stays_generic():
    """P402 already forbids re-sending elsewhere; assert it discloses no owner either."""
    from api.ingest.reasons import REASON_GUIDANCE

    text = REASON_GUIDANCE[RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE].lower()
    for banned in ("bridge_1", "bridge_2", "muni_", "which bridge"):
        assert banned not in text


# ---------------------------------------------------------------- structural constraints ---
def test_the_ownership_module_makes_no_verdict_of_its_own():
    import api.ingest.ownership as mod

    src = inspect.getsource(mod).lower()
    for banned in ("interpolat", "def clean", "quality_score", "is_anomal", "def convert"):
        assert banned not in src


def test_the_ownership_module_imports_no_agent():
    import api.ingest.ownership as mod

    src = inspect.getsource(mod)
    assert "from agents" not in src
    assert "import agents" not in src


def test_the_ownership_check_cannot_be_skipped_by_omission(store: FakeRawStore):
    """`registry` has no default on purpose.

    An optional one would make "skip the ownership check" the behaviour a forgotten argument
    produces — so a wiring omission at the router would silently disable AC-2 while every test
    in this file still passed.
    """
    with pytest.raises(TypeError):
        process_batch(
            parse_batch({"readings": [GOOD]}),
            store=store,
            principal=Principal.for_device(
                municipality_id="MUNI_A", bridge_id="BRIDGE_1"
            ),
            audit=FakeAuditLog(),
        )


def test_the_registry_offers_no_write_path():
    """Ingest reads the sensor roster; provisioning is an operator action elsewhere."""
    for banned in ("add_sensor", "add_bridge", "add_municipality", "delete", "update"):
        assert not hasattr(SensorRegistry, banned), f"SensorRegistry exposes {banned}"
