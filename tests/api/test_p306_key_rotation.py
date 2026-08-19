"""P306 — a Pi's key is rotated by appending a new row, never by overwriting the old one.

P201 and P303 already prove the *observable* half of this task: two keys authenticate
during the overlap window, and after revocation the old one is refused while the new one
works. Those tests are not repeated here. What they do **not** prove is the half the
acceptance criterion actually turns on — *"no key is ever overwritten in place and no row
is deleted."* Nothing so far stops `row.key_hash = new_hash`, and a store that rotated
that way would pass every existing test while quietly destroying evidence.

Why that matters more than it sounds. The credential row is the answer to a regulator's
question: *was the device that sent this reading authorised at the time?* An in-place key
overwrite leaves one row that claims to have always held the new key. Every reading the
old key authorised now traces to a credential that never existed when they arrived. The
data is intact and the audit trail is a lie — which is the worst of the two failure modes,
because nothing looks broken.

So rotation is modelled as an **operation**, not a convention: `rotate()` appends, and the
old row's key material is structurally immutable so a future contributor cannot rotate the
wrong way even by accident. The overlap is deliberate — a Pi is re-flashed by a person
standing on a bridge, and the window is what stops a failed re-flash from becoming a
sensor data gap.

Ties to tasks.md P306, plan §2a, migration 0018.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from api.auth.device_key import DeviceKeyResolver
from api.status_policy import ApiError
from db.credential_store import (
    CredentialStatus,
    DuplicateCredentialError,
    FakeCredentialStore,
    PlaintextKeyRejected,
    RevokedCredentialError,
    hash_key,
)
from db.tenant_store import FakeTenantStore

OLD_KEY = "old-key-0123456789abcdef"
NEW_KEY = "new-key-0123456789abcdef"
THIRD_KEY = "third-key-0123456789abcdef"

MIGRATION = Path("db/migrations/0018_device_credential_key_immutable.sql")


@pytest.fixture
def store() -> FakeCredentialStore:
    tenants = FakeTenantStore()
    tenants.add_municipality("MUNI_A", name="Alpha")
    tenants.add_municipality("MUNI_B", name="Beta")
    tenants.add_bridge("BRIDGE_1", municipality_id="MUNI_A", name="First")
    tenants.add_bridge("BRIDGE_2", municipality_id="MUNI_A", name="Second")
    tenants.add_bridge("BRIDGE_B1", municipality_id="MUNI_B", name="Beta First")
    return FakeCredentialStore(tenants)


@pytest.fixture
def rotated(store: FakeCredentialStore):
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    new = store.rotate(old.credential_id, new_key=NEW_KEY)
    return store, old, new


# --------------------------------------------------------- rotation appends a row ---
def test_rotation_appends_a_second_credential(rotated):
    store, old, new = rotated
    assert new.credential_id != old.credential_id
    assert store.count() == 2


def test_rotation_leaves_the_old_credential_active(rotated):
    """The overlap is the point: revoking here would strand a Pi mid-re-flash."""
    store, old, _ = rotated
    assert store.get(old.credential_id).status is CredentialStatus.ACTIVE
    assert store.get(old.credential_id).revoked_at is None


def test_the_new_credential_is_active(rotated):
    _, _, new = rotated
    assert new.status is CredentialStatus.ACTIVE
    assert new.revoked_at is None


def test_rotation_keeps_the_same_bridge_and_tenant(rotated):
    """A rotation replaces key material. It is not a re-assignment of the device."""
    _, old, new = rotated
    assert new.bridge_id == old.bridge_id
    assert new.municipality_id == old.municipality_id


def test_rotation_carries_the_operator_label_forward(rotated):
    _, old, new = rotated
    assert new.device_label == old.device_label


def test_repeated_rotation_keeps_every_row(store: FakeCredentialStore):
    """Three keys over a device's life means three rows, not one rewritten row."""
    first = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    second = store.rotate(first.credential_id, new_key=NEW_KEY)
    third = store.rotate(second.credential_id, new_key=THIRD_KEY)
    assert store.count() == 3
    assert len({first.credential_id, second.credential_id, third.credential_id}) == 3


