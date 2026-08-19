"""T202 — validated_readings migration: structural assertions.

[DB-DEP] No Supabase/Postgres locally, so the migration cannot be EXECUTED and the
CHECK constraints / correction-guard triggers cannot be live-verified here. What is
verifiable now: the file declares the six reading-statuses, the co-existing flags
(is_interpolated, clock_drift), provenance (source_raw_ids), and the correction chain
(superseded_by). This asserts the schema is written correctly, not live-enforced.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0002_validated_readings.sql"
)

# The six terminal reading-statuses (value/timeline axis).
SIX_STATUSES = ("OK", "INTERPOLATED", "SPIKE", "CORRUPT", "NO_DATA", "PENDING")


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_all_six_statuses_representable(sql: str):
    # The enum must contain exactly the six terminal statuses — no more, no fewer.
    lower = sql.lower()
    assert "create type reading_status as enum" in lower
    for status in SIX_STATUSES:
        assert f"'{status}'" in sql, f"reading_status missing: {status}"


def test_clock_drift_is_a_coexisting_flag_not_a_status(sql: str):
    # G4: clock_drift co-exists with ANY status — it is a boolean column, and must
    # NOT appear as a seventh enum value.
    assert "clock_drift" in sql
    assert "'CLOCK_DRIFT'" not in sql, "clock drift must be a flag, not a status"


def test_interpolated_flag_present(sql: str):
    assert "is_interpolated" in sql


def test_provenance_links_to_raw_ids(sql: str):
    # Constitution II/VI: every verdict traces to its raw source row(s).
    assert "source_raw_ids" in sql
    assert "bigint[]" in sql.lower()


def test_correction_chain_is_self_referential(sql: str):
    # FR-5: late-arrival recompute appends + supersedes; never overwrites.
    lower = sql.lower()
    assert "superseded_by" in lower
    assert "references validated_readings" in lower


def test_no_silent_overwrite_value_status_guarded(sql: str):
    # Operational constraint: the value/status/sensor_time of a written verdict
    # cannot be mutated in place — only superseded_by may be stamped.
    lower = sql.lower()
    assert "before update on validated_readings" in lower
    assert "correct-by-append" in lower


def test_history_is_permanent_delete_blocked(sql: str):
    lower = sql.lower()
    assert "before delete on validated_readings" in lower
    assert "delete blocked" in lower


def test_non_ok_requires_reason_for_audit(sql: str):
    # Auditability: any non-OK verdict carries an explanation.
    lower = sql.lower()
    assert "non_ok_has_reason" in lower


def test_sensor_time_drives_ordering(sql: str):
    # G4: sensor's own timestamp, aligned with raw_readings.
    assert "sensor_time" in sql
