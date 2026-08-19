"""D703 — FakeTenantStore RLS-scoping parity: [DB-DEP] tests get real tenant isolation without Neon.

[DB-DEP] No Neon locally, so migration 0016's row-level security cannot be EXERCISED against a live
connection. But the whole point of the fakes (like FakeRiskStore / FakeAlertStore) is that logic
tests exercise the SAME guarantees the DB will enforce. D703 gives FakeTenantStore the read-scoping
half of that: a settable "current municipality" context — the in-memory analogue of the
`app.current_municipality_id` GUC (plan §2) — and scoped readers that return ONLY the current
tenant's rows, exactly as the 0016 SELECT policies do.

The two RLS guarantees mirrored here (spec AC-4):
  * with a scope SET to MUNI_A, scoped reads return only MUNI_A's bridges/sensors — zero of MUNI_B's;
  * with the scope UNSET, scoped reads return ZERO rows (fail-closed) — a forgotten scope leaks
    nothing, never everything (the `current_setting(..., true)` -> NULL -> no match behaviour).

The append/supersede + orphan-rejection guarantees were already established (D101-D303); this test
re-confirms orphan rejection alongside the new scoping so the acceptance is covered in one place.

Ties to spec-002 §Testability and AC-4.
"""
from __future__ import annotations

import pytest

from db.tenant_store import (
    FakeTenantStore,
    UnknownMunicipalityError,
    UnknownBridgeError,
    ScopeNotSetError,
)


def _seed() -> FakeTenantStore:
    s = FakeTenantStore()
    s.add_municipality("MUNI_A", name="Alpha City")
    s.add_municipality("MUNI_B", name="Beta Town")
    s.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span")
    s.add_bridge("BRIDGE_A2", municipality_id="MUNI_A", name="South Span")
    s.add_bridge("BRIDGE_B1", municipality_id="MUNI_B", name="East Span")
    s.add_sensor("S_A1", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    s.add_sensor("S_B1", bridge_id="BRIDGE_B1", sensor_type="accelerometer")
    return s


# --- scoped reads return only the current tenant's rows -----------------------------------------
def test_scoped_bridges_returns_only_current_tenant():
    s = _seed()
    s.set_current_municipality("MUNI_A")
    got = {b.id for b in s.scoped_bridges()}
    assert got == {"BRIDGE_A1", "BRIDGE_A2"}, "MUNI_A scope must see only MUNI_A bridges"
    assert "BRIDGE_B1" not in got, "zero rows of MUNI_B (AC-4)"


def test_scoped_sensors_returns_only_current_tenant():
    s = _seed()
    s.set_current_municipality("MUNI_A")
    assert {sen.id for sen in s.scoped_sensors()} == {"S_A1"}
    s.set_current_municipality("MUNI_B")
    assert {sen.id for sen in s.scoped_sensors()} == {"S_B1"}


def test_flipping_scope_flips_visibility():
    s = _seed()
    s.set_current_municipality("MUNI_B")
    assert {b.id for b in s.scoped_bridges()} == {"BRIDGE_B1"}
    # the mirror direction, same store.
    s.set_current_municipality("MUNI_A")
    assert {b.id for b in s.scoped_bridges()} == {"BRIDGE_A1", "BRIDGE_A2"}


# --- fail-closed when the scope is unset --------------------------------------------------------
def test_unset_scope_reads_zero_rows_not_all():
    s = _seed()
    # no scope set: the GUC-unset -> NULL -> no match behaviour. Zero rows, NEVER all.
    with pytest.raises(ScopeNotSetError):
        s.scoped_bridges()
    with pytest.raises(ScopeNotSetError):
        s.scoped_sensors()


def test_clearing_scope_restores_fail_closed():
    s = _seed()
    s.set_current_municipality("MUNI_A")
    assert s.scoped_bridges()  # visible while scoped
    s.clear_scope()
    with pytest.raises(ScopeNotSetError):
        s.scoped_bridges()


def test_scope_to_unknown_municipality_rejected():
    s = _seed()
    # scoping to a tenant that doesn't exist is a caller error, not a silent empty read.
    with pytest.raises(UnknownMunicipalityError):
        s.set_current_municipality("MUNI_GHOST")


# --- orphan rejection still holds (append/supersede guarantees from D101-D303) -------------------
def test_orphan_bridge_and_sensor_still_rejected():
    s = _seed()
    with pytest.raises(UnknownMunicipalityError):
        s.add_bridge("BRIDGE_X", municipality_id="NOPE", name="Nowhere")
    with pytest.raises(UnknownBridgeError):
        s.add_sensor("S_X", bridge_id="NOPE", sensor_type="accelerometer")


def test_current_scope_accessor_reflects_state():
    s = _seed()
    assert s.current_municipality is None
    s.set_current_municipality("MUNI_A")
    assert s.current_municipality == "MUNI_A"
    s.clear_scope()
    assert s.current_municipality is None
