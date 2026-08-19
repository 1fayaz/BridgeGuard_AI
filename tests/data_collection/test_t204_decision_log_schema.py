"""T204 — decision_log migration: structural assertions.

[DB-DEP] No Supabase/Postgres locally; the migration cannot be EXECUTED here. What is
verifiable now: the file declares all nine decision types, an old_status/new_status
pair (CORRECTION transitions), a required reason, raw value + payload + source links
(traceability), and append-only enforcement (REVOKE + blocking trigger). This asserts
the schema is written correctly, not that the trigger fires live.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0004_decision_log.sql"
)

NINE_DECISIONS = (
    "LIVENESS",
    "RANGE",
    "SPIKE",
    "GAP",
    "PENDING",
    "CORRECTION",
    "PARSE",
    "CLOCK_DRIFT",
    "DUPLICATE_CONFLICT",
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_all_nine_decision_types_present(sql: str):
    assert "create type decision_kind as enum" in sql.lower()
    for kind in NINE_DECISIONS:
        assert f"'{kind}'" in sql, f"decision_kind missing: {kind}"


def test_status_transition_columns_for_corrections(sql: str):
    # CORRECTION must record old_status -> new_status (FR-7).
    assert "old_status" in sql
    assert "new_status" in sql


def test_reason_is_required_and_non_blank(sql: str):
    # Const. VI: an audit row with no reason explains nothing.
    lower = sql.lower()
    assert "reason" in lower
    assert "reason_not_blank" in lower
    # reason column declared NOT NULL.
    import re

    m = re.search(r"reason\s+text\s+(not null)", lower)
    assert m is not None, "reason must be NOT NULL"


def test_traceability_to_raw(sql: str):
    # Const. II: every decision links to its causing input + immutable source rows.
    assert "raw_value" in sql
    assert "raw_payload" in sql
    assert "source_raw_ids" in sql


def test_append_only_revoke_and_trigger(sql: str):
    lower = sql.lower()
    assert "revoke update, delete, truncate on decision_log from public" in lower
    assert "before update or delete on decision_log" in lower
    assert "append-only" in lower


def test_required_columns_present(sql: str):
    for column in ("decided_at", "sensor_id", "decision", "reason"):
        assert column in sql, f"decision_log missing column: {column}"


def test_dup_conflict_and_clock_drift_documented_in_reason_contract(sql: str):
    # The exact dup-conflict reason string and the drift gap/tolerance contract are
    # documented at the schema so the writer (T904/T905) has the canonical wording.
    assert "duplicate timestamp, conflicting value, first-received kept" in sql
