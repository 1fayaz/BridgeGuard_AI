"""D402 — correct-by-supersede audit: the five supersede tables share one discipline.

[DB-DEP] No Neon locally. Five SOR tables are CORRECT-BY-SUPERSEDE (not total-block): a mistake is
fixed by INSERTing a corrected row and stamping the OLD row's superseded_by to point at it, so the
old -> new history is preserved and never overwritten (Constitution VI). Each therefore carries the
SAME two-trigger discipline (plan §3):

  * a _guard_update trigger that BLOCKS an in-place substantive/identity edit but PERMITS the one
    legal UPDATE shape — stamping superseded_by (linking an old row to its replacement);
  * a _block_delete trigger + REVOKE DELETE, TRUNCATE — history is permanent.

The five: validated_readings (0002), risk_assessments (0006), report_artifacts (0008),
alert_dispatches (0010), analysis_results (0005). This audit asserts the discipline is present and
UNIFORM across all five — not per-file drift.

The one nuance (spec AC-7): alert_dispatches is ALSO a live state machine — a dispatch legitimately
advances SENT -> DELIVERED -> ACKNOWLEDGED / OPEN -> ESCALATED -> CLOSED on the current row. So its
guard blocks only the pinned IDENTITY (verdict id/version, decision, trace), NOT the delivery/
escalation/approval state columns. This file checks that its guard does NOT gate delivery_state.

Ties to spec-002 FR-7 (correct-by-supersede) and AC-7.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

# table -> (migration file, guard-fn stem, block-fn stem, guard-trigger, delete-trigger)
SUPERSEDE = {
    "validated_readings": "0002_validated_readings.sql",
    "risk_assessments":   "0006_risk_assessments.sql",
    "report_artifacts":   "0008_report_artifacts.sql",
    "alert_dispatches":   "0010_alert_dispatches.sql",
    "analysis_results":   "0005_analysis_results.sql",
}


def _norm(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return {t: _norm(MIG_DIR / f) for t, f in SUPERSEDE.items()}


@pytest.mark.parametrize("table", SUPERSEDE)
def test_has_superseded_by_self_link(sources: dict[str, str], table: str):
    # The correction mechanism itself: a self-referential superseded_by pointer.
    assert re.search(rf"superseded_by bigint\s+references {table}\(id\)", sources[table]), (
        f"{table} must carry a self-referential superseded_by (the supersede link)"
    )


@pytest.mark.parametrize("table", SUPERSEDE)
def test_guard_update_trigger_present(sources: dict[str, str], table: str):
    src = sources[table]
    # a guard_update function that RAISEs on a substantive edit,
    assert f"{table}_guard_update" in src, f"{table} must define a {table}_guard_update function"
    assert "raise exception" in src
    # attached BEFORE UPDATE (not UPDATE OR DELETE — supersede tables gate UPDATE and DELETE apart).
    assert re.search(
        rf"create trigger \w+ before update on {table}[^;]*{table}_guard_update", src
    ), f"{table} must attach {table}_guard_update as a BEFORE UPDATE trigger"


@pytest.mark.parametrize("table", SUPERSEDE)
def test_guard_permits_superseded_by_stamp(sources: dict[str, str], table: str):
    # The guard blocks substantive columns via `NEW.<col> IS DISTINCT FROM OLD.<col>` — but it must
    # NOT list superseded_by among the gated columns, else stamping the link would be blocked too.
    src = sources[table]
    gated = re.findall(r"new\.(\w+)\s+is distinct from old\.\1", src)
    assert gated, f"{table}'s guard must gate substantive columns via IS DISTINCT FROM"
    assert "superseded_by" not in gated, (
        f"{table}'s guard must NOT gate superseded_by (stamping the supersede link is the one legal edit)"
    )


@pytest.mark.parametrize("table", SUPERSEDE)
def test_block_delete_trigger_and_revoke(sources: dict[str, str], table: str):
    src = sources[table]
    assert f"{table}_block_delete" in src, f"{table} must define a {table}_block_delete function"
    assert re.search(
        rf"create trigger \w+ before delete on {table}[^;]*{table}_block_delete", src
    ), f"{table} must attach {table}_block_delete as a BEFORE DELETE trigger"
    assert re.search(rf"revoke delete, truncate on {table} from public", src), (
        f"{table} must REVOKE DELETE, TRUNCATE FROM PUBLIC"
    )


def test_alert_dispatches_guard_permits_delivery_state_advance(sources: dict[str, str]):
    # The AC-7 nuance: alert_dispatches is a live state machine on the current row. Its guard gates
    # only the pinned identity — NOT the delivery/escalation/approval state columns.
    src = sources["alert_dispatches"]
    gated = set(re.findall(r"new\.(\w+)\s+is distinct from old\.\1", src))
    # identity columns ARE gated,
    assert "assessment_id" in gated and "trace_id" in gated and "dispatch_decision" in gated, (
        "alert_dispatches must gate the pinned verdict identity/decision/trace"
    )
    # but the state-machine columns are NOT (they legitimately advance on the current row).
    for state_col in ("delivery_state", "escalation_state", "approval_state"):
        assert state_col not in gated, (
            f"alert_dispatches guard must not gate {state_col} (it advances as reality unfolds — AC-7)"
        )


def test_the_other_four_are_not_state_machines(sources: dict[str, str]):
    # The other four have no such live-state carve-out; their guard is the strict identity/verdict gate.
    # (Sanity: none of them reference a delivery_state column at all.)
    for table in ("validated_readings", "risk_assessments", "report_artifacts", "analysis_results"):
        assert "delivery_state" not in sources[table], (
            f"{table} is not a dispatch state machine; it should not carry delivery_state"
        )
