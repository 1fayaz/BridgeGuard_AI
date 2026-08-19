"""D501 — the (sensor_id, <time>) index family: time-series reads are B-tree-backed, never a hypertable.

[DB-DEP] No Neon locally. The time-series tables are read by-sensor, most-recent-first (the DCA reads
a sensor's recent raw window; the SA reads a sensor's validated window; dashboards read a sensor's
recent analysis). The sanctioned access path for all three is a plain composite B-tree, NOT a
TimescaleDB hypertable — the stack is Neon/Postgres with standard indexes only (CLAUDE.md /
constitution v2.1.0). What is verifiable now:

  * raw_readings (0001):        (sensor_id, sensor_time DESC)
  * validated_readings (0002):  (sensor_id, sensor_time DESC)
  * analysis_results (0005):    (sensor_id, computed_at DESC)   [SA results are keyed by compute time]

and — across EVERY migration — no `create_hypertable(...)` call and no TimescaleDB extension is ever
created. (The migrations legitimately contain the prose "NO TimescaleDB" / "no hypertable conversion"
explaining the decision; this test bans the actual TimescaleDB API, not the explanatory words.)

Ties to spec-002 FR-11/FR-13 and AC-10/AC-12.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

# table -> (migration file, expected composite index columns)
COMPOSITE = {
    "raw_readings":       ("0001_raw_readings.sql",       r"\(sensor_id, sensor_time desc\)"),
    "validated_readings": ("0002_validated_readings.sql", r"\(sensor_id, sensor_time desc\)"),
    "analysis_results":   ("0005_analysis_results.sql",   r"\(sensor_id, computed_at desc\)"),
}


def _norm(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


@pytest.mark.parametrize("table", COMPOSITE)
def test_composite_index_present(table: str):
    fname, cols = COMPOSITE[table]
    src = _norm(MIG_DIR / fname)
    m = re.search(rf"create index (if not exists )?\w+ on {table} {cols}", src)
    assert m is not None, f"{table} must have a composite {cols} B-tree index"


@pytest.mark.parametrize("table", COMPOSITE)
def test_composite_index_leads_with_sensor_id(table: str):
    # Leading column must be sensor_id — the predicate is `WHERE sensor_id = ? ORDER BY <time> DESC`,
    # so a (time, sensor_id) index would not serve the by-sensor lookup.
    fname, _ = COMPOSITE[table]
    src = _norm(MIG_DIR / fname)
    m = re.search(rf"create index (if not exists )?\w+ on {table} \((\w+),", src)
    assert m and m.group(2) == "sensor_id", f"{table}'s time-series index must lead with sensor_id"


def test_no_timescaledb_anywhere():
    # The actual TimescaleDB API — banned across every migration, regardless of the explanatory prose.
    for path in sorted(MIG_DIR.glob("*.sql")):
        src = _norm(path)
        assert "create_hypertable" not in src, f"{path.name} calls create_hypertable (banned)"
        assert "create extension" not in src or "timescaledb" not in src, (
            f"{path.name} creates the TimescaleDB extension (banned)"
        )
        # a hypertable is only ever CREATED via create_hypertable; guard against the SELECT form too.
        assert not re.search(r"select\s+create_hypertable", src), (
            f"{path.name} invokes create_hypertable (banned)"
        )


def test_standard_btree_only_on_time_series_tables():
    # These composites are plain B-tree — not BRIN/GIST/hypertable partitioning.
    for table, (fname, _) in COMPOSITE.items():
        src = _norm(MIG_DIR / fname)
        # the time-series index line must not request a non-default access method.
        idx_line = re.search(rf"create index (if not exists )?\w+ on {table} \(sensor_id[^;]*", src)
        assert idx_line is not None
        assert "using brin" not in idx_line.group(0)
        assert "using gist" not in idx_line.group(0)
