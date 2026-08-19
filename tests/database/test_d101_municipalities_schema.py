"""D101 — municipalities migration (0012) + FakeTenantStore: structural + in-fake assertions.

[DB-DEP] No Neon/Postgres locally; the migration cannot be EXECUTED here. What is verifiable now:
the file declares the tenant-root table with a TEXT primary key, a NOT NULL name, a created_at
default, and the Neon/no-TimescaleDB header. The in-memory FakeTenantStore mirrors the guarantees
the SQL will enforce live — it accepts a municipality and rejects a duplicate id (the TEXT PK
uniqueness). This asserts the schema is written correctly + the fake mirrors it, not that the DB
enforces it live.

Ties to spec FR-1 (root of the ownership chain municipalities -> bridges -> sensors -> readings)
and AC-1 (the ownership chain exists with enforced keys).
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0012_municipalities.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


# --- migration structure ------------------------------------------------------------------------
def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_creates_municipalities_table(sql: str):
    assert "create table" in sql.lower()
    assert "municipalities" in sql.lower()


def test_id_is_text_primary_key(sql: str):
    # Confirmed decision: TEXT natural key (zero-churn hard FKs downstream).
    import re

    lower = sql.lower()
    m = re.search(r"id\s+text\s+primary key", lower)
    assert m is not None, "municipalities.id must be a TEXT PRIMARY KEY"


def test_name_is_not_null(sql: str):
    import re

    lower = sql.lower()
    m = re.search(r"name\s+text\s+not null", lower)
    assert m is not None, "municipalities.name must be TEXT NOT NULL"


def test_created_at_present_with_default(sql: str):
    lower = sql.lower()
    assert "created_at" in lower
    assert "timestamptz" in lower
    assert "now()" in lower


def test_required_columns_present(sql: str):
    for column in ("id", "name", "created_at"):
        assert column in sql, f"municipalities missing column: {column}"


def test_neon_no_timescaledb_header(sql: str):
    lower = sql.lower()
    assert "neon" in lower, "header must state the Neon/Postgres stack"
    # The header must explicitly negate TimescaleDB (matches 0001/0004's fixed wording); and there
    # must be no actual hypertable usage anywhere in the migration body.
    assert "no timescaledb" in lower, "header must state NO TimescaleDB"
    assert "hypertable" not in lower and "create_hypertable" not in lower
    assert "[db-dep]" in lower


# --- FakeTenantStore (in-fake mirror) --------------------------------------------------------
def test_fake_store_accepts_a_municipality():
    from db.tenant_store import FakeTenantStore

    store = FakeTenantStore()
    store.add_municipality("MUNI_A", name="Alpha City")
    assert store.get_municipality("MUNI_A").name == "Alpha City"


def test_fake_store_rejects_duplicate_id():
    from db.tenant_store import FakeTenantStore, DuplicateMunicipalityError

    store = FakeTenantStore()
    store.add_municipality("MUNI_A", name="Alpha City")
    with pytest.raises(DuplicateMunicipalityError):
        store.add_municipality("MUNI_A", name="Alpha Again")


def test_fake_store_requires_non_blank_name():
    from db.tenant_store import FakeTenantStore

    store = FakeTenantStore()
    with pytest.raises(ValueError):
        store.add_municipality("MUNI_A", name="")
