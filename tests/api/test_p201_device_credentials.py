"""P201 — `device_credentials` (0017) + FakeCredentialStore: structural + in-fake assertions.

[DB-DEP] No Neon locally, so the migration cannot be EXECUTED here. What is verifiable
now: the file declares the table with the right columns, the hard FKs that make a
credential tenant-attributable, a unique `key_hash`, **no plaintext-key column**, and no
delete path. The in-memory FakeCredentialStore mirrors each guarantee for the logic tests.

Three properties carry the weight:

**No plaintext key, anywhere.** A stolen database dump must not yield working device
credentials. The table stores only a hash, and the structural check asserts no column is
named in a way that would hold the key itself.

**Revocation is a state change, not a delete.** A regulator asking "which device sent
this reading, and was it authorised at the time?" needs the credential row to still
exist after revocation. So the migration provides no DELETE path and blocks deletes
outright — the same discipline as the append-only SOR tables.

**A credential resolves to exactly one bridge + municipality.** This is what makes the
Pi's API key take the *same* RLS path as a JWT: the key resolves to a tenant, and that
tenant goes into `app.current_municipality_id`. A credential naming a non-existent
bridge is rejected by the database, not by convention.

Ties to spec §Authentication B, plan §2a, tasks P201.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from db.credential_store import (
    CredentialStatus,
    DuplicateCredentialError,
    FakeCredentialStore,
    PlaintextKeyRejected,
    RevokedCredentialError,
    UnknownCredentialError,
)
from db.tenant_store import FakeTenantStore, UnknownBridgeError

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0017_device_credentials.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def low(sql: str) -> str:
    return sql.lower()


@pytest.fixture
def store() -> FakeCredentialStore:
    tenants = FakeTenantStore()
    tenants.add_municipality("MUNI_A", name="Alpha")
    tenants.add_municipality("MUNI_B", name="Beta")
    tenants.add_bridge("BRIDGE_1", municipality_id="MUNI_A", name="First")
    tenants.add_bridge("BRIDGE_2", municipality_id="MUNI_B", name="Second")
    return FakeCredentialStore(tenants)


# ------------------------------------------------------------- migration structure ---
def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_creates_device_credentials_table(low: str):
    assert "create table" in low
    assert "device_credentials" in low


def test_declares_every_required_column(low: str):
    for column in ("credential_id", "key_hash", "bridge_id", "municipality_id",
                   "device_label", "status", "created_at", "last_used_at",
                   "revoked_at"):
        assert column in low, f"missing column {column}"


def test_key_hash_is_unique_and_not_null(low: str):
    assert re.search(r"key_hash\s+text\s+not null", low), "key_hash must be TEXT NOT NULL"
    # Unique so one physical key maps to at most one credential row.
    assert re.search(r"key_hash[^,]*unique", low) or "unique (key_hash)" in low \
        or "unique(key_hash)" in low, "key_hash must be UNIQUE"


def _column_lines(sql: str) -> list[str]:
    """Just the CREATE TABLE column declarations — comments excluded.

    Scanning the whole file for words like "plaintext" is useless: the migration's own
    header explains at length that it stores NO plaintext, so the prose trips every
    check. What matters is the declared columns.
    """
    body = sql.split("CREATE TABLE", 1)[1].split(");", 1)[0]
    out = []
    for raw in body.splitlines():
        line = raw.split("--", 1)[0].strip()  # drop trailing comments
        if line and not line.upper().startswith("CONSTRAINT"):
            out.append(line.lower())
    return out


def test_no_column_stores_a_plaintext_key(sql: str):
    # Only `key_hash` may hold key material, and it holds a hash.
    columns = _column_lines(sql)
    for banned in ("key_plaintext", "plaintext", "api_key", "raw_key", "secret"):
        offenders = [c for c in columns if banned in c]
        assert not offenders, f"{banned!r} appears in a column declaration: {offenders}"
    # And the one key-related column is explicitly the hash.
    assert any(c.startswith("key_hash") for c in columns)


def test_only_one_column_holds_key_material(sql: str):
    key_columns = [c for c in _column_lines(sql) if "key" in c.split()[0]]
    assert [c.split()[0] for c in key_columns] == ["key_hash"], (
        f"exactly one key column expected, found: {key_columns}"
    )


def test_bridge_and_municipality_are_hard_fks(low: str):
    assert re.search(r"bridge_id\s+text\s+not null", low)
    assert re.search(r"municipality_id\s+text\s+not null", low)
    assert "references bridges" in low, "bridge_id must be a hard FK"
    assert "references municipalities" in low, "municipality_id must be a hard FK"


def test_status_is_a_closed_set(low: str):
    # active | revoked, enforced by a CHECK — not free text.
    assert "check" in low
    assert "active" in low and "revoked" in low


def test_no_delete_path_and_deletes_are_blocked(low: str):
    assert "on delete cascade" not in low, "a credential must never cascade away"
    # Same discipline as the append-only SOR tables: a DELETE is refused in-engine.
    assert "delete" in low, "the migration must address DELETE explicitly"
    assert "block" in low or "raise exception" in low or "prevent" in low


def test_index_on_key_hash(low: str):
    assert "create index" in low or "unique" in low
    assert "key_hash" in low


def test_header_states_stack_and_db_dep(sql: str):
    # The header is everything before the first statement.
    head = sql.split("CREATE TABLE", 1)[0]
    assert "0017" in head
    assert "Neon" in head or "neon" in head
    assert "TimescaleDB" in head, "the no-TimescaleDB constraint must be restated"
    assert "[DB-DEP]" in head


def test_header_names_the_rls_guc(sql: str):
    # This table participates in the same isolation path; the GUC name must appear so a
    # reader cannot mistake it for an untenanted lookup table.
    assert "app.current_municipality_id" in sql


def test_rls_is_enabled_and_forced(low: str):
    assert "enable row level security" in low
    assert "force  row level security" in low or "force row level security" in low


# ---------------------------------------------------------------- in-fake behaviour ---
def test_issue_returns_credential_and_stores_only_a_hash(store: FakeCredentialStore):
    cred = store.issue("BRIDGE_1", device_label="Pi at north abutment", key="raw-secret-key-0123456789abcdef")
    assert cred.bridge_id == "BRIDGE_1"
    assert cred.municipality_id == "MUNI_A"  # denormalized from the chain
    assert cred.status is CredentialStatus.ACTIVE
    # The plaintext must not be recoverable from the stored row.
    assert "raw-secret-key-0123456789abcdef" not in repr(cred)
    assert cred.key_hash != "raw-secret-key-0123456789abcdef"
    assert len(cred.key_hash) >= 32


def test_unknown_bridge_is_rejected(store: FakeCredentialStore):
    with pytest.raises(UnknownBridgeError):
        store.issue("NO_SUCH_BRIDGE", device_label="ghost", key="ghost-key-0123456789abcdef")


def test_duplicate_key_is_rejected(store: FakeCredentialStore):
    store.issue("BRIDGE_1", device_label="one", key="same-key-0123456789abcdef")
    with pytest.raises(DuplicateCredentialError):
        store.issue("BRIDGE_2", device_label="two", key="same-key-0123456789abcdef")


def test_resolve_yields_exactly_one_bridge_and_municipality(store: FakeCredentialStore):
    store.issue("BRIDGE_1", device_label="pi-1", key="key-alpha-0123456789abcdef")
    scope = store.resolve("key-alpha-0123456789abcdef")
    assert scope.bridge_id == "BRIDGE_1"
    assert scope.municipality_id == "MUNI_A"


def test_resolve_rejects_an_unknown_key(store: FakeCredentialStore):
    with pytest.raises(UnknownCredentialError):
        store.resolve("never-issued-0123456789abcdef")


def test_resolve_never_accepts_a_hash_as_the_key(store: FakeCredentialStore):
    """Presenting the stored hash must not authenticate — else a DB leak is a master key."""
    cred = store.issue("BRIDGE_1", device_label="pi-1", key="key-alpha-0123456789abcdef")
    with pytest.raises(UnknownCredentialError):
        store.resolve(cred.key_hash)


def test_revocation_is_a_state_change_not_a_delete(store: FakeCredentialStore):
    cred = store.issue("BRIDGE_1", device_label="pi-1", key="key-alpha-0123456789abcdef")
    store.revoke(cred.credential_id)
    # The row survives — an auditor can still ask who sent what, and whether it was authorised.
    kept = store.get(cred.credential_id)
    assert kept.status is CredentialStatus.REVOKED
    assert kept.revoked_at is not None
    assert store.count() == 1


def test_revoked_credential_cannot_authenticate(store: FakeCredentialStore):
    cred = store.issue("BRIDGE_1", device_label="pi-1", key="key-alpha-0123456789abcdef")
    store.revoke(cred.credential_id)
    with pytest.raises(RevokedCredentialError):
        store.resolve("key-alpha-0123456789abcdef")


def test_store_exposes_no_delete_method(store: FakeCredentialStore):
    for name in ("delete", "remove", "purge", "drop"):
        assert not hasattr(store, name), f"FakeCredentialStore must not expose {name}()"


def test_rotation_allows_brief_overlap_then_revoke(store: FakeCredentialStore):
    old = store.issue("BRIDGE_1", device_label="pi-1", key="old-key-0123456789abcdef")
    new = store.issue("BRIDGE_1", device_label="pi-1", key="new-key-0123456789abcdef")
    # Both work during the overlap window — a Pi is not locked out mid-rotation.
    assert store.resolve("old-key-0123456789abcdef").bridge_id == "BRIDGE_1"
    assert store.resolve("new-key-0123456789abcdef").bridge_id == "BRIDGE_1"
    store.revoke(old.credential_id)
    with pytest.raises(RevokedCredentialError):
        store.resolve("old-key-0123456789abcdef")
    assert store.resolve("new-key-0123456789abcdef").bridge_id == "BRIDGE_1"
    assert new.status is CredentialStatus.ACTIVE


def test_issue_refuses_a_blank_key(store: FakeCredentialStore):
    with pytest.raises(PlaintextKeyRejected):
        store.issue("BRIDGE_1", device_label="pi-1", key="   ")


def test_issue_refuses_a_trivially_short_key(store: FakeCredentialStore):
    # A guessable device key is not a credential.
    with pytest.raises(PlaintextKeyRejected):
        store.issue("BRIDGE_1", device_label="pi-1", key="abc")


def test_last_used_is_recorded_on_resolve(store: FakeCredentialStore):
    cred = store.issue("BRIDGE_1", device_label="pi-1", key="key-alpha-0123456789abcdef")
    assert store.get(cred.credential_id).last_used_at is None
    store.resolve("key-alpha-0123456789abcdef")
    assert store.get(cred.credential_id).last_used_at is not None