# ------------------------------------------------------ the old key is not disturbed ---
def test_rotation_does_not_touch_the_old_key_hash(store: FakeCredentialStore):
    """The headline check. An overwrite here would rewrite history, not record it."""
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    hash_before = old.key_hash
    store.rotate(old.credential_id, new_key=NEW_KEY)
    assert store.get(old.credential_id).key_hash == hash_before


def test_the_old_key_still_resolves_to_its_own_row(store: FakeCredentialStore):
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    store.rotate(old.credential_id, new_key=NEW_KEY)
    assert store.resolve(OLD_KEY).credential_id == old.credential_id


def test_the_two_keys_resolve_to_different_rows(rotated):
    store, old, new = rotated
    assert store.resolve(OLD_KEY).credential_id == old.credential_id
    assert store.resolve(NEW_KEY).credential_id == new.credential_id


def test_the_new_row_holds_a_different_hash(rotated):
    _, old, new = rotated
    assert new.key_hash != old.key_hash


def test_the_stored_hash_is_not_the_raw_key(rotated):
    _, _, new = rotated
    assert NEW_KEY not in new.key_hash
    assert new.key_hash == hash_key(NEW_KEY, new.salt)


# --------------------------------------------- key material is structurally immutable ---
def test_a_key_hash_cannot_be_assigned_in_place(rotated):
    """Convention is not enough: the wrong rotation must be impossible, not discouraged."""
    store, old, _ = rotated
    row = store.get(old.credential_id)
    with pytest.raises(AttributeError):
        row.key_hash = hash_key(THIRD_KEY, row.salt)


def test_the_salt_cannot_be_reassigned(rotated):
    """Changing the salt silently invalidates the hash — same damage, subtler route."""
    store, old, _ = rotated
    row = store.get(old.credential_id)
    with pytest.raises(AttributeError):
        row.salt = "0" * 32


def test_the_identity_record_itself_is_frozen(rotated):
    """A read-only property is not enough: `row.identity.key_hash = x` must also raise.

    Without this the guard is one attribute hop deep, and a rotation that reached through
    `identity` would overwrite key material while every property-level test stayed green.
    """
    store, old, _ = rotated
    identity = store.get(old.credential_id).identity
    for field_name in ("key_hash", "salt", "credential_id", "bridge_id", "municipality_id"):
        with pytest.raises((AttributeError, TypeError)):
            setattr(identity, field_name, "tampered")


def test_the_identity_record_is_declared_frozen():
    """Stated structurally so removing `frozen=True` fails here, not silently."""
    from dataclasses import fields as dataclass_fields

    import db.credential_store as mod

    assert dataclass_fields(mod.CredentialIdentity), "CredentialIdentity must be a dataclass"
    assert mod.CredentialIdentity.__dataclass_params__.frozen, (
        "CredentialIdentity must be frozen — key material is not reassignable"
    )


@pytest.mark.parametrize("field", ["credential_id", "bridge_id", "municipality_id", "created_at"])
def test_credential_identity_is_immutable(rotated, field: str):
    """Re-pointing a live credential at another bridge is a tenancy hole, not a rotation."""
    store, old, _ = rotated
    row = store.get(old.credential_id)
    with pytest.raises(AttributeError):
        setattr(row, field, "MUNI_B")


@pytest.mark.parametrize("field", ["status", "revoked_at", "last_used_at"])
def test_lifecycle_fields_remain_writable(rotated, field: str):
    """Revocation and last-used are the two legitimate updates (0017 discipline 2)."""
    store, old, _ = rotated
    row = store.get(old.credential_id)
    setattr(row, field, getattr(row, field))  # must not raise


def test_the_store_exposes_no_in_place_key_replacement(store: FakeCredentialStore):
    for name in ("set_key", "replace_key", "update_key", "change_key", "overwrite_key"):
        assert not hasattr(store, name), f"FakeCredentialStore must not expose {name}()"


