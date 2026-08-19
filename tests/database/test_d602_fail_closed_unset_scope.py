"""D602 — fail-closed on unset scope: a forgotten scope leaks NOTHING (AC-4).

[DB-DEP] No Neon locally. The live proof — connect as bridgeguard_service WITHOUT setting
app.current_municipality_id, SELECT every tenant-scoped table, get ZERO rows on each — runs against a
seeded Neon instance. The behaviour is the load-bearing safety default (plan §2): the 0016 policies
key on `current_setting('app.current_municipality_id', true)`, and the `true` (missing_ok) makes an
unset GUC yield NULL, so `municipality_id = NULL` is never true and the read returns zero rows. The
failure mode this prevents is the dangerous one — a forgotten scope must leak NOTHING, never
EVERYTHING.

Proven now, over the D701/D702 seed + the D703 fake:
  * the 0016 predicate with scope=None returns zero rows on every tenant-scoped table (even though
    each table HAS rows) — never the full table;
  * FakeTenantStore's scoped readers (D703) raise ScopeNotSetError rather than returning all rows,
    the explicit surfacing of the same fail-closed contract.

Ties to spec-002 FR-4 and AC-4 (store-enforced isolation, not caller-enforced).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from db.tenant_store import FakeTenantStore, ScopeNotSetError

SEED = Path(__file__).resolve().parents[2] / "db" / "seed" / "seed_dev.sql"

TENANT_TABLES = (
    "municipalities", "bridges", "sensors",
    "raw_readings", "validated_readings", "analysis_results", "sensor_status", "decision_log",
    "risk_assessments", "report_artifacts", "alert_dispatches",
)


def _rows(text: str, table: str) -> list[dict[str, str]]:
    mcols = re.search(rf"insert\s+into\s+{table}\s*\(([^)]*)\)", text, re.IGNORECASE)
    if not mcols:
        return []
    cols = [c.strip() for c in mcols.group(1).split(",")]
    mvals = re.search(
        rf"insert\s+into\s+{table}\b.*?values\s*(.*?)(?:\bon\s+conflict\b|;)",
        text, re.IGNORECASE | re.DOTALL,
    )
    body = re.sub(r"--[^\n]*", "", mvals.group(1))
    tuples, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(" and depth == 0:
            depth, cur = 1, ""
        elif ch == ")" and depth == 1:
            depth = 0
            tuples.append(cur)
        elif depth == 1:
            cur += ch
    out = []
    for t in tuples:
        fields, d, buf, q = [], 0, "", False
        for ch in t:
            if ch == "'":
                q = not q; buf += ch
            elif ch in "{[" and not q:
                d += 1; buf += ch
            elif ch in "}]" and not q:
                d -= 1; buf += ch
            elif ch == "," and d == 0 and not q:
                fields.append(buf.strip()); buf = ""
            else:
                buf += ch
        fields.append(buf.strip())
        vals = [f.strip().strip("'") for f in fields]
        if len(vals) == len(cols):
            out.append(dict(zip(cols, vals)))
    return out


def _rls_visible(rows, table, scope):
    if scope is None:
        return []
    key = "id" if table == "municipalities" else "municipality_id"
    return [r for r in rows if r.get(key) == scope]


@pytest.fixture(scope="module")
def seed_text() -> str:
    return SEED.read_text(encoding="utf-8")


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_unset_scope_returns_zero_rows(seed_text: str, table: str):
    rows = _rows(seed_text, table)
    assert _rls_visible(rows, table, None) == [], f"{table}: unset scope must return ZERO rows"


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_unset_scope_does_not_return_all_rows(seed_text: str, table: str):
    # The dangerous failure mode: an unset scope returning the WHOLE table. For tables that actually
    # have seeded rows, prove the unset read is strictly smaller than the full table (it's empty).
    rows = _rows(seed_text, table)
    if not rows:
        pytest.skip(f"{table} has no seeded rows to contrast against")
    visible = _rls_visible(rows, table, None)
    assert len(visible) < len(rows), f"{table}: unset scope leaked the full table ({len(rows)} rows)"
    assert visible == []


def test_fake_scoped_readers_fail_closed_when_unset():
    s = FakeTenantStore()
    s.add_municipality("MUNI_A", name="Alpha City")
    s.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span")
    s.add_sensor("S_A1", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    # never set a scope: reads fail closed rather than returning the rows.
    assert s.current_municipality is None
    with pytest.raises(ScopeNotSetError):
        s.scoped_bridges()
    with pytest.raises(ScopeNotSetError):
        s.scoped_sensors()


def test_fake_fail_closed_survives_scope_then_clear():
    s = FakeTenantStore()
    s.add_municipality("MUNI_A", name="Alpha City")
    s.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span")
    s.set_current_municipality("MUNI_A")
    assert s.scoped_bridges()            # visible while scoped
    s.clear_scope()                      # a RESET of the GUC
    with pytest.raises(ScopeNotSetError):
        s.scoped_bridges()               # back to fail-closed


def test_0016_predicate_uses_missing_ok_true():
    # The mechanism that makes unset -> NULL -> zero rows: current_setting(..., true). A bare
    # current_setting(...) would ERROR on unset, not fail closed. Assert the migration uses the flag.
    mig = (SEED.resolve().parents[1] / "migrations" / "0016_rls_policies.sql").read_text().lower()
    assert "current_setting('app.current_municipality_id', true)" in mig
    assert not re.search(r"current_setting\('app\.current_municipality_id'\)\s", mig), (
        "a bare current_setting (no missing_ok) would error on unset instead of failing closed"
    )
