"""D304 — municipality_id index pass (migration 0015 part C): the RLS predicate is index-backed.

[DB-DEP] No Neon locally. RLS keys every tenant read on `municipality_id = current_setting(...)`
(plan §2), and the overview read model filters the same way. A denormalized single-column equality
predicate is only cheap if it is index-backed — otherwise every RLS-filtered query is a seq scan.
What is verifiable now: 0015 part C adds a B-tree `(municipality_id)` index to each of the eight
tenant-scoped tables that gained the column in part A (bridges already carries its own
`idx_bridges_municipality` from 0013; municipalities is keyed on its own PK `id`; sensors is
bridge-keyed). Standard B-tree only — no TimescaleDB (v2.1.0).

Ties to spec-002 FR-4 (RLS) and FR-12 (fast municipality overview backed by an index).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0015_tenant_columns_and_fks.sql"
)

# The eight tables that gain a denormalized municipality_id in 0015 part A and therefore need the
# RLS-predicate index here.
INDEXED_TABLES = (
    "raw_readings",
    "validated_readings",
    "analysis_results",
    "sensor_status",
    "decision_log",
    "risk_assessments",
    "report_artifacts",
    "alert_dispatches",
)


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


def test_part_c_section_present(norm: str):
    assert "part c" in norm


def test_every_tenant_table_has_a_municipality_index(norm: str):
    for table in INDEXED_TABLES:
        m = re.search(
            rf"create index (if not exists )?\w+ on {table} \(municipality_id\)", norm
        )
        assert m is not None, f"{table} must have a B-tree (municipality_id) index"


def test_indexes_are_idempotent(norm: str):
    # Migrations in this repo create indexes IF NOT EXISTS so a re-run is safe.
    for table in INDEXED_TABLES:
        m = re.search(
            rf"create index if not exists \w+ on {table} \(municipality_id\)", norm
        )
        assert m is not None, f"{table}'s municipality index must be CREATE INDEX IF NOT EXISTS"


def test_standard_btree_no_timescaledb(norm: str):
    # No hypertable / TimescaleDB index families — standard B-tree only (v2.1.0).
    assert "create_hypertable" not in norm
    assert "using gin" not in norm  # municipality_id is a scalar TEXT equality, not a GIN target
