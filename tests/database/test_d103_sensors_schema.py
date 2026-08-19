"""D103 — sensors migration (0014) + FakeTenantStore.add_sensor: structural + in-fake assertions.

[DB-DEP] No Neon/Postgres locally; the migration cannot be EXECUTED here. What is verifiable now:
the file declares the sensors table with a TEXT primary key, a NOT NULL bridge_id that is a HARD
foreign key REFERENCES bridges(id) (the ownership-chain link that makes every sensor-keyed reading
tenant-attributable), a NOT NULL sensor_type, a JSONB config, a created_at default, an index on
(bridge_id), and the Neon/no-TimescaleDB header. The in-memory FakeTenantStore mirrors the hard FK:
a sensor under an unknown bridge is rejected; a valid one is accepted and resolves up the full chain.

Ties to spec FR-1 (ownership chain municipalities -> bridges -> sensors -> readings), FR-2
(sensor-keyed data is tenant-attributable via sensor -> bridge -> municipality), and AC-1 (no orphan
sensor — every sensor references exactly one bridge via an enforced FK).
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0014_sensors.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


# --- migration structure ------------------------------------------------------------------------
def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_creates_sensors_table(sql: str):
    lower = sql.lower()
    assert "create table" in lower
    assert "sensors" in lower


def test_id_is_text_primary_key(sql: str):
    import re

    m = re.search(r"id\s+text\s+primary key", sql.lower())
    assert m is not None, "sensors.id must be a TEXT PRIMARY KEY"


def test_bridge_id_is_not_null_hard_fk(sql: str):
    # The ownership-chain link: bridge_id must be NOT NULL and a HARD FK (plan §5).
    import re

    lower = sql.lower()
    m = re.search(r"bridge_id\s+text\s+not null", lower)
    assert m is not None, "sensors.bridge_id must be TEXT NOT NULL"
    assert "references bridges" in lower, "bridge_id must REFERENCE bridges(id)"


def test_sensor_type_is_not_null(sql: str):
    import re

    m = re.search(r"sensor_type\s+text\s+not null", sql.lower())
    assert m is not None, "sensors.sensor_type must be TEXT NOT NULL"


def test_config_is_jsonb(sql: str):
    lower = sql.lower()
    assert "config" in lower
    import re

    m = re.search(r"config\s+jsonb", lower)
    assert m is not None, "sensors.config must be JSONB"


def test_created_at_present_with_default(sql: str):
    lower = sql.lower()
    assert "created_at" in lower
    assert "timestamptz" in lower
    assert "now()" in lower


def test_bridge_id_index_present(sql: str):
    # plan §4: (bridge_id) index for the bridge-detail sensor listing.
    import re

    m = re.search(r"create index[^;]*on\s+sensors\s*\(\s*bridge_id", sql.lower())
    assert m is not None, "expected an index on sensors(bridge_id)"


def test_required_columns_present(sql: str):
    for column in ("id", "bridge_id", "sensor_type", "config", "created_at"):
        assert column in sql, f"sensors missing column: {column}"


def test_neon_no_timescaledb_header(sql: str):
    lower = sql.lower()
    assert "neon" in lower, "header must state the Neon/Postgres stack"
    assert "no timescaledb" in lower, "header must state NO TimescaleDB"
    assert "hypertable" not in lower and "create_hypertable" not in lower
    assert "[db-dep]" in lower


# --- FakeTenantStore (in-fake mirror of the hard FK) --------------------------------------------
def _seed(store):
    store.add_municipality("MUNI_A", name="Alpha City")
    store.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span", location="River Rd")


def test_fake_store_accepts_a_sensor_under_a_real_bridge():
    from db.tenant_store import FakeTenantStore

    store = FakeTenantStore()
    _seed(store)
    store.add_sensor("SENSOR_1", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    s = store.get_sensor("SENSOR_1")
    assert s.bridge_id == "BRIDGE_A1"
    assert s.sensor_type == "accelerometer"


def test_fake_store_rejects_sensor_under_unknown_bridge():
    from db.tenant_store import FakeTenantStore, UnknownBridgeError

    store = FakeTenantStore()
    _seed(store)
    with pytest.raises(UnknownBridgeError):
        store.add_sensor("SENSOR_X", bridge_id="NOPE", sensor_type="strain_gauge")


def test_fake_store_rejects_duplicate_sensor_id():
    from db.tenant_store import FakeTenantStore, DuplicateSensorError

    store = FakeTenantStore()
    _seed(store)
    store.add_sensor("SENSOR_1", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    with pytest.raises(DuplicateSensorError):
        store.add_sensor("SENSOR_1", bridge_id="BRIDGE_A1", sensor_type="crack")


def test_fake_store_requires_non_blank_sensor_type():
    from db.tenant_store import FakeTenantStore

    store = FakeTenantStore()
    _seed(store)
    with pytest.raises(ValueError):
        store.add_sensor("SENSOR_1", bridge_id="BRIDGE_A1", sensor_type="")


def test_fake_store_resolves_sensor_to_municipality_full_chain():
    # The full ownership chain sensor -> bridge -> municipality (feeds D104 / FR-2 attribution).
    from db.tenant_store import FakeTenantStore

    store = FakeTenantStore()
    _seed(store)
    store.add_sensor("SENSOR_1", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    assert store.municipality_of_sensor("SENSOR_1") == "MUNI_A"
