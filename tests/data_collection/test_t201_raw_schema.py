"""T201 — raw_readings migration: structural assertions.

[DB-DEP] No Supabase/Postgres locally, so the migration cannot be EXECUTED here and
live append-only enforcement is deferred. What is verifiable now: the migration file
contains exactly the structures the acceptance check names — both timestamps (G4),
the required columns, and append-only enforcement (REVOKE + blocking trigger). This
asserts the schema is written correctly; it does NOT claim a live DB pass.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0001_raw_readings.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    return text.lower()


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_table_and_required_columns_present(sql: str):
    assert "create table" in sql and "raw_readings" in sql
    for column in (
        "sensor_time",
        "ingest_time",
        "sensor_id",
        "sensor_type",
        "value",
        "unit",
        "raw_payload",
    ):
        assert column in sql, f"raw_readings missing column: {column}"


def test_both_timestamps_present_for_clock_drift(sql: str):
    # G4: sensor_time drives liveness/ordering; ingest_time enables drift calc.
    assert "sensor_time" in sql
    assert "ingest_time" in sql


def test_value_is_nullable(sql: str):
    # Malformed payloads still get a raw row; value may be NULL (FR-6/AC-7).
    # Assert 'value' is NOT declared NOT NULL.
    import re

    m = re.search(r"value\s+double precision([^,]*)", sql)
    assert m is not None, "value column not found"
    assert "not null" not in m.group(1), "value must be nullable"


def test_append_only_revoke_present(sql: str):
    # Constitution II: UPDATE and DELETE revoked (append-only at the DB boundary).
    assert "revoke" in sql
    assert "update" in sql and "delete" in sql
    assert "raw_readings from public" in sql


def test_append_only_blocking_trigger_present(sql: str):
    # Belt-and-braces trigger blocks UPDATE/DELETE regardless of grant drift.
    assert "before update or delete" in sql
    assert "append-only" in sql


def test_raw_payload_preserved_verbatim(sql: str):
    # Provenance: the exact original payload is stored (jsonb), not just parsed fields.
    assert "raw_payload" in sql and "jsonb" in sql
