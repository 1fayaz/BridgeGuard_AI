"""D102 — bridges migration (0013) + FakeTenantStore.add_bridge: structural + in-fake assertions.

[DB-DEP] No Neon/Postgres locally; the migration cannot be EXECUTED here. What is verifiable now:
the file declares the bridges table with a TEXT primary key, a NOT NULL municipality_id that is a
HARD foreign key REFERENCES municipalities(id) (the ownership-chain link that makes a bridge
tenant-attributable), name + location, a created_at default, an index on (municipality_id), and the
Neon/no-TimescaleDB header. The in-memory FakeTenantStore mirrors the hard FK: a bridge under an
unknown municipality is rejected; a valid one is accepted.

Ties to spec FR-1 (ownership chain municipalities -> bridges -> sensors -> readings) and AC-1
(no orphan bridge — every bridge references exactly one municipality via an enforced FK).
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0013_bridges.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


# --- migration structure ------------------------------------------------------------------------
def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_creates_bridges_table(sql: str):
    lower = sql.lower()
    assert "create table" in lower
    assert "bridges" in lower


def test_id_is_text_primary_key(sql: str):
    import re

    m = re.search(r"id\s+text\s+primary key", sql.lower())
    assert m is not None, "bridges.id must be a TEXT PRIMARY KEY"


def test_municipality_id_is_not_null_hard_fk(sql: str):
    # The ownership-chain link: municipality_id must be NOT NULL and a HARD FK (plan §5).
    import re

    lower = sql.lower()
    m = re.search(r"municipality_id\s+text\s+not null", lower)
    assert m is not None, "bridges.municipality_id must be TEXT NOT NULL"
    assert "references municipalities" in lower, "municipality_id must REFERENCE municipalities(id)"


def test_name_and_location_present(sql: str):
    for column in ("name", "location"):
        assert column in sql, f"bridges missing column: {column}"


def test_created_at_present_with_default(sql: str):
    lower = sql.lower()
    assert "created_at" in lower
    assert "timestamptz" in lower
    assert "now()" in lower


def test_municipality_id_index_present(sql: str):
    # plan §4: (municipality_id) index for tenant listing + RLS predicate performance.
    lower = sql.lower()
    assert "create index" in lower
    assert "municipality_id" in lower
    # an index whose name/target references municipality_id on bridges
    import re

    m = re.search(r"create index[^;]*on\s+bridges\s*\(\s*municipality_id", lower)
    assert m is not None, "expected an index on bridges(municipality_id)"


def test_required_columns_present(sql: str):
    for column in ("id", "municipality_id", "name", "location", "created_at"):
        assert column in sql, f"bridges missing column: {column}"


def test_neon_no_timescaledb_header(sql: str):
    lower = sql.lower()
    assert "neon" in lower, "header must state the Neon/Postgres stack"
    assert "no timescaledb" in lower, "header must state NO TimescaleDB"
    assert "hypertable" not in lower and "create_hypertable" not in lower
    assert "[db-dep]" in lower


# --- FakeTenantStore (in-fake mirror of the hard FK) --------------------------------------------
def test_fake_store_accepts_a_bridge_under_a_real_municipality():
    from db.tenant_store import FakeTenantStore

    store = FakeTenantStore()
    store.add_municipality("MUNI_A", name="Alpha City")
    store.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span", location="River Rd")
    b = store.get_bridge("BRIDGE_A1")
    assert b.municipality_id == "MUNI_A"
    assert b.name == "North Span"


def test_fake_store_rejects_bridge_under_unknown_municipality():
    from db.tenant_store import FakeTenantStore, UnknownMunicipalityError

    store = FakeTenantStore()
    with pytest.raises(UnknownMunicipalityError):
        store.add_bridge("BRIDGE_X", municipality_id="NOPE", name="Orphan", location="?")


def test_fake_store_rejects_duplicate_bridge_id():
    from db.tenant_store import FakeTenantStore, DuplicateBridgeError

    store = FakeTenantStore()
    store.add_municipality("MUNI_A", name="Alpha City")
    store.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span", location="River Rd")
    with pytest.raises(DuplicateBridgeError):
        store.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="Dup", location="x")


def test_fake_store_resolves_bridge_to_municipality():
    # The chain hop bridge -> municipality (feeds D104's full-chain resolution).
    from db.tenant_store import FakeTenantStore

    store = FakeTenantStore()
    store.add_municipality("MUNI_A", name="Alpha City")
    store.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span", location="River Rd")
    assert store.municipality_of_bridge("BRIDGE_A1") == "MUNI_A"
