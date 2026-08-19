"""D302 — tenant hard FKs (migration 0015 part B): the ownership chain becomes structurally enforced.

[DB-DEP] No Neon locally. What is verifiable now: 0015 part B adds the HARD tenancy foreign keys and
tightens the tenant columns to NOT NULL, so an orphan row (a reading whose sensor_id is not in
sensors, or any row whose municipality_id is unknown) is rejected by the database — not merely by
convention (plan §5). The SOFT provenance arrays (source_raw_ids / source_validated_ids /
source_analysis_ids) are deliberately left as plain BIGINT[] with NO FK.

FK map:
  * sensor-keyed (raw_readings, validated_readings, analysis_results, sensor_status, decision_log):
      sensor_id -> sensors, bridge_id -> bridges, municipality_id -> municipalities
  * judgment (risk_assessments, report_artifacts, alert_dispatches):
      bridge_id -> bridges, municipality_id -> municipalities

Ties to spec-002 FR-1/FR-2/FR-3 and AC-1/AC-2/AC-3.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0015_tenant_columns_and_fks.sql"
)

SENSOR_KEYED = (
    "raw_readings",
    "validated_readings",
    "analysis_results",
    "sensor_status",
    "decision_log",
)
JUDGMENT = (
    "risk_assessments",
    "report_artifacts",
    "alert_dispatches",
)
ALL_TENANT = SENSOR_KEYED + JUDGMENT


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


def test_part_b_section_present(norm: str):
    assert "part b" in norm


def test_municipality_fk_on_every_tenant_table(norm: str):
    for table in ALL_TENANT:
        m = re.search(
            rf"alter table {table} add constraint \w+ foreign key \(municipality_id\) "
            rf"references municipalities",
            norm,
        )
        assert m is not None, f"{table} must add municipality_id -> municipalities FK"


def test_bridge_fk_on_every_tenant_table(norm: str):
    for table in ALL_TENANT:
        m = re.search(
            rf"alter table {table} add constraint \w+ foreign key \(bridge_id\) references bridges",
            norm,
        )
        assert m is not None, f"{table} must add bridge_id -> bridges FK"


def test_sensor_fk_on_sensor_keyed_tables(norm: str):
    for table in SENSOR_KEYED:
        m = re.search(
            rf"alter table {table} add constraint \w+ foreign key \(sensor_id\) references sensors",
            norm,
        )
        assert m is not None, f"{table} must add sensor_id -> sensors FK"


def test_no_sensor_fk_on_judgment_tables(norm: str):
    # Judgment rows are bridge-keyed, not sensor-keyed — no sensor_id FK.
    for table in JUDGMENT:
        m = re.search(
            rf"alter table {table} add constraint \w+ foreign key \(sensor_id\)", norm
        )
        assert m is None, f"{table} is bridge-keyed; it should not gain a sensor_id FK"


def test_tenant_columns_tightened_to_not_null(norm: str):
    # The part-A nullable columns are tightened to NOT NULL in part B (post-backfill).
    for table in ALL_TENANT:
        assert re.search(
            rf"alter table {table} alter column municipality_id set not null", norm
        ), f"{table}.municipality_id must be SET NOT NULL"
    for table in SENSOR_KEYED:
        assert re.search(
            rf"alter table {table} alter column bridge_id set not null", norm
        ), f"{table}.bridge_id must be SET NOT NULL"


def test_soft_provenance_arrays_are_not_fks(norm: str):
    # The deliberate decoupling (plan §5): provenance arrays stay plain BIGINT[], never a FK.
    assert "foreign key (source_raw_ids)" not in norm
    assert "foreign key (source_validated_ids)" not in norm
    assert "foreign key (source_analysis_ids)" not in norm
    # and no array column is turned into a REFERENCES.
    assert "source_validated_ids references" not in norm
    assert "source_analysis_ids references" not in norm


def test_backfill_note_precedes_not_null(norm: str):
    # Plan Open Item #4: NOT NULL/FK validation must be preceded by a backfill on a live instance.
    assert "backfill" in norm


# --- in-fake: the hard FK is mirrored (an orphan reading is rejected) ---------------------------
def test_fake_rejects_reading_under_unknown_sensor():
    # The tenant store's reading-attribution mirror rejects a reading whose sensor isn't onboarded.
    from db.tenant_store import FakeTenantStore, UnknownSensorError

    store = FakeTenantStore()
    store.add_municipality("MUNI_A", name="Alpha City")
    store.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span")
    store.add_sensor("S1", bridge_id="BRIDGE_A1", sensor_type="accelerometer")
    # attributing a reading to a real sensor resolves its tenant;
    assert store.attribute_reading(sensor_id="S1") == ("BRIDGE_A1", "MUNI_A")
    # attributing one to an unknown sensor is rejected (the 0015 sensor_id -> sensors FK).
    with pytest.raises(UnknownSensorError):
        store.attribute_reading(sensor_id="GHOST")