def test_the_store_still_exposes_no_delete(store: FakeCredentialStore):
    for name in ("delete", "remove", "purge", "drop"):
        assert not hasattr(store, name)


def test_rotate_never_deletes_a_row(store: FakeCredentialStore):
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    store.rotate(old.credential_id, new_key=NEW_KEY)
    store.revoke(old.credential_id)
    assert store.count() == 2, "revoking after rotation must not remove the old row"


# ------------------------------------------------------- closing the overlap window ---
def test_revoking_the_old_key_closes_the_window(rotated):
    store, old, _ = rotated
    store.revoke(old.credential_id)
    with pytest.raises(RevokedCredentialError):
        store.resolve(OLD_KEY)
    assert store.resolve(NEW_KEY).bridge_id == "BRIDGE_1"


def test_the_revoked_row_keeps_its_hash_and_gains_a_timestamp(rotated):
    store, old, _ = rotated
    hash_before = store.get(old.credential_id).key_hash
    store.revoke(old.credential_id)
    row = store.get(old.credential_id)
    assert row.key_hash == hash_before
    assert row.revoked_at is not None


def test_rotating_a_revoked_credential_is_refused(store: FakeCredentialStore):
    """You rotate a live key. Rotating a dead one would resurrect a retired device."""
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    store.revoke(old.credential_id)
    with pytest.raises(RevokedCredentialError):
        store.rotate(old.credential_id, new_key=NEW_KEY)


def test_only_the_new_key_is_active_after_revocation(rotated):
    store, old, new = rotated
    store.revoke(old.credential_id)
    active = store.active_for_municipality("MUNI_A")
    assert [c.credential_id for c in active] == [new.credential_id]


def test_both_keys_are_active_during_the_overlap(rotated):
    store, old, new = rotated
    active = {c.credential_id for c in store.active_for_municipality("MUNI_A")}
    assert active == {old.credential_id, new.credential_id}


# ------------------------------------------------------------ rotation input hygiene ---
def test_rotating_to_an_already_issued_key_is_refused(store: FakeCredentialStore):
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    store.issue("BRIDGE_2", device_label="pi-south", key=NEW_KEY)
    with pytest.raises(DuplicateCredentialError):
        store.rotate(old.credential_id, new_key=NEW_KEY)


def test_rotating_to_the_same_key_is_refused(store: FakeCredentialStore):
    """A no-op rotation would look like a completed rotation in an operator's log."""
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    with pytest.raises(DuplicateCredentialError):
        store.rotate(old.credential_id, new_key=OLD_KEY)


@pytest.mark.parametrize("bad", ["", "   ", "short"])
def test_rotating_to_a_weak_key_is_refused(store: FakeCredentialStore, bad: str):
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    with pytest.raises(PlaintextKeyRejected):
        store.rotate(old.credential_id, new_key=bad)


def test_a_refused_rotation_leaves_the_store_unchanged(store: FakeCredentialStore):
    """Fail closed: a half-applied rotation is worse than a refused one."""
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    with pytest.raises(PlaintextKeyRejected):
        store.rotate(old.credential_id, new_key="x")
    assert store.count() == 1
    assert store.get(old.credential_id).status is CredentialStatus.ACTIVE


def test_the_raw_key_is_not_retained_on_the_returned_row(rotated):
    _, _, new = rotated
    blob = repr(new)
    assert NEW_KEY not in blob


# ------------------------------------------------- rotation is invisible to the auth layer ---
def test_the_resolver_accepts_both_keys_during_the_overlap(rotated):
    """The auth layer needs no rotation awareness — that is the design working."""
    store, _, _ = rotated
    resolver = DeviceKeyResolver(store)
    assert resolver.resolve(OLD_KEY).bridge_id == "BRIDGE_1"
    assert resolver.resolve(NEW_KEY).bridge_id == "BRIDGE_1"


