"""A203 — alert_dispatches migration: structural assertions.

[DB-DEP] No Neon/Postgres locally, so the migration cannot be EXECUTED and the CHECK constraints /
append-+-supersede triggers cannot be live-verified here. What IS verifiable now: the file declares
the dispatch_decision / delivery_state / escalation_state / approval_state enums; the
gated-needs-approval-state and un-gated-has-none shapes via CHECKs; the full provenance block
(assessment id+version, trace_id, FR-11/FR-13); the (assessment_id, assessment_version) current-row
idempotency (FR-10); and the same correct-by-append guard + DELETE-block as risk_assessments (0006)
/ report_artifacts (0008). This asserts the schema is written correctly, not live-enforced. The
in-memory FakeAlertStore (A801) mirrors these guarantees for the logic tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0010_alert_dispatches.sql"
)

DECISIONS = ("AUTO_FIRE", "NEEDS_APPROVAL", "DASHBOARD_ONLY")
DELIVERY_STATES = ("QUEUED", "SENT", "DELIVERED", "FAILED", "ACKNOWLEDGED")
ESCALATION_STATES = ("OPEN", "ESCALATED", "CLOSED")
APPROVAL_STATES = ("AWAITING_APPROVAL", "APPROVED", "REJECTED")


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_dispatch_decision_enum_is_the_closed_set(sql: str):
    assert "create type dispatch_decision as enum" in sql.lower()
    for d in DECISIONS:
        assert f"'{d}'" in sql, f"decision missing: {d}"


def test_delivery_state_enum_is_the_closed_set(sql: str):
    assert "create type delivery_state as enum" in sql.lower()
    for s in DELIVERY_STATES:
        assert f"'{s}'" in sql, f"delivery_state missing: {s}"


def test_escalation_state_enum_is_the_closed_set(sql: str):
    assert "create type escalation_state as enum" in sql.lower()
    for s in ESCALATION_STATES:
        assert f"'{s}'" in sql, f"escalation_state missing: {s}"


def test_approval_state_enum_is_the_closed_set(sql: str):
    assert "create type approval_state as enum" in sql.lower()
    for s in APPROVAL_STATES:
        assert f"'{s}'" in sql, f"approval_state missing: {s}"


def test_core_columns_present(sql: str):
    lower = sql.lower()
    for col in ("bridge_id", "cycle_id", "assessment_id", "assessment_version",
                "dispatch_decision", "channel", "recipient", "provider_message_id",
                "delivery_state", "escalation_state", "close_reason",
                "approval_state", "approved_by", "approved_at", "trace_id", "attempted_at"):
        assert col in lower, f"missing column: {col}"


def test_gated_dispatch_requires_an_approval_state_check(sql: str):
    # FR-5: a NEEDS_APPROVAL row must carry an approval_state (the human sign-off is audited).
    lower = sql.lower()
    assert "gated_has_approval_state" in lower or \
        ("needs_approval" in lower and "approval_state is not null" in lower)


def test_ungated_dispatch_has_no_approval_state_check(sql: str):
    # An AUTO_FIRE / DASHBOARD_ONLY row is un-gated: approval_state must be NULL (no sign-off needed).
    lower = sql.lower()
    assert "ungated_has_no_approval_state" in lower or \
        ("approval_state is null" in lower)


def test_provenance_block_present_fr11_fr13(sql: str):
    # FR-11/FR-13: reproducible + end-to-end traceable from exactly the pinned assessment version
    # and the upstream trace id.
    lower = sql.lower()
    for col in ("assessment_id", "assessment_version", "trace_id"):
        assert col in lower, f"missing provenance column: {col}"


def test_idempotency_unique_current_assessment_version(sql: str):
    # FR-10: only one CURRENT (non-superseded) dispatch per (assessment_id, assessment_version).
    lower = sql.lower()
    assert "unique" in lower
    assert "assessment_id" in lower and "assessment_version" in lower
    assert "superseded_by is null" in lower  # partial index over current rows


def test_correction_chain_is_self_referential(sql: str):
    lower = sql.lower()
    assert "superseded_by" in lower
    assert "references alert_dispatches" in lower


def test_correct_by_append_guard_present(sql: str):
    # Same discipline as risk_assessments / report_artifacts: the pinned verdict identity + trace
    # of a written row cannot be mutated in place; only the state machine + superseded_by advance.
    lower = sql.lower()
    assert "before update on alert_dispatches" in lower
    assert "correct-by-append" in lower


def test_history_is_permanent_delete_blocked(sql: str):
    lower = sql.lower()
    assert "before delete on alert_dispatches" in lower
    assert "delete blocked" in lower


def test_no_timescaledb_only_standard_indexes(sql: str):
    # Constitution v2.1.0: Neon/Postgres, standard indexes only — no time-series extension.
    lower = sql.lower()
    assert "timescaledb" not in lower
    assert "create_hypertable" not in lower
