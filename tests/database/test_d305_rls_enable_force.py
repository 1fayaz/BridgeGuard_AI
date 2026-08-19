"""D305 — RLS enable + FORCE (migration 0016 part A): isolation is switched on and un-bypassable.

[DB-DEP] No Neon locally. Multi-tenant isolation (spec AC-4) is the load-bearing safety property of
the database layer: municipality A must receive ZERO rows of municipality B, even when a query omits
a scope filter. Postgres RLS delivers that — but only once a table has ROW LEVEL SECURITY ENABLED,
and the policies only bind the table OWNER once it is also FORCED (by default the owner and any
BYPASSRLS role skip policies entirely). BridgeGuard's single `bridgeguard_service` role owns these
tables, so without FORCE the very role the app connects as would silently see every tenant's data.

What is verifiable now: 0016 part A issues both `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL
SECURITY` on all eleven tenant-scoped tables. Part B (D306) adds the per-table policies. This file
checks only that the switch is thrown and forced on every table — a table missing FORCE is a silent
isolation hole, so the test fails if either statement is absent for any table.

Ties to spec-002 FR-4 (RLS) and AC-4 (A sees zero rows of B).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0016_rls_policies.sql"
)

# All eleven tenant-scoped tables: the tenancy foundation (municipalities/bridges/sensors) plus the
# eight data tables that carry a denormalized municipality_id (0015).
RLS_TABLES = (
    "municipalities",
    "bridges",
    "sensors",
    "sensor_status",
    "raw_readings",
    "validated_readings",
    "analysis_results",
    "decision_log",
    "risk_assessments",
    "report_artifacts",
    "alert_dispatches",
)


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_part_a_section_present(norm: str):
    assert "part a" in norm


def test_every_table_enables_rls(norm: str):
    for table in RLS_TABLES:
        assert re.search(
            rf"alter table {table} enable row level security", norm
        ), f"{table} must ENABLE ROW LEVEL SECURITY"


def test_every_table_forces_rls(norm: str):
    # FORCE is the part that binds the table-owning bridgeguard_service role — without it the app's
    # own role bypasses the policies and isolation is a no-op.
    for table in RLS_TABLES:
        assert re.search(
            rf"alter table {table} force row level security", norm
        ), f"{table} must FORCE ROW LEVEL SECURITY (owner must not bypass isolation)"


def test_neon_no_timescaledb_header(norm: str):
    assert "neon" in norm
    assert "no timescaledb" in norm
    assert "create_hypertable" not in norm
    assert "[db-dep]" in norm
