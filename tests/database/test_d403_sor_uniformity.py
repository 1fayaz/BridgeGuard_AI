"""D403 — SOR uniformity: all seven system-of-record tables match their discipline; sensor_status is
correctly EXCLUDED.

[DB-DEP] No Neon locally. D401/D402 audited the two disciplines in isolation. This test is the single
enumerating check that makes the discipline provably CONSISTENT across the whole system of record —
so an eighth SOR table added later without a guard, or a guard silently removed, fails here rather
than slipping through per-file review (plan §0/§3).

The seven SOR tables and their required discipline:
  TOTAL-BLOCK  (no UPDATE, no DELETE ever): raw_readings (0001), decision_log (0004)
    => <table>_block_mutation trigger fired BEFORE UPDATE OR DELETE + REVOKE UPDATE, DELETE, TRUNCATE
  SUPERSEDE    (UPDATE only to stamp superseded_by; no DELETE): validated_readings (0002),
    risk_assessments (0006), report_artifacts (0008), alert_dispatches (0010), analysis_results (0005)
    => <table>_guard_update (BEFORE UPDATE) + <table>_block_delete (BEFORE DELETE) + REVOKE DELETE, TRUNCATE

The eighth data table, sensor_status (0003), is deliberately NOT an SOR table: it is mutable
current-state (the permanent transition history lives in decision_log). It must therefore have NO
mutation guard and remain freely UPDATE-able — but DELETE/TRUNCATE are still revoked (a sensor's state
cannot silently vanish). This test asserts that exclusion is intentional, not an omission.

Ties to spec-002 FR-6/FR-7 and plan §0 (seven SOR tables, not six) / §3.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

TOTAL_BLOCK = {
    "raw_readings": "0001_raw_readings.sql",
    "decision_log": "0004_decision_log.sql",
}
SUPERSEDE = {
    "validated_readings": "0002_validated_readings.sql",
    "risk_assessments":   "0006_risk_assessments.sql",
    "report_artifacts":   "0008_report_artifacts.sql",
    "alert_dispatches":   "0010_alert_dispatches.sql",
    "analysis_results":   "0005_analysis_results.sql",
}
SOR_TABLES = {**TOTAL_BLOCK, **SUPERSEDE}
EXCLUDED = {"sensor_status": "0003_sensor_status.sql"}


def _norm(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


def test_there_are_exactly_seven_sor_tables():
    # Plan §0: the correction from six to seven SOR tables (analysis_results included). If this count
    # drifts, the enumerations below (and the discipline they enforce) are out of date.
    assert len(SOR_TABLES) == 7, "the system of record is exactly seven tables (plan §0)"


@pytest.mark.parametrize("table,fname", TOTAL_BLOCK.items())
def test_total_block_discipline(table: str, fname: str):
    src = _norm(MIG_DIR / fname)
    assert re.search(
        rf"create trigger \w+ before update or delete on {table}[^;]*{table}_block_mutation", src
    ), f"{table} (total-block) must fire {table}_block_mutation BEFORE UPDATE OR DELETE"
    assert re.search(rf"revoke update, delete, truncate on {table} from public", src), (
        f"{table} (total-block) must REVOKE UPDATE, DELETE, TRUNCATE"
    )


@pytest.mark.parametrize("table,fname", SUPERSEDE.items())
def test_supersede_discipline(table: str, fname: str):
    src = _norm(MIG_DIR / fname)
    assert re.search(
        rf"create trigger \w+ before update on {table}[^;]*{table}_guard_update", src
    ), f"{table} (supersede) must fire {table}_guard_update BEFORE UPDATE"
    assert re.search(
        rf"create trigger \w+ before delete on {table}[^;]*{table}_block_delete", src
    ), f"{table} (supersede) must fire {table}_block_delete BEFORE DELETE"
    assert re.search(rf"revoke delete, truncate on {table} from public", src), (
        f"{table} (supersede) must REVOKE DELETE, TRUNCATE"
    )


def test_every_sor_table_has_some_mutation_guard():
    # The whole-of-SOR invariant: NO system-of-record table lacks a mutation guard.
    for table, fname in SOR_TABLES.items():
        src = _norm(MIG_DIR / fname)
        has_guard = (
            f"{table}_block_mutation" in src  # total-block
            or (f"{table}_guard_update" in src and f"{table}_block_delete" in src)  # supersede
        )
        assert has_guard, f"SOR table {table} is missing its append-only guard"


def test_sensor_status_is_excluded_and_stays_mutable():
    # The deliberate exclusion: mutable current-state, no mutation guard.
    src = _norm(MIG_DIR / EXCLUDED["sensor_status"])
    assert "sensor_status_block_mutation" not in src, "sensor_status must NOT be total-blocked"
    assert "sensor_status_guard_update" not in src, "sensor_status must NOT have a supersede guard"
    assert "sensor_status_block_delete" not in src
    # No BEFORE UPDATE trigger of any kind gates it — it is freely UPDATE-able current-state.
    assert re.search(r"before update[^;]*on sensor_status", src) is None, (
        "sensor_status must remain freely UPDATE-able (current-state, not history)"
    )
    # ...but its state can't silently vanish: DELETE/TRUNCATE are still revoked.
    assert re.search(r"revoke delete, truncate on sensor_status from public", src), (
        "sensor_status must still REVOKE DELETE, TRUNCATE (silence != safety)"
    )
    # UPDATE is deliberately NOT revoked (that's the whole point of the exclusion).
    assert re.search(r"revoke update[^;]*on sensor_status", src) is None, (
        "sensor_status UPDATE must not be revoked — it is mutable by design"
    )
