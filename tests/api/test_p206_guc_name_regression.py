"""P206 — the GUC name, pinned against the migrations that read it.

Plan §0 calls this the layer's highest-risk carry-over, and the risk is not that the
name is hard to get right. It is that getting it wrong **does not raise**.

Spec 003's plan said `app.municipality_id`. Migrations 0015/0016/0017 say
`app.current_municipality_id`. If the API ever sets the former, every RLS policy
compares `municipality_id` against a GUC that was never set — `current_setting(..., true)`
returns NULL, `<col> = NULL` is not true, and **every table reads as empty**. No error,
no 500, no failing health check. Dashboards render "no bridges". Ingestion writes fail
their WITH CHECK. The system presents as a quiet Tuesday with no data, which is a state a
team can stare at for a long time before suspecting the tenancy GUC.

So this file does the one thing the other Phase 2 tests cannot: it reads the **actual
migration files** and asserts the Python constant matches what the database will
actually look up. Testing `GUC_NAME == "app.current_municipality_id"` alone is circular —
it pins a string against itself. The value is in the *pairing*.

Ties to tasks.md P206, spec AC-6, plan §0.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.db.scope import GUC_NAME, SET_SCOPE_SQL

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "db" / "migrations"

# Every migration whose policies or guards read the GUC.
GUC_MIGRATIONS = (
    "0015_tenant_columns_and_fks.sql",
    "0016_rls_policies.sql",
    "0017_device_credentials.sql",
)

# Names this has plausibly been, or plausibly will be, mistyped as.
WRONG_NAMES = (
    "app.municipality_id",       # Spec 003's plan. The documented near-miss.
    "app.tenant_id",
    "app.current_tenant_id",
    "app.municipality",
    "current_municipality_id",   # missing the required `app.` prefix
    "app.current_muncipality_id",  # transposition
)


@pytest.fixture(scope="module")
def migration_sql() -> dict[str, str]:
    out = {}
    for name in GUC_MIGRATIONS:
        path = MIGRATIONS / name
        assert path.is_file(), f"missing migration {name} — this guard needs it"
        out[name] = path.read_text(encoding="utf-8")
    return out


# ------------------------------------------------- the pairing that actually matters ---
def test_every_migration_policy_reads_the_name_the_api_sets(migration_sql):
    """The whole point of this file.

    Extracts each `current_setting('...')` call from the SQL and asserts every one names
    exactly the GUC the API writes. If either side is renamed alone, this fails — which
    is the only way to notice, since the runtime symptom is silence.
    """
    pattern = re.compile(r"current_setting\(\s*'([^']+)'")
    for name, sql in migration_sql.items():
        found = set(pattern.findall(sql))
        assert found, f"{name} reads no GUC at all — has the RLS predicate been removed?"
        assert found == {GUC_NAME}, (
            f"{name} reads {found}, but the API sets {GUC_NAME!r}. A mismatch here "
            "returns ZERO ROWS everywhere instead of raising."
        )


def test_the_api_sets_the_name_the_policies_read(migration_sql):
    """The same check from the other direction, against 0016 specifically."""
    assert GUC_NAME in migration_sql["0016_rls_policies.sql"]
    assert GUC_NAME in SET_SCOPE_SQL


def test_no_migration_mentions_a_wrong_name(migration_sql):
    for name, sql in migration_sql.items():
        for wrong in WRONG_NAMES:
            assert not re.search(rf"'{re.escape(wrong)}'", sql), (
                f"{name} references the wrong GUC {wrong!r}"
            )


@pytest.mark.parametrize("wrong", WRONG_NAMES)
def test_the_api_constant_is_not_a_wrong_name(wrong: str):
    assert GUC_NAME != wrong


def test_guc_name_is_exactly_this_string():
    """Deliberately literal. A rename must be a conscious edit to this line."""
    assert GUC_NAME == "app.current_municipality_id"


def test_guc_name_is_app_prefixed():
    """Postgres requires a dotted prefix for a custom GUC; a bare name errors on SET."""
    assert GUC_NAME.startswith("app.")
    assert GUC_NAME.count(".") == 1


# ------------------------------------------------------------------ TEXT, not uuid ---
def test_no_uuid_cast_in_the_api_statement():
    """The tenant key is `MUNI_A`. A `::uuid` cast raises on the real data."""
    assert "::uuid" not in SET_SCOPE_SQL.lower()
    assert "uuid" not in SET_SCOPE_SQL.lower()


def test_no_uuid_cast_in_any_policy(migration_sql):
    """The same on the SQL side: casting the GUC or the column would break the match."""
    for name, sql in migration_sql.items():
        for line in sql.splitlines():
            code = line.split("--", 1)[0]
            if "current_setting" in code:
                assert "::uuid" not in code.lower(), (
                    f"{name}: a uuid cast on the GUC comparison — the tenant key is "
                    f"TEXT: {line.strip()}"
                )


def test_the_tenant_column_is_declared_text_not_uuid():
    """0012's key type is what makes the TEXT decision binding downstream."""
    sql = (MIGRATIONS / "0012_municipalities.sql").read_text(encoding="utf-8").lower()
    assert re.search(r"\bid\s+text\b", sql), (
        "municipalities.id must be TEXT — the GUC is compared against it uncast"
    )
    assert not re.search(r"\bid\s+uuid\b", sql)


# --------------------------------------------------------- transaction-local, still ---
def test_the_api_statement_is_transaction_local():
    """`is_local => true`. Session scope is the pooled-connection leak (P205)."""
    assert "set_config" in SET_SCOPE_SQL.lower()
    assert SET_SCOPE_SQL.rstrip().rstrip(")").rstrip().endswith("true")


def test_the_api_statement_is_parameterized():
    """$1, not an interpolated tenant id. This is the tenancy boundary."""
    assert "$1" in SET_SCOPE_SQL


def test_every_policy_uses_missing_ok_true(migration_sql):
    """`current_setting(name, true)` → NULL when unset → zero rows.

    Without the second argument Postgres RAISES on an unset GUC. That sounds safer and
    is not: any caller that catches the error and proceeds gets an unfiltered read.
    Zero rows cannot be caught into a leak.
    """
    calls = re.compile(r"current_setting\(\s*'[^']+'\s*(,\s*true)?\s*\)")
    for name, sql in migration_sql.items():
        for line in sql.splitlines():
            code = line.split("--", 1)[0]
            if "current_setting" not in code:
                continue
            for match in calls.finditer(code):
                assert match.group(1), (
                    f"{name}: current_setting without missing_ok=true: {line.strip()}"
                )
