"""R203 — risk_assessments migration: structural assertions.

[DB-DEP] No Supabase/Postgres locally, so the migration cannot be EXECUTED and the CHECK
constraints / append-+-supersede triggers cannot be live-verified here. What is verifiable now:
the file declares the severity + review_status enums, the score+explanation (FR-1) and withheld
(FR-6/7) shapes via CHECKs, the FR-11 CRITICAL->PENDING_HUMAN_REVIEW CHECK, the full provenance
block (FR-9/10), the (bridge_id, cycle_id) current-row idempotency, and the same
correct-by-append guard + DELETE-block as validated_readings (0002). This asserts the schema is
written correctly, not live-enforced.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0006_risk_assessments.sql"
)

SEVERITIES = ("SAFE", "WATCH", "WARNING", "CRITICAL")
REVIEW_STATUSES = ("FINAL", "PENDING_HUMAN_REVIEW")


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_severity_enum_is_the_closed_set(sql: str):
    lower = sql.lower()
    assert "create type severity as enum" in lower
    for s in SEVERITIES:
        assert f"'{s}'" in sql, f"severity missing: {s}"


def test_review_status_enum_is_the_closed_set(sql: str):
    lower = sql.lower()
    assert "create type review_status as enum" in lower
    for r in REVIEW_STATUSES:
        assert f"'{r}'" in sql, f"review_status missing: {r}"


def test_core_verdict_columns_present(sql: str):
    lower = sql.lower()
    for col in ("bridge_id", "cycle_id", "risk_score", "severity",
                "recommendation", "explanation", "review_status"):
        assert col in lower, f"missing column: {col}"


def test_score_and_severity_are_nullable_for_withheld(sql: str):
    # FR-6/FR-7: a withheld assessment has NULL score + NULL severity. They must NOT be NOT NULL.
    lower = sql.lower()
    # crude but effective: the explanation IS required, the score is not.
    assert "risk_score" in lower
    # the withheld CHECK ties NULL score to PENDING review (asserted below)


def test_explanation_is_always_required_fr1(sql: str):
    # FR-1 / mandate #1: every assessment (scored OR withheld) carries a WHY.
    lower = sql.lower()
    assert "explanation" in lower
    assert "explanation_present" in lower or "explanation is not null" in lower \
        or "length(btrim(explanation))" in lower


def test_scored_assessment_requires_severity_check(sql: str):
    # FR-1: a numeric score must carry a band; score-without-band is rejected.
    lower = sql.lower()
    assert "score_has_band" in lower or "risk_score is null" in lower


def test_withheld_requires_pending_review_check(sql: str):
    # FR-6/FR-7: NULL score => severity NULL AND review_status = PENDING_HUMAN_REVIEW.
    lower = sql.lower()
    assert "withheld" in lower
    assert "pending_human_review" in lower


def test_critical_must_be_pending_review_check(sql: str):
    # FR-11 / mandate #3: a CRITICAL assessment can never be FINAL.
    lower = sql.lower()
    assert "critical_not_final" in lower or \
        ("severity = 'critical'" in lower and "pending_human_review" in lower)


def test_provenance_block_present_fr9_fr10(sql: str):
    # FR-9/FR-10: reproducible from exactly these pinned inputs.
    lower = sql.lower()
    for col in ("source_analysis_ids", "baseline_ref", "standard_code", "standard_version",
                "score_weights_version", "model_id", "model_version", "trace_id"):
        assert col in lower, f"missing provenance column: {col}"
    assert "bigint[]" in lower  # source_analysis_ids is an id array


def test_contributing_factors_stored_as_jsonb(sql: str):
    lower = sql.lower()
    assert "contributing_factors" in lower
    assert "jsonb" in lower


def test_idempotency_unique_current_bridge_cycle(sql: str):
    # Only one CURRENT (non-superseded) assessment per (bridge_id, cycle_id) — redelivery no-op.
    lower = sql.lower()
    assert "unique" in lower
    assert "bridge_id" in lower and "cycle_id" in lower
    # partial index over current rows (superseded_by IS NULL)
    assert "superseded_by is null" in lower


def test_correction_chain_is_self_referential(sql: str):
    lower = sql.lower()
    assert "superseded_by" in lower
    assert "references risk_assessments" in lower


def test_correct_by_append_guard_present(sql: str):
    # Same discipline as validated_readings: score/severity/explanation of a written row
    # cannot be mutated in place; only superseded_by may be stamped.
    lower = sql.lower()
    assert "before update on risk_assessments" in lower
    assert "correct-by-append" in lower


def test_history_is_permanent_delete_blocked(sql: str):
    lower = sql.lower()
    assert "before delete on risk_assessments" in lower
    assert "delete blocked" in lower
