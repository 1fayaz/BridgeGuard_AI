"""D502 — the (bridge_id, <ts>) index family: bridge-keyed trend reads are B-tree-backed.

[DB-DEP] No Neon locally. The three judgment tables are read by-bridge, most-recent-first (a bridge's
risk history, its report history, its dispatch history — the trend views). The sanctioned access path
is a composite B-tree leading with bridge_id and ordered by each table's REAL event timestamp — not a
uniform `created_at` (plan §4: index on the column the domain actually orders by). What is verifiable
now:

  * risk_assessments (0006):  (bridge_id, assessed_at DESC)   — when the verdict was assessed
  * report_artifacts (0008):  (bridge_id, rendered_at DESC)   — when the report was rendered
  * alert_dispatches (0010):  (bridge_id, attempted_at DESC)  — when the dispatch was attempted

Each timestamp column is the table's own event time, matching the built schema. Standard B-tree only
(v2.1.0), consistent with D501.

Ties to spec-002 FR-12 (trend reads).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

# table -> (migration file, real event-timestamp column)
BRIDGE_TREND = {
    "risk_assessments": ("0006_risk_assessments.sql", "assessed_at"),
    "report_artifacts": ("0008_report_artifacts.sql", "rendered_at"),
    "alert_dispatches": ("0010_alert_dispatches.sql", "attempted_at"),
}


def _norm(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


@pytest.mark.parametrize("table", BRIDGE_TREND)
def test_bridge_trend_index_present(table: str):
    fname, ts = BRIDGE_TREND[table]
    src = _norm(MIG_DIR / fname)
    m = re.search(rf"create index (if not exists )?\w+ on {table} \(bridge_id, {ts} desc\)", src)
    assert m is not None, f"{table} must have a composite (bridge_id, {ts} DESC) index"


@pytest.mark.parametrize("table", BRIDGE_TREND)
def test_index_leads_with_bridge_id(table: str):
    # Leading column must be bridge_id: `WHERE bridge_id = ? ORDER BY <ts> DESC`.
    fname, _ = BRIDGE_TREND[table]
    src = _norm(MIG_DIR / fname)
    m = re.search(rf"create index (if not exists )?\w+ on {table} \((\w+),", src)
    assert m and m.group(2) == "bridge_id", f"{table}'s trend index must lead with bridge_id"


@pytest.mark.parametrize("table", BRIDGE_TREND)
def test_timestamp_column_is_the_real_event_time(table: str):
    # The ordered column must be a REAL column declared on the table — not a uniform created_at.
    fname, ts = BRIDGE_TREND[table]
    src = _norm(MIG_DIR / fname)
    assert re.search(rf"{ts}\s+timestamptz", src), (
        f"{table} must declare a real {ts} TIMESTAMPTZ column (plan §4: order by the domain's own time)"
    )


def test_the_three_timestamp_columns_are_distinct():
    # Plan §4's whole point: three different event times, not one generic created_at reused.
    cols = {ts for _, ts in BRIDGE_TREND.values()}
    assert cols == {"assessed_at", "rendered_at", "attempted_at"}, (
        "each judgment table orders by its own distinct event timestamp"
    )