def test_the_resolver_refuses_the_old_key_after_revocation(rotated):
    store, old, _ = rotated
    store.revoke(old.credential_id)
    resolver = DeviceKeyResolver(store)
    with pytest.raises(ApiError) as exc:
        resolver.resolve(OLD_KEY)
    assert exc.value.status_code == 401
    assert resolver.resolve(NEW_KEY).bridge_id == "BRIDGE_1"


def test_a_rotated_key_never_resolves_into_another_tenant(store: FakeCredentialStore):
    old = store.issue("BRIDGE_1", device_label="pi-north", key=OLD_KEY)
    store.rotate(old.credential_id, new_key=NEW_KEY)
    resolver = DeviceKeyResolver(store)
    assert resolver.resolve(NEW_KEY).municipality_id == "MUNI_A"


# ------------------------------------------------------------------ structural scans ---
def test_nothing_in_the_api_layer_updates_a_key_hash():
    """An in-place overwrite anywhere in the boundary defeats the whole discipline."""
    offenders = []
    for path in Path("src/api").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for banned in ("set key_hash", "key_hash =", "update device_credentials"):
            if banned in text:
                offenders.append(f"{path}: {banned}")
    assert not offenders, f"in-place key writes found: {offenders}"


def test_the_rotation_helper_appends_rather_than_mutates():
    """`rotate` must go through `issue`; a local row build would bypass its guards."""
    src = inspect.getsource(FakeCredentialStore.rotate)
    assert "self.issue(" in src, "rotate must append via issue()"
    assert "key_hash" not in src, "rotate must not touch key material directly"


# ------------------------------------------------------------------------- migration ---
def test_the_migration_exists():
    """[DB-DEP] Reviewable now; enforced in-engine when a Neon instance exists."""
    assert MIGRATION.is_file(), f"{MIGRATION} is missing"


def _executable_sql() -> str:
    """The migration with `--` comment lines stripped.

    A plain-text scan over the whole file passes on the header's own explanatory prose:
    this migration *documents* every column it guards, so `"municipality_id" in sql` is true
    even with the guard deleted. Only the statements count.
    """
    lines = [
        line for line in MIGRATION.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    ]
    return "\n".join(lines).lower()


def test_the_migration_fires_before_update():
    sql = _executable_sql()
    assert "before update on device_credentials" in sql
    assert "raise exception" in sql


@pytest.mark.parametrize(
    "column", ["key_hash", "credential_id", "bridge_id", "municipality_id", "created_at"]
)
def test_the_migration_guards_every_immutable_column(column: str):
    """Asserted against the actual condition, so deleting a branch fails here."""
    sql = _executable_sql()
    assert f"new.{column} is distinct from old.{column}" in sql, (
        f"the guard does not compare {column}"
    )


def test_the_migration_still_permits_revocation_and_last_used():
    """The guard must not freeze the row — 0017's legitimate updates stay legal.

    Stated as an absence: neither column may appear in an immutability comparison, or
    revocation (the mechanism that replaces DELETE) would be blocked too.
    """
    sql = _executable_sql()
    for permitted in ("last_used_at", "revoked_at"):
        assert f"new.{permitted} is distinct from old.{permitted}" not in sql, (
            f"{permitted} must stay writable"
        )


def test_the_migration_blocks_un_revoking():
    """Reactivating a revoked row would make a retired Pi live with no record of the retirement."""
    sql = _executable_sql()
    assert "old.status = 'revoked'" in sql


def test_the_migration_declares_no_timescale_extension():
    """Scan for *declarations*, not the word — the header legitimately says 'NO TimescaleDB'."""
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for banned in ("create extension", "create_hypertable", "add_dimension"):
        assert banned not in sql, f"the migration declares {banned!r}"


def test_the_migration_number_is_free_and_unique():
    numbers = [p.name[:4] for p in Path("db/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")]
    assert numbers.count("0018") == 1, "0018 is claimed more than once"
