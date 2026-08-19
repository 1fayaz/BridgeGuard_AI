"""R204 — decision_log gains the risk-reasoning audit kinds.

[DB-DEP] No Postgres locally, so the ALTER TYPE cannot be EXECUTED. What is verifiable now: the
migration adds exactly the three risk kinds to the shared decision_kind enum (one cross-agent
audit trail, per plan §3b), each guarded so re-running is safe, and does NOT redefine or drop the
DCA's existing kinds.

  RISK_ASSESSMENT      a scored whole-bridge assessment was emitted
  RISK_WITHHELD        coverage below floor -> score withheld, routed to human review (FR-6)
  RISK_GUARDRAIL_FAIL  numeric-provenance guardrail failed closed after one regenerate (FR-7)
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0007_decision_log_risk_kinds.sql"
)

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


def test_all_three_risk_kinds_added(sql: str):
    for kind in RISK_KINDS:
        assert f"'{kind}'" in sql, f"decision_kind missing risk kind: {kind}"


def test_adds_are_idempotent(sql: str):
    # ALTER TYPE ... ADD VALUE IF NOT EXISTS so re-running the migration is safe.
    lower = sql.lower()
    assert lower.count("add value if not exists") >= len(RISK_KINDS)


def test_does_not_redefine_or_drop_the_enum(sql: str):
    # One shared audit trail: we EXTEND, never recreate (which would drop the DCA's kinds).
    lower = sql.lower()
    assert "create type decision_kind" not in lower
    assert "drop type decision_kind" not in lower


def test_does_not_touch_existing_dca_kinds(sql: str):
    # The DCA's kinds are not re-added (that would error) — only the three new ones appear.
    for kind in DCA_KINDS:
        assert f"'{kind}'" not in sql, f"must not re-add existing DCA kind: {kind}"
