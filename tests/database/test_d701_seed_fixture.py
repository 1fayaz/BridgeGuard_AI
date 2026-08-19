"""D701 — dev seed fixture: two municipalities, their bridges, full sensor-type coverage.

[DB-DEP] No Neon locally, so the seed is not EXECUTED here; it is parsed structurally and its chain
is mirrored through the FakeTenantStore (which enforces the same hard FKs the live DB will). The seed
lives OUTSIDE the numbered schema migrations (db/seed/seed_dev.sql, plan §6) — it is dev/test data,
not schema, so it never runs as part of a migration sequence.

What the seed must provide (plan §6, spec §Testability, AC-1):
  * >= 2 municipalities (MUNI_A, MUNI_B) — isolation is only provable with two tenants (enables D601);
  * MUNI_A -> BRIDGE_A1, BRIDGE_A2 ; MUNI_B -> BRIDGE_B1 (a multi-bridge tenant + a cross-tenant pair);
  * under BRIDGE_A1, one sensor of EACH sensor_type the SA/DCA handle (the seven-type catalogue), so
    every SA-handled type has a real sensor_id that resolves up the chain;
  * every row's denormalized attribution consistent with its ownership chain.

This test asserts the seed's rows are present and its chain is internally consistent (each bridge's
municipality exists; each sensor's bridge exists; the seven types are all covered), and — by loading
the same rows into FakeTenantStore — that the chain satisfies the hard-FK / consistency guarantees.

Ties to spec-002 AC-1 and §Testability; enables D601.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[2] / "db" / "seed" / "seed_dev.sql"

# The seven sensor types the SA/DCA catalogue handles (src/agents/data_collection/config/
# sensor_profiles.py) — the seed must cover each under BRIDGE_A1.
SENSOR_TYPES = (
    "accelerometer",
    "strain_gauge",
    "crack_sensor",
    "load_cell",
    "temperature",
    "tiltmeter",
    "displacement_lvdt",
)


@pytest.fixture(scope="module")
def raw() -> str:
    return SEED.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def norm(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.lower())


def test_seed_file_exists_outside_migrations():
    assert SEED.is_file(), f"missing seed fixture: {SEED}"
    # It must NOT be a numbered migration (plan §6: seed is not schema).
    assert SEED.parent.name == "seed", "seed_dev.sql must live under db/seed/, not db/migrations/"


def test_two_municipalities_present(norm: str):
    assert "insert into municipalities" in norm
    assert "'muni_a'" in norm and "'muni_b'" in norm, "both tenants required to prove isolation"


def test_bridges_and_their_municipality_chain(norm: str):
    assert "insert into bridges" in norm
    for bridge in ("bridge_a1", "bridge_a2", "bridge_b1"):
        assert f"'{bridge}'" in norm, f"seed must define {bridge}"


def test_every_sensor_type_covered_under_bridge_a1(norm: str):
    assert "insert into sensors" in norm
    for stype in SENSOR_TYPES:
        assert f"'{stype}'" in norm, f"seed must include a {stype} sensor (full SA/DCA catalogue)"


def test_no_ddl_in_seed(norm: str):
    # Seed is DATA only — it must not CREATE/ALTER/DROP schema (that is the migrations' job).
    for ddl in ("create table", "alter table", "drop table", "create index"):
        assert ddl not in norm, f"seed must not contain DDL ({ddl!r}) — it is data, not schema"


# --- the seed's chain is internally consistent (mirrored through the real hard-FK store) ---------
def _load_seed_into_fake():
    """Parse the seed's municipalities/bridges/sensors INSERTs and replay them through
    FakeTenantStore, which enforces the same hard FKs + duplicate rejection the live DB does. If the
    seed's chain is inconsistent (a bridge under an unknown municipality, etc.) this raises.
    """
    from db.tenant_store import FakeTenantStore

    text = SEED.read_text(encoding="utf-8")
    store = FakeTenantStore()

    # crude but sufficient row parser: pull (…) tuples out of each INSERT ... VALUES block.
    def _rows(table: str) -> list[list[str]]:
        m = re.search(
            rf"insert\s+into\s+{table}\b.*?values\s*(.*?)(?:\bon\s+conflict\b|;)",
            text, re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return []
        # strip line comments so a `-- …` inside the VALUES block isn't parsed as a row.
        body = re.sub(r"--[^\n]*", "", m.group(1))
        tuples = re.findall(r"\(([^)]*)\)", body)
        out = []
        for t in tuples:
            fields = [f.strip().strip("'") for f in t.split(",")]
            out.append(fields)
        return out

    for r in _rows("municipalities"):
        store.add_municipality(r[0], name=r[1])
    for r in _rows("bridges"):
        store.add_bridge(r[0], municipality_id=r[1], name=r[2],
                         location=(r[3] if len(r) > 3 else None))
    for r in _rows("sensors"):
        store.add_sensor(r[0], bridge_id=r[1], sensor_type=r[2])
    return store


def test_seed_chain_loads_without_fk_violation():
    store = _load_seed_into_fake()
    # >= 2 municipalities (isolation provable).
    assert store.has_municipality("MUNI_A") and store.has_municipality("MUNI_B")
    # every seeded sensor resolves all the way up to its municipality (no dangling hop).
    for sid in store._sensors:
        chain = store.ownership_chain(sid)
        assert chain.municipality_id in ("MUNI_A", "MUNI_B")


def test_bridge_a1_has_a_real_sensor_id_per_type():
    store = _load_seed_into_fake()
    types_on_a1 = {
        store.get_sensor(sid).sensor_type
        for sid, s in store._sensors.items()
        if s.bridge_id == "BRIDGE_A1"
    }
    for stype in SENSOR_TYPES:
        assert stype in types_on_a1, f"BRIDGE_A1 must carry a {stype} sensor resolving up the chain"
