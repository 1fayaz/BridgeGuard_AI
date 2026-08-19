"""G203 — report_artifacts migration: structural assertions.

[DB-DEP] No Neon/Postgres locally, so the migration cannot be EXECUTED and the CHECK constraints /
append-+-supersede triggers cannot be live-verified here. What IS verifiable now: the file
declares the report_outcome / document_mark / withheld_reason enums; the RENDERED-needs-artifact
and WITHHELD-needs-reason shapes via CHECKs; the full provenance block (assessment id+version,
source_analysis_ids, standard code+version, template_version, FR-9/FR-11); the
(assessment_id, assessment_version) current-row idempotency; and the same correct-by-append guard
+ DELETE-block as risk_assessments (0006). This asserts the schema is written correctly, not
live-enforced. The in-memory FakeReportStore (G801) mirrors these guarantees for the logic tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0008_report_artifacts.sql"
)

OUTCOMES = ("RENDERED", "WITHHELD", "ERROR")
MARKS = ("NOT_FINAL", "SCORE_WITHHELD", "HISTORICAL", "SECTION_UNAVAILABLE")
WITHHELD_REASONS = ("ASSESSMENT_NOT_FOUND", "PROVENANCE_MISMATCH")


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_report_outcome_enum_is_the_closed_set(sql: str):
    lower = sql.lower()
    assert "create type report_outcome as enum" in lower
    for o in OUTCOMES:
        assert f"'{o}'" in sql, f"outcome missing: {o}"


def test_document_mark_enum_is_the_closed_set(sql: str):
    lower = sql.lower()
    assert "create type document_mark as enum" in lower
    for m in MARKS:
        assert f"'{m}'" in sql, f"mark missing: {m}"


def test_withheld_reason_enum_is_the_closed_set(sql: str):
    lower = sql.lower()
    assert "create type report_withheld_reason as enum" in lower
    for r in WITHHELD_REASONS:
        assert f"'{r}'" in sql, f"withheld_reason missing: {r}"


def test_core_columns_present(sql: str):
    lower = sql.lower()
    for col in ("bridge_id", "cycle_id", "assessment_id", "assessment_version",
                "rendered_at", "outcome", "marks", "withheld_reason", "artifact_ref"):
        assert col in lower, f"missing column: {col}"


def test_rendered_requires_an_artifact_ref_check(sql: str):
    # FR-9: a RENDERED row must carry an artifact_ref; a WITHHELD row may have NULL artifact_ref.
    lower = sql.lower()
    assert "rendered_has_artifact" in lower or \
        ("outcome" in lower and "artifact_ref is not null" in lower)


def test_withheld_requires_a_reason_check(sql: str):
    # A WITHHELD row must carry a withheld_reason; RENDERED/ERROR rows must not.
    lower = sql.lower()
    assert "withheld_has_reason" in lower or \
        ("withheld" in lower and "withheld_reason is not null" in lower)


def test_provenance_block_present_fr9_fr11(sql: str):
    # FR-9/FR-11: reproducible from exactly the pinned assessment version + source versions.
    lower = sql.lower()
    for col in ("assessment_id", "assessment_version", "source_analysis_ids",
                "standard_code", "standard_version", "template_version"):
        assert col in lower, f"missing provenance column: {col}"
    assert "bigint[]" in lower  # source_analysis_ids is an id array


def test_idempotency_unique_current_assessment_version(sql: str):
    # Only one CURRENT (non-superseded) artifact per (assessment_id, assessment_version).
    lower = sql.lower()
    assert "unique" in lower
    assert "assessment_id" in lower and "assessment_version" in lower
    assert "superseded_by is null" in lower  # partial index over current rows


def test_correction_chain_is_self_referential(sql: str):
    lower = sql.lower()
    assert "superseded_by" in lower
    assert "references report_artifacts" in lower


def test_correct_by_append_guard_present(sql: str):
    # Same discipline as risk_assessments: outcome/marks/artifact of a written row cannot be
    # mutated in place; only superseded_by may be stamped.
    lower = sql.lower()
    assert "before update on report_artifacts" in lower
    assert "correct-by-append" in lower


def test_history_is_permanent_delete_blocked(sql: str):
    lower = sql.lower()
    assert "before delete on report_artifacts" in lower
    assert "delete blocked" in lower


def test_no_timescaledb_only_standard_indexes(sql: str):
    # Constitution v2.1.0: Neon/Postgres, standard indexes only — no TimescaleDB hypertables.
    lower = sql.lower()
    assert "timescaledb" not in lower
    assert "create_hypertable" not in lower
