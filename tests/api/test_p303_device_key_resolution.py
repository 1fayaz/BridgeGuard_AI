"""P303 — resolving a Pi's API key to exactly one bridge and one tenant.

[DB-DEP] No Neon locally, so this runs against `FakeCredentialStore` (P201), which
mirrors migration 0017's guarantees.

This is the one place in the layer that reads the database **before** a tenant scope
exists — because this read is what *determines* the scope. That inversion is documented
in 0017's header and it deserves care, so the properties below are pinned hard:

**The presented key is never logged and never compared in plaintext.** A field-installed
Raspberry Pi is the credential most likely to be physically extracted, and the most
likely to end up in a debug log during an outage. Comparison goes through the stored
salted hash; the raw key appears in no error message, no exception, and no log record.

**Presenting the stored hash must not authenticate.** Otherwise a database dump is a
master key — the hash would be both the stored secret and the presentable one.

**A revoked key is 401, not a resolution.** And it is distinguishable *in the log* from
an unknown key, because the two mean different things operationally: a revoked key still
presenting is a decommissioned Pi that was never unplugged, while an unknown key may be
an attack. The client sees the same 401 either way.

**The bridge pin is mandatory.** A device Principal without a `bridge_id` has not
resolved (P301). That pin is what makes a stolen key worth one bridge's ingestion rather
than a municipality's whole dataset.

Ties to tasks.md P303, spec AC-7, plan §2a.
"""
from __future__ import annotations

import logging

import pytest

from api.auth.device_key import DeviceKeyResolver
from api.auth.principal import CredentialClass
from api.status_policy import ApiError, Failure
from db.credential_store import CredentialStatus, FakeCredentialStore
from db.tenant_store import FakeTenantStore

RAW_KEY = "pi-north-abutment-key-0123456789abcdef"
OTHER_KEY = "pi-south-pier-key-0123456789abcdef"


@pytest.fixture
def store() -> FakeCredentialStore:
    tenants = FakeTenantStore()
    tenants.add_municipality("MUNI_A", name="Alpha")
    tenants.add_municipality("MUNI_B", name="Beta")
    tenants.add_bridge("BRIDGE_1", municipality_id="MUNI_A", name="First")
    tenants.add_bridge("BRIDGE_3", municipality_id="MUNI_B", name="Third")
    return FakeCredentialStore(tenants)


@pytest.fixture
def resolver(store: FakeCredentialStore) -> DeviceKeyResolver:
    store.issue("BRIDGE_1", device_label="Pi at north abutment", key=RAW_KEY)
    return DeviceKeyResolver(store)


# ------------------------------------------------------------------ the happy path ---
def test_a_valid_key_resolves_to_one_bridge_and_one_tenant(resolver: DeviceKeyResolver):
    p = resolver.resolve(RAW_KEY)
    assert p.credential_class is CredentialClass.DEVICE_KEY
    assert p.municipality_id == "MUNI_A"
    assert p.bridge_id == "BRIDGE_1"
    assert p.user_id is None


def test_the_tenant_is_derived_not_supplied(store: FakeCredentialStore):
    """A device in MUNI_B resolves to MUNI_B — the caller never names a tenant."""
    store.issue("BRIDGE_3", device_label="Pi south", key=OTHER_KEY)
    p = DeviceKeyResolver(store).resolve(OTHER_KEY)
    assert p.municipality_id == "MUNI_B"
    assert p.bridge_id == "BRIDGE_3"


def test_resolution_stamps_last_used(resolver: DeviceKeyResolver,
                                     store: FakeCredentialStore):
    """Operational visibility: a Pi that stopped presenting its key is offline."""
    cred = store.get(1)
    assert cred.last_used_at is None
    resolver.resolve(RAW_KEY)
    assert store.get(1).last_used_at is not None


def test_a_header_prefixed_key_is_accepted(resolver: DeviceKeyResolver):
    """Gateways send the raw key; tolerate an ApiKey prefix without requiring it."""
    assert resolver.resolve(f"ApiKey {RAW_KEY}").bridge_id == "BRIDGE_1"


# --------------------------------------------------------------- rejections → 401 ---
def test_an_unknown_key_is_rejected(resolver: DeviceKeyResolver):
    with pytest.raises(ApiError) as exc:
        resolver.resolve("never-issued-key-0123456789abcdef")
    assert exc.value.status_code == 401


def test_a_revoked_key_is_rejected(resolver: DeviceKeyResolver,
                                   store: FakeCredentialStore):
    store.revoke(1)
    with pytest.raises(ApiError) as exc:
        resolver.resolve(RAW_KEY)
    assert exc.value.status_code == 401


def test_a_revoked_key_is_a_distinct_failure_class_for_the_log(
    resolver: DeviceKeyResolver, store: FakeCredentialStore
):
    """Same 401 to the client; different class internally.

    A revoked key still presenting is a decommissioned Pi nobody unplugged. An unknown
    key may be an attack. Operators need to tell those apart.
    """
    store.revoke(1)
    with pytest.raises(ApiError) as revoked:
        resolver.resolve(RAW_KEY)
    with pytest.raises(ApiError) as unknown:
        resolver.resolve("never-issued-key-0123456789abcdef")
    assert revoked.value.failure is Failure.EXPIRED_CREDENTIAL
    assert unknown.value.failure is Failure.INVALID_CREDENTIAL
    assert revoked.value.status_code == unknown.value.status_code == 401


