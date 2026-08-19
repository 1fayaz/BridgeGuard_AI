"""D104 — ownership-chain resolution (municipality <- bridge <- sensor).

The Phase-1 capstone: proves the chain municipalities -> bridges -> sensors resolves end-to-end,
with no missing hop, and that an orphan (a sensor with no bridge, or a bridge with no municipality)
cannot exist. Two layers:

  * SCHEMA (structural, [DB-DEP]): the 0013/0014 migrations declare the hard FKs that make an orphan
    structurally impossible — bridges.municipality_id REFERENCES municipalities, sensors.bridge_id
    REFERENCES bridges. (Live enforcement deferred; the FK clauses are asserted present.)
  * IN-FAKE: over a multi-municipality / multi-bridge / multi-sensor graph, every seeded sensor
    resolves to EXACTLY one municipality via sensor -> bridge -> municipality, and the resolver
    raises (never silently returns a partial) if a hop is missing.

Ties to spec FR-1 (the ownership chain exists and is total), FR-2 (sensor-keyed data is tenant-
attributable), FR-3 (bridge-keyed attribution), AC-1 (enforced keys, no orphan) and AC-2
(sensor-keyed attribution to exactly one municipality).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from db.tenant_store import FakeTenantStore

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


def _norm(path: Path) -> str:
    """Lowercase + collapse runs of whitespace to a single space, so column-alignment padding in the
    migrations doesn't defeat substring assertions."""
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


BRIDGES_SQL = _norm(MIGRATIONS / "0013_bridges.sql")
SENSORS_SQL = _norm(MIGRATIONS / "0014_sensors.sql")


# --- SCHEMA: the FK chain makes an orphan structurally impossible ------------------------------
def test_bridge_hard_fk_to_municipality_declared():
    assert "references municipalities" in BRIDGES_SQL, "bridges.municipality_id must REFERENCE municipalities"
    assert "municipality_id text not null" in BRIDGES_SQL, "the tenant link must be NOT NULL"


def test_sensor_hard_fk_to_bridge_declared():
    assert "references bridges" in SENSORS_SQL, "sensors.bridge_id must REFERENCE bridges"
    assert "bridge_id text not null" in SENSORS_SQL, "the bridge link must be NOT NULL"


def test_chain_is_total_across_both_migrations():
    # Both hops declared NOT NULL + hard FK ⇒ no orphan sensor/bridge can exist (AC-1).
    assert "not null references municipalities" in BRIDGES_SQL
    assert "not null references bridges" in SENSORS_SQL


# --- IN-FAKE: end-to-end resolution over a multi-tenant graph -----------------------------------
def _graph() -> FakeTenantStore:
    """MUNI_A -> {BRIDGE_A1 -> [S_A1a, S_A1b], BRIDGE_A2 -> [S_A2a]}; MUNI_B -> {BRIDGE_B1 -> [S_B1a]}."""
    s = FakeTenantStore()
    s.add_municipality("MUNI_A", name="Alpha City")
    s.add_municipality("MUNI_B", name="Beta Town")
    s.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span", location="River Rd")
    s.add_bridge("BRIDGE_A2", municipality_id="MUNI_A", name="South Span", location="Dock St")
    s.add_bridge("BRIDGE_B1", municipality_id="MUNI_B", name="East Span", location="Hill Ave")
    s.add_sensor("S_A1a", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    s.add_sensor("S_A1b", bridge_id="BRIDGE_A1", sensor_type="strain_gauge")
    s.add_sensor("S_A2a", bridge_id="BRIDGE_A2", sensor_type="crack")
    s.add_sensor("S_B1a", bridge_id="BRIDGE_B1", sensor_type="tiltmeter")
    return s


def test_every_sensor_resolves_to_exactly_one_municipality():
    store = _graph()
    expected = {
        "S_A1a": "MUNI_A",
        "S_A1b": "MUNI_A",
        "S_A2a": "MUNI_A",
        "S_B1a": "MUNI_B",
    }
    for sensor_id, muni in expected.items():
        assert store.municipality_of_sensor(sensor_id) == muni


def test_ownership_chain_returns_all_three_links_no_missing_hop():
    store = _graph()
    chain = store.ownership_chain("S_A1a")
    assert chain.sensor_id == "S_A1a"
    assert chain.bridge_id == "BRIDGE_A1"
    assert chain.municipality_id == "MUNI_A"


def test_chain_partitions_sensors_by_municipality():
    # Every MUNI_A sensor resolves to A, every MUNI_B sensor to B — the basis of RLS isolation.
    store = _graph()
    a = {sid for sid in ("S_A1a", "S_A1b", "S_A2a") if store.municipality_of_sensor(sid) == "MUNI_A"}
    b = {sid for sid in ("S_B1a",) if store.municipality_of_sensor(sid) == "MUNI_B"}
    assert a == {"S_A1a", "S_A1b", "S_A2a"}
    assert b == {"S_B1a"}
    # No sensor resolves across tenants.
    assert store.municipality_of_sensor("S_B1a") != "MUNI_A"


def test_resolver_raises_on_missing_sensor_no_silent_partial():
    store = _graph()
    with pytest.raises(KeyError):
        store.ownership_chain("NO_SUCH_SENSOR")


def test_bridge_hop_resolves_independently():
    # FR-3: bridge-keyed attribution (risk/report/alert rows carry bridge_id) resolves too.
    store = _graph()
    assert store.municipality_of_bridge("BRIDGE_A2") == "MUNI_A"
    assert store.municipality_of_bridge("BRIDGE_B1") == "MUNI_B"
