"""A204 — decision_log gains the alert-escalation audit kinds.

[DB-DEP] No Neon/Postgres locally, so the ALTER TYPE cannot be EXECUTED. What is verifiable now:
the migration adds exactly the four alert kinds to the shared decision_kind enum (one cross-agent
audit trail, per plan §3b / Open Item 11), each guarded so re-running is safe, and does NOT
redefine or drop the DCA's / Risk's / Report's existing kinds.

  ALERT_DISPATCHED  a notification was dispatched (records assessment id+version + channel + approval)
  ALERT_ESCALATED   an alert advanced up the escalation ladder (no timely delivery/ack, FR-6/FR-8)
  ALERT_WITHHELD    no dispatch on purpose; the row names the reason (ASSESSMENT_NOT_FOUND, or a
                    CONSISTENCY_MISMATCH where the message contradicts the verdict — FR-9)
  ALERT_ERROR       an unexpected dispatch failure — structured, never a crash (FR-12)
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0011_decision_log_alert_kinds.sql"
)

ALERT_KINDS = ("ALERT_DISPATCHED", "ALERT_ESCALATED", "ALERT_WITHHELD", "ALERT_ERROR")
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


def test_all_four_alert_kinds_added(sql: str):
    for kind in ALERT_KINDS:
        assert f"'{kind}'" in sql, f"decision_kind missing alert kind: {kind}"


def test_adds_are_idempotent(sql: str):
    # ALTER TYPE ... ADD VALUE IF NOT EXISTS so re-running the migration is safe.
    lower = sql.lower()
    assert lower.count("add value if not exists") >= len(ALERT_KINDS)


def test_does_not_redefine_or_drop_the_enum(sql: str):
    # One shared audit trail: we EXTEND, never recreate (which would drop other agents' kinds).
    lower = sql.lower()
    assert "create type decision_kind" not in lower
    assert "drop type decision_kind" not in lower


def test_does_not_touch_existing_kinds(sql: str):
    # The DCA's / Risk's / Report's kinds are not re-added (that would error) — only the four new ones.
    for kind in DCA_KINDS + RISK_KINDS + REPORT_KINDS:
        assert f"'{kind}'" not in sql, f"must not re-add existing kind: {kind}"


def test_notes_alter_type_cannot_run_in_a_transaction_block(sql: str):
    # Same operational caveat as 0007/0009: ADD VALUE cannot run inside BEGIN/COMMIT.
    lower = sql.lower()
    assert "transaction block" in lower or "outside" in lower
