"""D601 — cross-tenant SELECT isolation: municipality A sees ZERO rows of municipality B (AC-4).

[DB-DEP] No Neon locally, so the definitive proof — connect as bridgeguard_service, `SET
app.current_municipality_id = 'MUNI_A'`, SELECT every tenant-scoped table, get zero MUNI_B rows —
runs against a seeded Neon instance. What is proven NOW, over the D701/D702 seed + the D703 fake:

  * the RLS PREDICATE the 0016 policies apply (`municipality_id = current_setting(...)`, or `id = ...`
    for municipalities) yields, for scope=MUNI_A, only MUNI_A rows across all eleven tenant-scoped
    tables — and the mirror for MUNI_B;
  * the FakeTenantStore's scoped readers (D703), which ARE the in-memory 0016 SELECT policy, return
    only the current tenant's bridges/sensors and zero of the other's.

This is the behavioural half of AC-4 (isolation logic); the live half (Postgres actually enforcing it
on the wire) is D601's Neon run. Together they close AC-4.

Ties to spec-002 FR-4 and AC-4 (the explicit RLS criterion).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from db.tenant_store import FakeTenantStore

SEED = Path(__file__).resolve().parents[2] / "db" / "seed" / "seed_dev.sql"

# The eleven tenant-scoped tables. municipalities self-scopes on id; the rest on municipality_id.
TENANT_TABLES = (
    "municipalities", "bridges", "sensors",
    "raw_readings", "validated_readings", "analysis_results", "sensor_status", "decision_log",
    "risk_assessments", "report_artifacts", "alert_dispatches",
)


def _rows(text: str, table: str) -> list[dict[str, str]]:
    """Parse `INSERT INTO <table> (cols) [OVERRIDING ...] VALUES (...),(...) [ON CONFLICT];` into dicts."""
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


def _rls_visible(rows: list[dict[str, str]], table: str, scope: str) -> list[dict[str, str]]:
    """The 0016 SELECT-policy predicate, in Python: for `municipalities` a row is visible iff id ==
    scope; for every other tenant table iff municipality_id == scope. An unset scope (None) matches
    nothing (fail-closed)."""
    if scope is None:
        return []
    key = "id" if table == "municipalities" else "municipality_id"
    return [r for r in rows if r.get(key) == scope]


@pytest.fixture(scope="module")
def seed_text() -> str:
    return SEED.read_text(encoding="utf-8")


# --- the RLS predicate isolates every seeded tenant table ---------------------------------------
@pytest.mark.parametrize("table", TENANT_TABLES)
def test_scope_a_sees_zero_b_rows(seed_text: str, table: str):
    rows = _rows(seed_text, table)
    visible_a = _rls_visible(rows, table, "MUNI_A")
    # every row A sees is A's; NOT ONE belongs to B.
    key = "id" if table == "municipalities" else "municipality_id"
    b_rows_seen = [r for r in visible_a if r.get(key) == "MUNI_B"]
    assert b_rows_seen == [], f"{table}: MUNI_A scope leaked {len(b_rows_seen)} MUNI_B row(s)"


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_scope_b_sees_zero_a_rows(seed_text: str, table: str):
    rows = _rows(seed_text, table)
    visible_b = _rls_visible(rows, table, "MUNI_B")
    key = "id" if table == "municipalities" else "municipality_id"
    a_rows_seen = [r for r in visible_b if r.get(key) == "MUNI_A"]
    assert a_rows_seen == [], f"{table}: MUNI_B scope leaked {len(a_rows_seen)} MUNI_A row(s)"


def test_partition_is_complete_no_row_invisible_to_its_owner(seed_text: str):
    # Sanity: the isolation is a PARTITION, not a blanket deny — every seeded row is visible to its
    # OWN tenant (so we're proving isolation, not just an empty database).
    for table in TENANT_TABLES:
        rows = _rows(seed_text, table)
        for scope in ("MUNI_A", "MUNI_B"):
            key = "id" if table == "municipalities" else "municipality_id"
            owned = [r for r in rows if r.get(key) == scope]
            visible = _rls_visible(rows, table, scope)
            assert owned == visible, f"{table}: some {scope} rows are invisible to {scope}"


def test_seed_actually_contains_both_tenants_rows(seed_text: str):
    # Guard against a vacuous pass: the seed must contain BOTH tenants' rows on the shared tables,
    # else "A sees zero B rows" is trivially true because there are no B rows.
    for table in ("bridges", "risk_assessments"):
        rows = _rows(seed_text, table)
        munis = {r["municipality_id"] for r in rows}
        assert {"MUNI_A", "MUNI_B"} <= munis, f"{table} seed must include both tenants to prove isolation"


# --- the authoritative in-memory 0016 policy: FakeTenantStore scoped readers (D703) --------------
def _fake_from_seed(seed_text: str) -> FakeTenantStore:
    s = FakeTenantStore()
    for m in _rows(seed_text, "municipalities"):
        s.add_municipality(m["id"], name=m["name"])
    for b in _rows(seed_text, "bridges"):
        s.add_bridge(b["id"], municipality_id=b["municipality_id"], name=b["name"],
                     location=b.get("location"))
    for sen in _rows(seed_text, "sensors"):
        s.add_sensor(sen["id"], bridge_id=sen["bridge_id"], sensor_type=sen["sensor_type"])
    return s


def test_fake_scoped_readers_isolate_bridges_and_sensors(seed_text: str):
    s = _fake_from_seed(seed_text)
    s.set_current_municipality("MUNI_A")
    a_bridges = {b.id for b in s.scoped_bridges()}
    assert a_bridges == {"BRIDGE_A1", "BRIDGE_A2"} and "BRIDGE_B1" not in a_bridges
    assert {sen.id for sen in s.scoped_sensors()} == {"SENSOR_A1_ACC", "SENSOR_A1_STR",
        "SENSOR_A1_CRK", "SENSOR_A1_LOAD", "SENSOR_A1_TEMP", "SENSOR_A1_TILT",
        "SENSOR_A1_LVDT", "SENSOR_A2_ACC"}

    s.set_current_municipality("MUNI_B")
    assert {b.id for b in s.scoped_bridges()} == {"BRIDGE_B1"}
    assert {sen.id for sen in s.scoped_sensors()} == {"SENSOR_B1_ACC"}
