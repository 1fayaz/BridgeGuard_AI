"""D301 — tenant columns (migration 0015 part A): every tenant-scoped table gains municipality_id,
and the sensor-keyed tables gain bridge_id.

[DB-DEP] No Neon locally; the migration cannot be EXECUTED. What is verifiable now: the 0015 file
ALTERs each tenant-scoped table to ADD the denormalized `municipality_id` (the column the RLS
predicate keys on — plan §2), and ADDs `bridge_id` to the sensor-keyed tables that lack it
(raw_readings, validated_readings, analysis_results, sensor_status, decision_log). The judgment
tables (risk_assessments 0006, report_artifacts 0008, alert_dispatches 0010) already carry bridge_id
and are NOT re-added. Columns are added NULLABLE in part A; the hard FKs + NOT NULL are part B (D302),
per plan Open Item #4 (add nullable -> backfill -> NOT NULL + validate FK).

Ties to spec-002 FR-2 (sensor-keyed attribution) and FR-3 (bridge-keyed attribution).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0015_tenant_columns_and_fks.sql"
)

# Every tenant-scoped table must end up with a municipality_id column.
TENANT_TABLES = (
    "raw_readings",
    "validated_readings",
    "analysis_results",
    "sensor_status",
    "decision_log",
    "risk_assessments",
    "report_artifacts",
    "alert_dispatches",
)

# Sensor-keyed tables that lack bridge_id and must gain it here.
NEEDS_BRIDGE_ID = (
    "raw_readings",
    "validated_readings",
    "analysis_results",
    "sensor_status",
    "decision_log",
)

# Judgment tables already carry bridge_id (0006/0008/0010) — must NOT be re-added.
ALREADY_HAS_BRIDGE_ID = (
    "risk_assessments",
    "report_artifacts",
    "alert_dispatches",
)


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_every_tenant_table_gains_municipality_id(norm: str):
    for table in TENANT_TABLES:
        m = re.search(rf"alter table {table} add column[^;]*municipality_id", norm)
        assert m is not None, f"{table} must ADD COLUMN municipality_id"


def test_sensor_keyed_tables_gain_bridge_id(norm: str):
    for table in NEEDS_BRIDGE_ID:
        m = re.search(rf"alter table {table} add column[^;]*bridge_id", norm)
        assert m is not None, f"{table} must ADD COLUMN bridge_id (it only had sensor_id)"


def test_judgment_tables_bridge_id_not_re_added(norm: str):
    # A bridge_id ADD COLUMN on a table that already has it would fail live; assert we don't.
    for table in ALREADY_HAS_BRIDGE_ID:
        m = re.search(rf"alter table {table} add column[^;]*bridge_id", norm)
        assert m is None, f"{table} already has bridge_id — must not be re-added in 0015"


def test_columns_are_text(norm: str):
    # municipality_id / bridge_id are TEXT natural keys (confirmed decision).
    assert "municipality_id text" in norm
    assert "bridge_id text" in norm


def test_part_a_is_additive_no_data_loss(norm: str):
    # Part A only ADDs columns — no DROP, no data rewrite.
    assert "drop column" not in norm
    assert "drop table" not in norm


def test_part_a_columns_are_nullable_fk_deferred_to_part_b(norm: str):
    # Per plan Open Item #4: part A adds nullable columns; NOT NULL + hard FK are part B (D302).
    # So the ADD COLUMN statements in part A must NOT declare NOT NULL or REFERENCES yet.
    # (We check the municipality_id adds specifically.)
    adds = re.findall(r"alter table \w+ add column [^;]*municipality_id[^;]*;", norm)
    assert adds, "expected municipality_id ADD COLUMN statements"
    for stmt in adds:
        assert "not null" not in stmt, f"part A must add municipality_id nullable: {stmt}"
        assert "references" not in stmt, f"part A must not add the FK yet (D302): {stmt}"


def test_neon_no_timescaledb_header(norm: str):
    assert "neon" in norm
    assert "no timescaledb" in norm
    assert "create_hypertable" not in norm
    assert "[db-dep]" in norm


def test_header_documents_the_three_part_plan(norm: str):
    # The wiring migration is built across D301 (cols) / D302 (FKs+NOT NULL) / D304 (indexes).
    assert "part a" in norm
    assert "0015" in norm or "tenant" in norm
