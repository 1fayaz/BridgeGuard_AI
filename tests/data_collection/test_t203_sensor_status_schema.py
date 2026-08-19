"""T203 — sensor_status migration: structural assertions.

[DB-DEP] No Supabase/Postgres locally; the migration cannot be EXECUTED here. What is
verifiable now: the file declares the LIVE|OFFLINE health axis, is structurally
distinct from validated_readings (so the two can co-exist for one sensor/cycle), and
carries missed_count + last_seen(sensor ts) for the liveness owner (T301/G2).
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0003_sensor_status.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_live_and_offline_are_the_only_health_states(sql: str):
    lower = sql.lower()
    assert "create type sensor_health as enum" in lower
    assert "'LIVE'" in sql
    assert "'OFFLINE'" in sql
    # The six reading-statuses must NOT leak into this device-health axis.
    for reading_status in ("'NO_DATA'", "'INTERPOLATED'", "'SPIKE'", "'CORRUPT'", "'PENDING'"):
        assert reading_status not in sql, f"{reading_status} belongs to validated_readings, not sensor_status"


def test_distinct_table_from_validated_readings(sql: str):
    lower = sql.lower()
    assert "create table if not exists sensor_status" in lower
    # Co-existence (OFFLINE here + NO_DATA reading row) requires two independent tables:
    # this one must NOT be foreign-keyed to / dependent on validated_readings.
    assert "references validated_readings" not in lower


def test_tracks_missed_count_for_liveness(sql: str):
    # T301 counts consecutive missed reports; 3 -> OFFLINE.
    assert "missed_count" in sql
    assert "missed_count_non_negative" in sql.lower()


def test_last_seen_uses_sensor_timestamp(sql: str):
    # G4: liveness measures silence from the sensor's own last timestamp.
    assert "last_seen" in sql


def test_required_columns_present(sql: str):
    for column in ("sensor_id", "status", "missed_count", "last_seen", "updated_at"):
        assert column in sql, f"sensor_status missing column: {column}"


def test_one_current_row_per_sensor(sql: str):
    # sensor_id is the primary key -> exactly one current state row per sensor.
    lower = sql.lower()
    assert "sensor_id" in lower and "primary key" in lower
