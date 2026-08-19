"""D303 — municipality_id consistency guard (migration 0015): the denormalized copy can't drift.

[DB-DEP] No Neon locally. The denormalized municipality_id / bridge_id (added in 0015 for a
single-equality RLS predicate, plan §2) are a copy of what the sensor_id/bridge_id FK chain already
determines. A copy can drift; this guard makes drift impossible. What is verifiable now: 0015
declares BEFORE INSERT OR UPDATE trigger functions that reject a row whose denormalized tenant
columns disagree with the chain:
  * sensor-keyed rows: bridge_id must equal sensors.bridge_id for sensor_id, AND municipality_id must
    equal bridges.municipality_id for that bridge;
  * bridge-keyed (judgment) rows: municipality_id must equal bridges.municipality_id for bridge_id.
A CHECK cannot subquery, so this is a trigger (not a column CHECK). The FakeTenantStore mirrors it.

Ties to spec-002 FR-2/FR-3 (attribution is trustworthy — the denormalized value is provably the one
the chain yields).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0015_tenant_columns_and_fks.sql"
)

SENSOR_KEYED = ("raw_readings", "validated_readings", "analysis_results", "sensor_status", "decision_log")
JUDGMENT = ("risk_assessments", "report_artifacts", "alert_dispatches")


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


# --- migration: the consistency-guard trigger functions + triggers ------------------------------
def test_guard_functions_declared(norm: str):
    # Two reusable guard functions (sensor-keyed shape + bridge-keyed shape).
    assert "tenant_consistency" in norm, "expected a tenant-consistency guard function"
    # they must query the chain tables to compare the denormalized copy against the source.
    assert "from sensors" in norm
    assert "from bridges" in norm


def test_guard_raises_on_mismatch(norm: str):
    # The guard raises when the denormalized value disagrees with the chain.
    assert "raise exception" in norm
    assert "is distinct from" in norm or "<>" in norm
    # the message names the drift it prevents.
    assert "municipality" in norm and ("consistent" in norm or "drift" in norm or "disagree" in norm or "match" in norm)


def test_sensor_keyed_tables_have_a_consistency_trigger(norm: str):
    for table in SENSOR_KEYED:
        m = re.search(rf"before insert or update on {table}[^;]*tenant_consistency", norm)
        assert m is not None, f"{table} must have a BEFORE INSERT OR UPDATE tenant-consistency trigger"


def test_judgment_tables_have_a_consistency_trigger(norm: str):
    for table in JUDGMENT:
        m = re.search(rf"before insert or update on {table}[^;]*tenant_consistency", norm)
        assert m is not None, f"{table} must have a BEFORE INSERT OR UPDATE tenant-consistency trigger"


def test_sensor_guard_checks_bridge_hop_too(norm: str):
    # The sensor-keyed guard checks BOTH hops: bridge_id vs sensors, municipality_id vs bridges.
    assert "new.bridge_id" in norm
    assert "new.municipality_id" in norm
    assert "new.sensor_id" in norm


# --- FakeTenantStore mirror ---------------------------------------------------------------------
def _store():
    from db.tenant_store import FakeTenantStore

    s = FakeTenantStore()
    s.add_municipality("MUNI_A", name="Alpha City")
    s.add_municipality("MUNI_B", name="Beta Town")
    s.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span")
    s.add_bridge("BRIDGE_B1", municipality_id="MUNI_B", name="East Span")
    s.add_sensor("S1", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    return s


def test_consistent_sensor_row_accepted():
    store = _store()
    # S1 -> BRIDGE_A1 -> MUNI_A : a matching denormalized pair is fine.
    store.check_tenant_consistency(sensor_id="S1", bridge_id="BRIDGE_A1", municipality_id="MUNI_A")


def test_wrong_bridge_rejected():
    from db.tenant_store import TenantConsistencyError

    store = _store()
    # S1 actually belongs to BRIDGE_A1; claiming BRIDGE_B1 is drift.
    with pytest.raises(TenantConsistencyError):
        store.check_tenant_consistency(sensor_id="S1", bridge_id="BRIDGE_B1", municipality_id="MUNI_B")


def test_wrong_municipality_rejected():
    from db.tenant_store import TenantConsistencyError

    store = _store()
    # Correct bridge, but a municipality that isn't the bridge's owner is drift.
    with pytest.raises(TenantConsistencyError):
        store.check_tenant_consistency(sensor_id="S1", bridge_id="BRIDGE_A1", municipality_id="MUNI_B")


def test_bridge_keyed_consistency_accepted_and_rejected():
    from db.tenant_store import TenantConsistencyError

    store = _store()
    # A judgment row carries only bridge_id + municipality_id.
    store.check_bridge_tenant_consistency(bridge_id="BRIDGE_A1", municipality_id="MUNI_A")
    with pytest.raises(TenantConsistencyError):
        store.check_bridge_tenant_consistency(bridge_id="BRIDGE_A1", municipality_id="MUNI_B")
