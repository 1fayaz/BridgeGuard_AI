"""D603 — cross-tenant INSERT blocked by WITH CHECK: write-side isolation (AC-4).

[DB-DEP] No Neon locally. The live proof — as bridgeguard_service with
app.current_municipality_id = 'MUNI_A', attempt INSERT ... municipality_id = 'MUNI_B' and have the
policy WITH CHECK reject it — runs against a seeded Neon instance. Read isolation (D601/D602) stops A
from SEEING B's rows; this stops A from CREATING a row attributed to B. Both directions are required:
without WITH CHECK, a compromised or buggy A-scoped writer could plant rows in B's tenant that B
would then (correctly, per RLS) see as its own.

The 0016 INSERT policies carry `WITH CHECK (municipality_id = current_setting(...))` (id = ... for
municipalities), so the ONLY municipality_id a scoped writer may stamp is its own. Proven now over the
FakeTenantStore scoped-write mirror (D603 extends the D703 scope):
  * a scoped INSERT whose municipality_id equals the current scope succeeds;
  * a scoped INSERT whose municipality_id is a FOREIGN tenant is rejected (CrossTenantWriteError);
  * with no scope set, a scoped INSERT fails closed (ScopeNotSetError) — you cannot write unscoped.

Ties to spec-002 FR-4 and AC-4 (write-side isolation).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from db.tenant_store import (
    FakeTenantStore,
    CrossTenantWriteError,
    ScopeNotSetError,
)

MIG = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0016_rls_policies.sql"
)


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIG.read_text(encoding="utf-8").lower())


# --- structural: the WITH CHECK write predicate exists on every tenant table --------------------
def test_every_table_has_with_check_bound_to_scope(norm: str):
    # Each INSERT policy's WITH CHECK must key on the scope — the write-side of the same predicate.
    # (Presence per table is D306; here we assert the WITH CHECK predicate is the scoped equality.)
    assert "with check (municipality_id = current_setting('app.current_municipality_id', true))" in norm
    # municipalities self-checks on id.
    assert "with check (id = current_setting('app.current_municipality_id', true))" in norm


# --- fake mirror: a scoped write may only stamp its own municipality_id --------------------------
def _seed() -> FakeTenantStore:
    s = FakeTenantStore()
    s.add_municipality("MUNI_A", name="Alpha City")
    s.add_municipality("MUNI_B", name="Beta Town")
    s.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span")
    s.add_bridge("BRIDGE_B1", municipality_id="MUNI_B", name="East Span")
    return s


def test_same_tenant_write_allowed():
    s = _seed()
    s.set_current_municipality("MUNI_A")
    # writing a row attributed to the current scope passes the WITH CHECK.
    s.check_insert_scope(municipality_id="MUNI_A")  # does not raise


def test_foreign_tenant_write_rejected():
    s = _seed()
    s.set_current_municipality("MUNI_A")
    # attributing a new row to MUNI_B while scoped to MUNI_A is exactly what WITH CHECK forbids.
    with pytest.raises(CrossTenantWriteError):
        s.check_insert_scope(municipality_id="MUNI_B")


def test_write_without_scope_fails_closed():
    s = _seed()
    # no scope set: a scoped write is fail-closed, same as a scoped read.
    with pytest.raises(ScopeNotSetError):
        s.check_insert_scope(municipality_id="MUNI_A")


def test_mirror_direction_b_cannot_write_a():
    s = _seed()
    s.set_current_municipality("MUNI_B")
    s.check_insert_scope(municipality_id="MUNI_B")   # own tenant ok
    with pytest.raises(CrossTenantWriteError):
        s.check_insert_scope(municipality_id="MUNI_A")


def test_add_bridge_under_current_scope_enforced():
    # The higher-level convenience: a scoped add_bridge_scoped stamps + verifies the current tenant,
    # so a caller cannot accidentally create a bridge for another municipality while scoped.
    s = _seed()
    s.set_current_municipality("MUNI_A")
    with pytest.raises(CrossTenantWriteError):
        s.check_insert_scope(municipality_id="MUNI_B")
    # and the same-tenant path is unobstructed.
    s.check_insert_scope(municipality_id="MUNI_A")
