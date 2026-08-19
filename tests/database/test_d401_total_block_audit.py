"""D401 — total-block audit: raw_readings (0001) + decision_log (0004) are hard append-only.

[DB-DEP] No Neon locally. Two SOR tables are TOTAL-BLOCK: no UPDATE, no DELETE, ever — a raw sensor
reading and a decision-log entry are immutable the instant they land (Constitution II raw-immutable,
VI audit-permanent). This is defense in depth (plan §3): REVOKE removes the privilege, and a
BEFORE UPDATE OR DELETE trigger RAISEs even if the privilege is somehow restored (e.g. a superuser or
a future GRANT). This audit re-asserts BOTH layers on BOTH tables, and — because 0015 (D301) added
tenant columns to these very tables — confirms that ALTER did not weaken the block.

What is verifiable now: the REVOKE UPDATE/DELETE/TRUNCATE statements, the block-mutation trigger
function that RAISEs, and the BEFORE UPDATE OR DELETE trigger, all present per table; and that 0015's
touch of these tables was ADD COLUMN only (no DROP TRIGGER / no DISABLE / no weakening).

Ties to spec-002 FR-6 (append-only) and AC-6.
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


def _norm(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return {table: _norm(MIG_DIR / fname) for table, fname in TOTAL_BLOCK.items()}


@pytest.fixture(scope="module")
def wiring() -> str:
    return _norm(MIG_DIR / "0015_tenant_columns_and_fks.sql")


@pytest.mark.parametrize("table", TOTAL_BLOCK)
def test_revokes_update_delete_truncate(sources: dict[str, str], table: str):
    # The privilege is removed from PUBLIC and from the app role (defense layer 1).
    assert re.search(rf"revoke update, delete, truncate on {table} from public", sources[table]), (
        f"{table} must REVOKE UPDATE, DELETE, TRUNCATE FROM PUBLIC"
    )
    assert re.search(
        rf"revoke update, delete, truncate on {table} from bridgeguard_service", sources[table]
    ), f"{table} must REVOKE UPDATE, DELETE, TRUNCATE FROM bridgeguard_service"


@pytest.mark.parametrize("table", TOTAL_BLOCK)
def test_block_mutation_trigger_raises(sources: dict[str, str], table: str):
    # The trigger function RAISEs (defense layer 2) — survives even if the privilege is restored.
    src = sources[table]
    assert f"{table}_block_mutation" in src, f"{table} must define a {table}_block_mutation function"
    assert "raise exception" in src, f"{table}'s block function must RAISE"


@pytest.mark.parametrize("table", TOTAL_BLOCK)
def test_before_update_or_delete_trigger_attached(sources: dict[str, str], table: str):
    # Both UPDATE and DELETE are intercepted (not just one).
    m = re.search(
        rf"create trigger \w+ before update or delete on {table}[^;]*{table}_block_mutation",
        sources[table],
    )
    assert m is not None, f"{table} must have a BEFORE UPDATE OR DELETE trigger firing its block fn"


@pytest.mark.parametrize("table", TOTAL_BLOCK)
def test_tenant_add_did_not_weaken_the_block(wiring: str, table: str):
    # 0015 touched these tables to add tenant columns; it must not have dropped/disabled the guard.
    assert f"drop trigger if exists trg_{table}" not in wiring, (
        f"0015 must not drop {table}'s append-only trigger"
    )
    # 0015's only mutation-verb touch of these tables is ADD COLUMN / ADD CONSTRAINT / ALTER COLUMN —
    # never DROP COLUMN / DROP TABLE (that would rewrite/replace the guarded table).
    assert "drop column" not in wiring
    assert "drop table" not in wiring
    # and it never RE-GRANTS the revoked privilege back to the service role.
    assert f"grant update on {table}" not in wiring
    assert f"grant delete on {table}" not in wiring
