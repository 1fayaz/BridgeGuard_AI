"""D203 — analysis_results correct-by-supersede + idempotency (migration 0005 triggers/index + fake).

[DB-DEP] No Neon/Postgres locally. What is verifiable now: the 0005 migration declares the
guard-update trigger (blocks in-place edits to the substantive/provenance columns; permits stamping
superseded_by), the block-delete trigger + DELETE/TRUNCATE revoke (history permanent, Const. VI),
and the idempotency partial-unique index
  (sensor_id, calculation, block_id, input_version) WHERE superseded_by IS NULL.
The in-memory FakeAnalysisStore mirrors these: a re-trigger for the same input version is a no-op
(rejected duplicate current), a genuine input correction (new input_version) supersedes (appends +
links old->new, never mutates), and delete/overwrite are blocked.

Ties to spec-002 FR-7 (correct-by-supersede, DELETE blocked) and FR-10 (idempotent current rows);
AC-7 / AC-9. Mirrors risk_assessments (0006) / report_artifacts (0008) discipline.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0005_analysis_results.sql"
)


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


# --- migration: triggers + revoke + idempotency index -------------------------------------------
def test_guard_update_trigger_present(norm: str):
    assert "analysis_results_guard_update" in norm
    assert "before update on analysis_results" in norm


def test_guard_blocks_substantive_and_provenance_edits(norm: str):
    # The guard must block edits to the substantive/identity/provenance columns.
    for col in ("outcome", "value", "reason_code", "source_validated_ids",
                "input_version", "config_version", "sensor_id", "calculation"):
        assert col in norm, f"guard should reference {col}"
    # it raises on a disallowed mutation.
    assert "correct-by-append" in norm or "correct by append" in norm


def test_block_delete_trigger_and_revoke(norm: str):
    assert "analysis_results_block_delete" in norm
    assert "before delete on analysis_results" in norm
    assert "revoke delete, truncate on analysis_results" in norm


def test_idempotency_partial_unique_index(norm: str):
    # (sensor_id, calculation, block_id, input_version) WHERE superseded_by IS NULL.
    m = re.search(
        r"create unique index[^;]*on analysis_results\s*\(\s*sensor_id\s*,\s*calculation\s*,"
        r"\s*block_id\s*,\s*input_version\s*\)\s*where superseded_by is null",
        norm,
    )
    assert m is not None, "expected the partial-unique idempotency index over current rows"


# --- FakeAnalysisStore: supersede + idempotency -------------------------------------------------
def _ran(sensor="S1", calc="RMS", block="b1", version="v1", value=0.5):
    from db.analysis_store import AnalysisResult

    return AnalysisResult(
        sensor_id=sensor, calculation=calc, block_id=block, input_version=version,
        outcome="RAN", value=value, config_version="cfg-1", source_validated_ids=(10,),
    )


def test_insert_assigns_id_and_is_current():
    from db.analysis_store import FakeAnalysisStore

    store = FakeAnalysisStore()
    rid = store.insert(_ran())
    assert isinstance(rid, int)
    cur = store.current("S1", "RMS", "b1", "v1")
    assert cur is not None and cur.value == 0.5


def test_duplicate_current_same_input_version_rejected():
    # FR-10: a re-trigger for the SAME input version is a no-op (rejected duplicate current).
    from db.analysis_store import FakeAnalysisStore, DuplicateAnalysisResultError

    store = FakeAnalysisStore()
    store.insert(_ran(version="v1"))
    with pytest.raises(DuplicateAnalysisResultError):
        store.insert(_ran(version="v1", value=0.9))


def test_new_input_version_supersedes():
    # FR-8/FR-10: a genuine correction (new input_version) supersedes — appends + links old->new.
    from db.analysis_store import FakeAnalysisStore

    store = FakeAnalysisStore()
    old_id = store.insert(_ran(version="v1", value=0.5))
    new_id = store.insert_superseding(old_id, _ran(version="v2", value=0.7))
    assert new_id != old_id
    # old row retained, now historical (linked); new row is current.
    assert store.get(old_id).superseded_by == new_id
    assert store.get(new_id).superseded_by is None
    cur = store.current("S1", "RMS", "b1", "v2")
    assert cur.value == 0.7


def test_supersede_does_not_mutate_the_old_row():
    from db.analysis_store import FakeAnalysisStore

    store = FakeAnalysisStore()
    old_id = store.insert(_ran(version="v1", value=0.5))
    store.insert_superseding(old_id, _ran(version="v2", value=0.7))
    # the old verdict's value is unchanged (only superseded_by was stamped).
    assert store.get(old_id).result.value == 0.5


def test_overwrite_blocked():
    from db.analysis_store import FakeAnalysisStore, AnalysisResultImmutableError

    store = FakeAnalysisStore()
    rid = store.insert(_ran())
    with pytest.raises(AnalysisResultImmutableError):
        store.overwrite(rid, _ran(value=9.9))


def test_delete_blocked():
    from db.analysis_store import FakeAnalysisStore, AnalysisResultDeleteBlocked

    store = FakeAnalysisStore()
    rid = store.insert(_ran())
    with pytest.raises(AnalysisResultDeleteBlocked):
        store.delete(rid)


def test_superseded_row_frees_the_idempotency_slot():
    # After supersession, a NEW current row for the superseding version coexists with the historical
    # one; there is exactly ONE current row per (sensor, calc, block, version) key at a time.
    from db.analysis_store import FakeAnalysisStore

    store = FakeAnalysisStore()
    old_id = store.insert(_ran(version="v1"))
    store.insert_superseding(old_id, _ran(version="v2"))
    current_rows = [r for r in store.rows if r.superseded_by is None]
    assert len(current_rows) == 1
    assert current_rows[0].result.input_version == "v2"


def test_different_block_is_independent():
    # Two blocks on the same sensor/calc are distinct idempotency keys — both current, no conflict.
    from db.analysis_store import FakeAnalysisStore

    store = FakeAnalysisStore()
    store.insert(_ran(block="b1", version="v1"))
    store.insert(_ran(block="b2", version="v1"))
    assert store.current("S1", "RMS", "b1", "v1") is not None
    assert store.current("S1", "RMS", "b2", "v1") is not None
