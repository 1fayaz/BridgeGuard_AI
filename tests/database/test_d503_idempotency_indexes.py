"""D503 — assessment-keyed idempotency: a partial-unique-current index per supersede table.

[DB-DEP] No Neon locally. Idempotency (spec FR-10) means a redelivered trigger for an
already-handled key is a no-op, not a duplicate — but ONLY among CURRENT rows, because a correction
legitimately produces a new current row for the same key after superseding the old one. Each supersede
table enforces this with a PARTIAL unique index scoped `WHERE superseded_by IS NULL`, so:

  * a second CURRENT row for the same key is rejected (the redelivery no-op);
  * superseding the old row (superseded_by := new id) frees the slot for the replacement.

The keys (plan §4 / the built schema):
  * risk_assessments (0006):  (bridge_id, cycle_id)                          WHERE superseded_by IS NULL
  * report_artifacts (0008):  (assessment_id, assessment_version)            WHERE superseded_by IS NULL
  * alert_dispatches (0010):  (assessment_id, assessment_version)            WHERE superseded_by IS NULL
  * analysis_results (0005):  (sensor_id, calculation, block_id, input_version) WHERE superseded_by IS NULL

The `WHERE superseded_by IS NULL` predicate is the load-bearing part — a plain UNIQUE would forbid
the correction history. This test asserts the four indexes are UNIQUE + partial-on-current, and (over
the FakeAnalysisStore) that the current-vs-superseded behaviour matches.

Ties to spec-002 FR-10 and AC-9.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

# table -> (migration file, tuple of key columns)
IDEMPOTENCY = {
    "risk_assessments": ("0006_risk_assessments.sql", ("bridge_id", "cycle_id")),
    "report_artifacts": ("0008_report_artifacts.sql", ("assessment_id", "assessment_version")),
    "alert_dispatches": ("0010_alert_dispatches.sql", ("assessment_id", "assessment_version")),
    "analysis_results": ("0005_analysis_results.sql",
                         ("sensor_id", "calculation", "block_id", "input_version")),
}


def _norm(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


@pytest.mark.parametrize("table", IDEMPOTENCY)
def test_partial_unique_current_index_present(table: str):
    fname, cols = IDEMPOTENCY[table]
    src = _norm(MIG_DIR / fname)
    col_list = re.escape("(" + ", ".join(cols) + ")")
    m = re.search(
        rf"create unique index (if not exists )?\w+ on {table} {col_list} where superseded_by is null",
        src,
    )
    assert m is not None, (
        f"{table} must have a UNIQUE index on {cols} scoped WHERE superseded_by IS NULL"
    )


@pytest.mark.parametrize("table", IDEMPOTENCY)
def test_index_is_partial_not_a_plain_unique(table: str):
    # The WHERE clause is what allows a correction history — a plain UNIQUE would forbid it. Assert the
    # index on these key columns is NOT declared without the partial predicate.
    fname, cols = IDEMPOTENCY[table]
    src = _norm(MIG_DIR / fname)
    col_list = re.escape("(" + ", ".join(cols) + ")")
    # find the unique-index statement for this key and confirm it carries the predicate.
    m = re.search(rf"create unique index (if not exists )?\w+ on {table} {col_list}[^;]*", src)
    assert m is not None and "where superseded_by is null" in m.group(0), (
        f"{table}'s idempotency index must be PARTIAL on current rows, not a plain UNIQUE"
    )


# --- FakeAnalysisStore mirror: current-vs-superseded idempotency behaviour ----------------------
def _result(**over):
    from db.analysis_store import AnalysisResult

    base = dict(
        sensor_id="S1", calculation="RMS", block_id="b1", input_version="v1",
        outcome="RAN", value=0.4, config_version="cfg-1", source_validated_ids=(1,),
    )
    base.update(over)
    return AnalysisResult(**base)


def test_second_current_for_same_key_rejected():
    from db.analysis_store import FakeAnalysisStore, DuplicateAnalysisResultError

    store = FakeAnalysisStore()
    store.insert(_result())
    # a second CURRENT row for the same (sensor, calc, block, input_version) is the redelivery no-op.
    with pytest.raises(DuplicateAnalysisResultError):
        store.insert(_result(value=0.9))


def test_superseding_frees_the_slot():
    from db.analysis_store import FakeAnalysisStore

    store = FakeAnalysisStore()
    old = store.insert(_result())
    # superseding the old row frees the current slot; the corrected row then inserts cleanly.
    new = store.insert_superseding(old, _result(value=0.9))
    assert new != old
    # exactly one current row remains for the key, and it holds the corrected value.
    cur = store.current(sensor_id="S1", calculation="RMS", block_id="b1", input_version="v1")
    assert cur is not None and cur.value == 0.9
    # the new id is the current row; the old row is now superseded by it.
    assert store.get(new).result.value == 0.9
    assert store.get(old).superseded_by == new


def test_a_different_key_is_independent():
    from db.analysis_store import FakeAnalysisStore

    store = FakeAnalysisStore()
    store.insert(_result(block_id="b1"))
    # a different block_id is a different idempotency key — not a duplicate.
    store.insert(_result(block_id="b2"))
    assert store.current(sensor_id="S1", calculation="RMS", block_id="b2", input_version="v1") is not None
