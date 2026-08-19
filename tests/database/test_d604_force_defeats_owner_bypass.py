"""D604 — FORCE defeats the owner/BYPASS bypass: isolation holds even for the table owner (AC-4).

[DB-DEP] No Neon locally. The live proof — connect as the table OWNER (bridgeguard_service owns these
tables), SET a scope, SELECT, and still get only in-scope rows — runs against a seeded Neon instance.
This is the subtle half of RLS that a naive setup gets wrong: by default a table's OWNER and any
BYPASSRLS role SKIP row-level policies entirely. BridgeGuard's single bridgeguard_service role OWNS
every tenant table AND is the role the app connects as, so ENABLE alone would leave the app's own
connection seeing every tenant's rows. `ALTER TABLE ... FORCE ROW LEVEL SECURITY` removes the owner
exemption, so the policies bind the owner too (plan §2).

What is verifiable now: FORCE (not merely ENABLE) is declared on ALL eleven tenant-scoped tables in
0016 — a table with ENABLE but no FORCE would be a silent owner-visible hole. The behavioural proof
(an owner connection actually being filtered) is the Neon run; here we prove the switch that makes it
so is thrown on every table.

Ties to spec-002 FR-4, AC-4, and plan §2.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIG = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0016_rls_policies.sql"
)

TENANT_TABLES = (
    "municipalities", "bridges", "sensors",
    "raw_readings", "validated_readings", "analysis_results", "sensor_status", "decision_log",
    "risk_assessments", "report_artifacts", "alert_dispatches",
)


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIG.read_text(encoding="utf-8").lower())


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_force_declared_on_every_table(norm: str, table: str):
    assert re.search(rf"alter table {table} force row level security", norm), (
        f"{table} must FORCE RLS — ENABLE alone leaves the owner bridgeguard_service unfiltered"
    )


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_enable_and_force_are_both_present(norm: str, table: str):
    # Both are required: ENABLE turns RLS on; FORCE makes it bind the owner. Neither alone is enough.
    assert re.search(rf"alter table {table} enable row level security", norm), f"{table} needs ENABLE"
    assert re.search(rf"alter table {table} force row level security", norm), f"{table} needs FORCE"


def test_force_count_matches_table_count(norm: str):
    # Exactly the eleven tenant tables are FORCED — no table silently omitted.
    forced = set(re.findall(r"alter table (\w+) force row level security", norm))
    assert forced == set(TENANT_TABLES), (
        f"FORCE must cover exactly the eleven tenant tables; got {sorted(forced)}"
    )


def test_no_table_bypasses_rls():
    # Guard against an accidental escape hatch: no EXECUTABLE statement may grant BYPASSRLS or
    # DISABLE/UN-FORCE RLS. The header prose legitimately *mentions* BYPASSRLS to explain why FORCE is
    # needed, so we scan only NON-COMMENT lines (a real statement, not the explanatory word).
    code = "\n".join(
        line for line in MIG.read_text(encoding="utf-8").lower().splitlines()
        if not line.strip().startswith("--")
    )
    assert "bypassrls" not in code, "no executable statement may grant BYPASSRLS (defeats FORCE)"
    assert "no force row level security" not in code
    assert "disable row level security" not in code
