"""D306 — per-table RLS policies (migration 0016 part B): the scoped-visibility rule itself.

[DB-DEP] No Neon locally. D305 turned RLS on + FORCED it (fail-closed: a table with RLS on and no
policy returns zero rows). This task writes the policies that open EXACTLY the current tenant's rows
back up. The rule is one predicate, applied everywhere:

    municipality_id = current_setting('app.current_municipality_id', true)

`municipalities` is the one exception — it has no municipality_id column, so it self-predicates on its
own PK: `id = current_setting('app.current_municipality_id', true)`.

Two policy directions per table (spec AC-4):
  * SELECT (USING)      — a read returns only rows of the scoped municipality;
  * INSERT (WITH CHECK) — a write may only create rows for the scoped municipality (you cannot insert
    a row attributed to a foreign tenant).

Fail-closed: `current_setting(..., true)` returns NULL when the GUC is unset (the `true` =
missing_ok), and `municipality_id = NULL` is never true, so an unscoped session sees zero rows rather
than erroring or seeing everything. Policies are granted to the single `bridgeguard_service` role.

What is verifiable now: the policy statements exist per table with the right predicate, direction,
GUC name, and role. The live "GUC=MUNI_A returns only A / unset returns zero / foreign INSERT
rejected" check runs in D601 against a seeded DB.

Ties to spec-002 FR-4 and AC-4.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0016_rls_policies.sql"
)

GUC = "app.current_municipality_id"
ROLE = "bridgeguard_service"

# Tables whose policy predicate is on the denormalized municipality_id column.
MUNICIPALITY_ID_TABLES = (
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
ALL_TABLES = ("municipalities",) + MUNICIPALITY_ID_TABLES


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


def test_part_b_section_present(norm: str):
    assert "part b" in norm


def test_uses_the_exact_guc_name(norm: str):
    # The GUC name is fixed: app.current_municipality_id (confirmed decision) — no vari/spelling drift.
    assert f"current_setting('{GUC}', true)" in norm


def test_every_table_has_a_select_policy(norm: str):
    for table in ALL_TABLES:
        m = re.search(rf"create policy \w+ on {table} for select", norm)
        assert m is not None, f"{table} must have a SELECT (USING) policy"


def test_every_table_has_an_insert_with_check_policy(norm: str):
    for table in ALL_TABLES:
        m = re.search(rf"create policy \w+ on {table} for insert[^;]*with check", norm)
        assert m is not None, f"{table} must have an INSERT policy with a WITH CHECK clause"


def test_municipality_id_tables_predicate_on_municipality_id(norm: str):
    # The denormalized single-equality predicate (plan §2), applied to both directions.
    for table in MUNICIPALITY_ID_TABLES:
        block = _table_block(norm, table)
        assert f"municipality_id = current_setting('{GUC}', true)" in block, (
            f"{table} policies must key on municipality_id = the GUC"
        )


def test_municipalities_self_predicates_on_its_pk(norm: str):
    # municipalities has no municipality_id column; it scopes on its own id.
    block = _table_block(norm, "municipalities")
    assert f"id = current_setting('{GUC}', true)" in block, (
        "municipalities must self-predicate on id (it has no municipality_id column)"
    )


def test_policies_granted_to_the_service_role(norm: str):
    # Policies bind the single application role.
    assert f"to {ROLE}" in norm


def test_fail_closed_missing_ok_true(norm: str):
    # current_setting(..., true): missing_ok=true => NULL on unset GUC => zero rows, not an error.
    assert "current_setting" in norm
    assert ", true)" in norm
    # a bare current_setting without the missing_ok flag would ERROR on unset — must not appear.
    assert re.search(r"current_setting\('app\.current_municipality_id'\)\s", norm) is None


def _table_block(norm: str, table: str) -> str:
    """Return the substring of the migration covering `table`'s policies (from its first policy to the
    next table's first policy, or end-of-file), so per-table predicate checks don't match a neighbour.
    """
    starts = [m.start() for m in re.finditer(rf"create policy \w+ on {table} ", norm)]
    assert starts, f"no policy found for {table}"
    start = starts[0]
    # find the earliest policy for any OTHER table after this table's block begins.
    others = [
        m.start()
        for m in re.finditer(r"create policy \w+ on (\w+) ", norm)
        if m.start() > starts[-1] and m.group(1) != table
    ]
    end = min(others) if others else len(norm)
    return norm[start:end]