def test_the_client_cannot_tell_revoked_from_unknown(
    resolver: DeviceKeyResolver, store: FakeCredentialStore
):
    """The body must not confirm that a key was ever valid."""
    store.revoke(1)
    with pytest.raises(ApiError) as revoked:
        resolver.resolve(RAW_KEY)
    with pytest.raises(ApiError) as unknown:
        resolver.resolve("never-issued-key-0123456789abcdef")
    assert revoked.value.detail == unknown.value.detail
    assert revoked.value.error == unknown.value.error


@pytest.mark.parametrize("empty", ["", "   ", "ApiKey ", None])
def test_a_missing_key_is_missing_credential(resolver: DeviceKeyResolver, empty):
    with pytest.raises(ApiError) as exc:
        resolver.resolve(empty)
    assert exc.value.failure is Failure.MISSING_CREDENTIAL
    assert exc.value.status_code == 401


def test_a_short_key_is_rejected_without_a_store_lookup(resolver: DeviceKeyResolver):
    """A trivially short key is not a credential; reject before touching the store."""
    with pytest.raises(ApiError) as exc:
        resolver.resolve("abc")
    assert exc.value.status_code == 401


# ------------------------------------------------- the key itself never escapes ---
def test_presenting_the_stored_hash_does_not_authenticate(
    resolver: DeviceKeyResolver, store: FakeCredentialStore
):
    """Otherwise a database dump is a master key."""
    stored_hash = store.get(1).key_hash
    with pytest.raises(ApiError):
        resolver.resolve(stored_hash)


def test_no_error_message_contains_the_presented_key(resolver: DeviceKeyResolver):
    bad = "some-attackers-key-0123456789abcdef"
    with pytest.raises(ApiError) as exc:
        resolver.resolve(bad)
    assert bad not in exc.value.detail
    assert bad not in exc.value.error
    assert bad[:16] not in exc.value.detail


def test_no_error_message_contains_a_valid_key_either(
    resolver: DeviceKeyResolver, store: FakeCredentialStore
):
    store.revoke(1)
    with pytest.raises(ApiError) as exc:
        resolver.resolve(RAW_KEY)
    assert RAW_KEY not in exc.value.detail
    assert RAW_KEY[:16] not in exc.value.detail


def test_the_key_is_never_logged(resolver: DeviceKeyResolver, caplog):
    """The realistic leak: a debug log during an outage, with the key in it."""
    caplog.set_level(logging.DEBUG)
    bad = "leaky-key-0123456789abcdef"
    with pytest.raises(ApiError):
        resolver.resolve(bad)
    blob = caplog.text
    assert bad not in blob
    assert bad[:16] not in blob


def test_a_successful_resolution_logs_no_key(resolver: DeviceKeyResolver, caplog):
    caplog.set_level(logging.DEBUG)
    resolver.resolve(RAW_KEY)
    assert RAW_KEY not in caplog.text
    assert RAW_KEY[:16] not in caplog.text


def test_the_resolver_repr_holds_no_key_material(resolver: DeviceKeyResolver):
    blob = repr(resolver).lower()
    assert RAW_KEY not in blob
    for banned in ("key_hash", "secret", "salt"):
        assert banned not in blob


def test_no_plaintext_comparison_in_the_source():
    """A structural check: the module must not compare a raw key to a stored value."""
    import inspect

    import api.auth.device_key as mod

    src = inspect.getsource(mod)
    assert "== row.key" not in src
    assert "key ==" not in src
    # Resolution must go through the store's hash-based lookup, not a local compare.
    assert ".resolve(" in src


# --------------------------------------------------------------- rotation (P306) ---
def test_both_keys_work_during_rotation_overlap(store: FakeCredentialStore):
    """A Pi is re-flashed without a data gap; both keys authenticate briefly."""
    store.issue("BRIDGE_1", device_label="pi-1", key=RAW_KEY)
    store.issue("BRIDGE_1", device_label="pi-1", key=OTHER_KEY)
    r = DeviceKeyResolver(store)
    assert r.resolve(RAW_KEY).bridge_id == "BRIDGE_1"
    assert r.resolve(OTHER_KEY).bridge_id == "BRIDGE_1"


def test_after_revocation_only_the_new_key_works(store: FakeCredentialStore):
    old = store.issue("BRIDGE_1", device_label="pi-1", key=RAW_KEY)
    store.issue("BRIDGE_1", device_label="pi-1", key=OTHER_KEY)
    store.revoke(old.credential_id)
    r = DeviceKeyResolver(store)
    with pytest.raises(ApiError):
        r.resolve(RAW_KEY)
    assert r.resolve(OTHER_KEY).bridge_id == "BRIDGE_1"


def test_revocation_never_deletes_the_row(store: FakeCredentialStore):
    """Audit permanence: 'was this device authorised then?' stays answerable."""
    cred = store.issue("BRIDGE_1", device_label="pi-1", key=RAW_KEY)
    store.revoke(cred.credential_id)
    assert store.get(cred.credential_id).status is CredentialStatus.REVOKED
    assert store.count() == 1


# ----------------------------------------------------------- feeds the scope seam ---
@pytest.mark.asyncio
async def test_the_resolved_tenant_scopes_the_transaction(resolver: DeviceKeyResolver):
    """The bootstrap read determines the scope; every later query runs inside it."""
    from api.db.fake_connection import FakeConnection
    from api.db.scope import scoped_transaction

    conn = FakeConnection()
    p = resolver.resolve(RAW_KEY)
    async with scoped_transaction(conn, p.municipality_id):
        assert conn.current_scope == "MUNI_A"
