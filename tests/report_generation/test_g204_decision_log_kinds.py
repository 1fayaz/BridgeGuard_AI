"""G204 — decision_log gains the report-generation audit kinds.

[DB-DEP] No Neon/Postgres locally, so the ALTER TYPE cannot be EXECUTED. What is verifiable now:
the migration adds exactly the three report kinds to the shared decision_kind enum (one
cross-agent audit trail, per plan §5), each guarded so re-running is safe, and does NOT redefine
or drop the DCA's or Risk's existing kinds.

  REPORT_RENDERED   a document was assembled and persisted (records assessment id+version + marks)
  REPORT_WITHHELD   no document produced on purpose (records the withheld reason, FR-5)
  REPORT_ERROR      an unexpected render failure — structured, never a crash (FR-12)
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0009_decision_log_report_kinds.sql"
)

REPORT_KINDS = ("REPORT_RENDERED", "REPORT_WITHHELD", "REPORT_ERROR")
RISK_KINDS = ("RISK_ASSESSMENT", "RISK_WITHHELD", "RISK_GUARDRAIL_FAIL")
DCA_KINDS = (
    "LIVENESS", "RANGE", "SPIKE", "GAP", "PENDING",
    "CORRECTION", "PARSE", "CLOCK_DRIFT", "DUPLICATE_CONFLICT",
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_extends_the_shared_decision_kind_enum(sql: str):
    lower = sql.lower()
    assert "alter type decision_kind" in lower
    assert "add value" in lower


def test_all_three_report_kinds_added(sql: str):
    for kind in REPORT_KINDS:
        assert f"'{kind}'" in sql, f"decision_kind missing report kind: {kind}"


def test_adds_are_idempotent(sql: str):
    # ALTER TYPE ... ADD VALUE IF NOT EXISTS so re-running the migration is safe.
    lower = sql.lower()
    assert lower.count("add value if not exists") >= len(REPORT_KINDS)


def test_does_not_redefine_or_drop_the_enum(sql: str):
    # One shared audit trail: we EXTEND, never recreate (which would drop other agents' kinds).
    lower = sql.lower()
    assert "create type decision_kind" not in lower
    assert "drop type decision_kind" not in lower


def test_does_not_touch_existing_dca_or_risk_kinds(sql: str):
    # The DCA's and Risk's kinds are not re-added (that would error) — only the three new ones.
    for kind in DCA_KINDS + RISK_KINDS:
        assert f"'{kind}'" not in sql, f"must not re-add existing kind: {kind}"


def test_notes_alter_type_cannot_run_in_a_transaction_block(sql: str):
    # Same operational caveat as 0007: ADD VALUE cannot run inside BEGIN/COMMIT.
    lower = sql.lower()
    assert "transaction block" in lower or "outside" in lower
