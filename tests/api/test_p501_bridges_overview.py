"""P501 — the dashboard's first screen: one row per bridge, read from current assessments.

This is the endpoint an engineer opens on a Monday morning to decide where to go, so the
failures worth designing against are the ones that make a bridge look fine when nobody knows
whether it is.

**A bridge with no assessment must still appear.** The natural spelling of this query is an
inner join, and an inner join silently drops every bridge the Risk Agent has never scored. The
list then reads as complete — nothing marks the absence — and a bridge that has never been
assessed is indistinguishable from one that does not exist. So the join is a LEFT JOIN and an
unassessed bridge is present with no risk attached. "We do not know" is a state the dashboard
has to be able to show.

**No reading history is scanned.** The overview reads `bridges` and current `risk_assessments`
and nothing else. Not for speed alone (though the <500 ms target depends on it): the moment this
layer touches `raw_readings`, it is one aggregate away from computing something — a mean, a
latest-value, a liveness guess — and that number would be a second opinion competing with the
DCA's, with no audit row behind it (Principle III, INV-6).

**A score never appears without its WHY.** `current_risk` is one nested object in which
`explanation` is required, so a score and its explanation cannot be separated by any serialization
path. This mirrors 0006's own constraints exactly: `explanation` is NOT NULL there too, and
`risk_score`/`severity` are NULL together. The response model is the table's shape, not a
reinterpretation of it (INV-7; P508 revisits this structurally).

**One item per bridge, even though the schema permits several.** 0006's partial unique index is
on `(bridge_id, cycle_id)` among current rows — per *cycle*, not per bridge — so a bridge with two
un-superseded assessments from different cycles legitimately has two current rows. Left alone,
that bridge appears twice in the list with two different scores and no indication which is now.

[DB-DEP] There is no Neon instance, so the query runs against `FakeConnection`, which applies
0016's RLS predicate to its rows. Tenancy is therefore genuinely exercised; the SQL's own shape is
asserted structurally.

Ties to tasks.md P501, spec AC-2 + §6, plan §6.
"""
from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.db.fake_connection import FakeConnection
from api.db.repository import Repository
from api.db.scope import scoped_transaction
from api.read.bridges import (
    OVERVIEW_SQL,
    BridgeOverview,
    BridgeOverviewRepository,
    CurrentRisk,
    project_overview,
)
from api.schemas.common import PageParams

READ_ROOT = Path(__file__).resolve().parents[2] / "src" / "api" / "read"

T1 = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def joined_row(
    *,
    bridge_id: str = "BRIDGE_1",
    municipality_id: str = "MUNI_A",
    name: str = "Ours",
    scored: bool = True,
    assessed_at: datetime = T2,
    assessment_id: int | None = 501,
) -> dict:
    """One row as the LEFT JOIN produces it: bridge columns, assessment columns or NULLs."""
    row = {
        "bridge_id": bridge_id,
        "municipality_id": municipality_id,
        "name": name,
        "location": "Over the Indus",
        "assessment_id": assessment_id,
        "risk_score": None,
        "severity": None,
        "explanation": None,
        "review_status": None,
        "assessed_at": None,
    }
    if scored:
        row |= {
            "risk_score": 72,
            "severity": "WARNING",
            "explanation": "Strain at pier 3 is 1.4x baseline across two cycles.",
            "review_status": "PENDING_HUMAN_REVIEW",
            "assessed_at": assessed_at,
        }
    return row


def unassessed_row(**kwargs) -> dict:
    """No assessment row at all — the LEFT JOIN's NULL side."""
    return joined_row(scored=False, assessment_id=None, **kwargs)


def withheld_row(**kwargs) -> dict:
    """An assessment that exists and declined to score (0006 FR-6/FR-7).

    Score and severity are NULL together; the explanation is still there, stating what was
    missing, and review_status is PENDING_HUMAN_REVIEW. This is a real audited verdict, and the
    difference from `unassessed_row` is the difference between "we looked and could not say"
    and "nobody has looked".
    """
    return joined_row(scored=False, **kwargs) | {
        "explanation": "Withheld: pier-3 strain gauge offline for 6 of 8 cycles.",
        "review_status": "PENDING_HUMAN_REVIEW",
        "assessed_at": T2,
    }


async def fetch_overview(rows: list[dict], scope: str, params: PageParams | None = None):
    conn = FakeConnection(rows=rows)
    async with scoped_transaction(conn, scope) as scoped:
        repo = BridgeOverviewRepository(scoped)
        return await repo.list_overview(params or PageParams()), conn


def _read_sources() -> list[tuple[str, str]]:
    return [
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(READ_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def _code_only(src: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    body.pop(0)
    return ast.unparse(tree)


# ------------------------------------------------------------ one item per in-scope bridge ---
def test_each_in_scope_bridge_produces_one_item():
    items = project_overview([joined_row(bridge_id=f"B{i}") for i in range(4)])
    assert [i.bridge_id for i in items] == ["B0", "B1", "B2", "B3"]


def test_an_item_carries_the_score_severity_and_when_it_was_assessed():
    item = project_overview([joined_row()])[0]
    assert item.current_risk.risk_score == 72
    assert item.current_risk.severity == "WARNING"
    assert item.current_risk.assessed_at == T2


def test_an_item_carries_the_bridge_identity_a_reader_needs():
    item = project_overview([joined_row(name="Kohat Crossing")])[0]
    assert item.bridge_id == "BRIDGE_1"
    assert item.name == "Kohat Crossing"


def test_an_item_names_the_assessment_it_projected():
    """INV-6: a number on a dashboard has to be traceable to the audited row it came from."""
    item = project_overview([joined_row()])[0]
    assert item.current_risk.assessment_id == 501


def test_the_severity_is_passed_through_verbatim():
    """P503 in advance: the band is read, never derived. Any string the row holds arrives
    unchanged, so this layer cannot be the place a band is decided."""
    for band in ("SAFE", "WATCH", "WARNING", "CRITICAL"):
        row = joined_row() | {"severity": band}
        assert project_overview([row])[0].current_risk.severity == band


def test_the_review_status_is_carried():
    """P509 in advance: a PENDING_HUMAN_REVIEW verdict must never reach a screen looking
    settled, and it cannot be surfaced later if the projection dropped it here."""
    item = project_overview([joined_row()])[0]
    assert item.current_risk.review_status == "PENDING_HUMAN_REVIEW"


# ------------------------------------------- a bridge with no assessment is present, not gone ---
def test_an_unassessed_bridge_still_appears():
    """The inner-join bug, stated as a test.

    A dropped bridge is worse than an unscored one: the list looks complete, so nobody goes
    looking for what is missing.
    """
    items = project_overview([unassessed_row(bridge_id="NEVER_SCORED")])
    assert [i.bridge_id for i in items] == ["NEVER_SCORED"]


def test_an_unassessed_bridge_carries_no_risk_object():
    item = project_overview([unassessed_row()])[0]
    assert item.current_risk is None


def test_an_unassessed_bridge_never_reads_as_a_zero_score():
    """A fabricated 0 renders as the safest possible bridge. Absence must not become good news."""
    item = project_overview([unassessed_row()])[0]
    blob = item.model_dump()
    assert blob["current_risk"] is None
    assert 0 not in [v for v in blob.values() if isinstance(v, int)]


def test_a_mixed_estate_returns_both_kinds():
    items = project_overview([joined_row(bridge_id="B1"), unassessed_row(bridge_id="B2")])
    assert [i.bridge_id for i in items] == ["B1", "B2"]
    assert items[0].current_risk is not None
    assert items[1].current_risk is None


# ------------------------------ a withheld assessment is a verdict, not an absence (P502) ---
def test_a_withheld_assessment_still_produces_a_risk_object():
    """The distinction this projection must not collapse.

    "We assessed this bridge and could not put a number on it" and "nobody has assessed this
    bridge" are different facts, and only the first one means a human already looked. Keying the
    risk object on the *score* rather than the assessment's identity erases the withheld case
    entirely — the bridge then reads as never-assessed, and the pending review that the Risk
    Agent deliberately raised disappears from the screen.
    """
    item = project_overview([withheld_row()])[0]
    assert item.current_risk is not None
    assert item.current_risk.risk_score is None


def test_a_withheld_assessment_carries_its_explanation():
    """The explanation is the entire content of a withheld verdict — it says what was missing.
    Dropping the object drops the one thing that makes the withholding actionable."""
    item = project_overview([withheld_row()])[0]
    assert item.current_risk.explanation.startswith("Withheld:")


def test_a_withheld_assessment_carries_its_pending_review_status():
    item = project_overview([withheld_row()])[0]
    assert item.current_risk.review_status == "PENDING_HUMAN_REVIEW"


def test_a_withheld_assessment_names_the_row_it_came_from():
    """INV-6 again: a withheld verdict is auditable too, and an investigator needs the id."""
    item = project_overview([withheld_row()])[0]
    assert item.current_risk.assessment_id == 501


def test_withheld_and_unassessed_are_distinguishable_in_the_response():
    """Stated as the property rather than the mechanism, so it survives a rewrite."""
    items = project_overview([withheld_row(bridge_id="B1"), unassessed_row(bridge_id="B2")])
    withheld, never = items[0], items[1]
    assert withheld.current_risk is not None
    assert never.current_risk is None


# --------------------------------------------------- a score is inseparable from its WHY ---
def test_the_risk_object_requires_an_explanation():
    """Structural (INV-7). Not "we remembered to include it" — there is no way to build the
    object without it, so no serialization path can drop it."""
    with pytest.raises(Exception):
        CurrentRisk(
            assessment_id=1, risk_score=72, severity="WARNING",
            review_status="FINAL", assessed_at=T2,
        )


def test_the_explanation_is_carried_byte_for_byte():
    """P507's guarantee begins here: the stored text is the served text, not a summary of it."""
    text = "  Strain 1.4x baseline.\n\nSecond paragraph — verbatim, including spacing.  "
    item = project_overview([joined_row() | {"explanation": text}])[0]
    assert item.current_risk.explanation == text


def test_a_score_arriving_without_an_explanation_is_refused_not_silently_served():
    """0006 makes `explanation` NOT NULL, so this row cannot exist in a healthy database.

    If it somehow does — a hand-run migration, a restored dump — the honest response is a
    failure, not a score with the WHY quietly missing. Serving it would breach INV-7 at exactly
    the moment the data is least trustworthy.
    """
    with pytest.raises(Exception):
        project_overview([joined_row() | {"explanation": None}])


# ------------------------------------------- one item per bridge, even with several current ---
def test_a_bridge_with_two_current_assessments_appears_once():
    """0006's partial unique index is per (bridge_id, cycle_id), not per bridge, so this row
    set is legal. Left alone it puts one bridge on the dashboard twice with two scores."""
    older = joined_row(assessed_at=T1, assessment_id=1) | {"risk_score": 10}
    newer = joined_row(assessed_at=T2, assessment_id=2) | {"risk_score": 90}
    items = project_overview([older, newer])
    assert len(items) == 1


def test_the_surviving_assessment_is_the_most_recent():
    """Which one wins is the whole question: showing the stale 10 hides a bridge at 90."""
    older = joined_row(assessed_at=T1, assessment_id=1) | {"risk_score": 10}
    newer = joined_row(assessed_at=T2, assessment_id=2) | {"risk_score": 90}
    for ordering in ([older, newer], [newer, older]):
        item = project_overview(ordering)[0]
        assert item.current_risk.risk_score == 90
        assert item.current_risk.assessment_id == 2


def test_an_unassessed_bridge_is_not_collapsed_into_an_assessed_one():
    items = project_overview([joined_row(bridge_id="B1"), unassessed_row(bridge_id="B2")])
    assert len(items) == 2


# ------------------------------------------------------------- tenancy (AC-2, INV-1, INV-3) ---
async def test_another_tenants_bridges_are_absent():
    """Filtered by the same predicate migration 0016 applies, not by a check in the handler."""
    rows = [
        joined_row(bridge_id="OURS", municipality_id="MUNI_A"),
        joined_row(bridge_id="THEIRS", municipality_id="MUNI_B"),
    ]
    items, _ = await fetch_overview(rows, "MUNI_A")
    assert [i.bridge_id for i in items] == ["OURS"]


async def test_a_tenant_with_no_bridges_gets_an_empty_list_not_someone_elses():
    rows = [joined_row(bridge_id="THEIRS", municipality_id="MUNI_B")]
    items, _ = await fetch_overview(rows, "MUNI_A")
    assert items == []


async def test_each_tenant_sees_only_its_own_estate():
    rows = [
        joined_row(bridge_id="A1", municipality_id="MUNI_A"),
        joined_row(bridge_id="B1", municipality_id="MUNI_B"),
        joined_row(bridge_id="A2", municipality_id="MUNI_A"),
    ]
    for scope, expected in (("MUNI_A", ["A1", "A2"]), ("MUNI_B", ["B1"])):
        items, _ = await fetch_overview(rows, scope)
        assert [i.bridge_id for i in items] == expected


def test_the_repository_cannot_be_built_from_an_unscoped_handle():
    """P203's seam, restated at the first read repository that uses it."""
    with pytest.raises(TypeError):
        BridgeOverviewRepository(FakeConnection())


def test_the_repository_inherits_the_scoped_base():
    assert issubclass(BridgeOverviewRepository, Repository)


async def test_the_query_runs_inside_the_scoped_transaction():
    """The scope statement lands before the read, so there is no window where the query could
    run unscoped."""
    _, conn = await fetch_overview([joined_row()], "MUNI_A")
    kinds = [op.kind for op in conn.ops]
    assert kinds.index("set_scope") < kinds.index("fetch")


# ------------------------------------------------------ no reading history is scanned (§6) ---
def test_the_overview_query_names_no_reading_table():
    """The headline structural guarantee. A read layer that can reach the reading tables is
    one aggregate away from forming an opinion the Risk Agent already owns."""
    sql = OVERVIEW_SQL.lower()
    for table in ("raw_readings", "validated_readings", "sensor_status", "analysis_results"):
        assert table not in sql, f"the overview scans {table}"


def test_no_module_in_the_read_layer_names_a_reading_table():
    for name, src in _read_sources():
        body = _code_only(src).lower()
        for table in ("raw_readings", "validated_readings"):
            assert table not in body, f"{name} reaches into reading history: {table}"


def test_the_overview_query_computes_no_aggregate():
    """An aggregate here is a number with no audited row behind it (INV-6)."""
    sql = OVERVIEW_SQL.lower()
    for fn in ("avg(", "sum(", "min(", "max(", "count(", "stddev(", "percentile"):
        assert fn not in sql, f"the overview computes {fn.rstrip('(')}"


def test_the_read_layer_derives_no_band():
    """P503 in advance: no threshold literals, no band arithmetic. The band is read."""
    for name, src in _read_sources():
        body = _code_only(src)
        for banned in ("if score >", "if score <", "if risk_score >", "if risk_score <",
                       "SAFE", "WATCH", "WARNING", "CRITICAL"):
            assert banned not in body, f"{name} appears to decide a band: {banned}"


# ---------------------------------------------------- the query reads current rows only ---
def test_the_query_excludes_superseded_assessments():
    """A superseded verdict is history. Serving one shows a score that has been withdrawn."""
    assert "superseded_by is null" in OVERVIEW_SQL.lower()


def test_the_query_left_joins_rather_than_inner_joins():
    """Asserted on the SQL because the fake cannot execute a join: this is the one place the
    inner-join bug could be reintroduced without any behavioural test noticing."""
    sql = " ".join(OVERVIEW_SQL.lower().split())
    assert "left join" in sql
    assert "inner join" not in sql
    assert "from bridges" in sql


def test_the_query_bounds_itself_to_one_assessment_per_bridge():
    """The SQL half of the de-duplication. The projection collapses too, but doing it here as
    well is what stops a bridge with a hundred cycles from shipping a hundred rows over the
    wire to be thrown away."""
    sql = " ".join(OVERVIEW_SQL.lower().split())
    assert "lateral" in sql
    assert "order by ra.assessed_at desc" in sql
    assert "limit 1" in sql


# ------------------------------------------------------------------- bounded, and paginated ---
def test_the_query_is_bounded():
    """No request may pull an unbounded list. P506 sets the defaults and the cap."""
    sql = OVERVIEW_SQL.lower()
    assert "limit" in sql and "offset" in sql


async def test_the_page_parameters_reach_the_query_as_bound_parameters():
    """Interpolated, they would be the one place a read path builds SQL from caller input."""
    _, conn = await fetch_overview([joined_row()], "MUNI_A", PageParams(page=3, page_size=20))
    fetches = [op for op in conn.ops if op.kind == "fetch"]
    assert fetches[0].params == (20, 40)


async def test_the_page_size_is_not_interpolated_into_the_sql():
    _, conn = await fetch_overview([joined_row()], "MUNI_A", PageParams(page=2, page_size=7))
    fetches = [op for op in conn.ops if op.kind == "fetch"]
    assert "7" not in fetches[0].sql


def test_the_projection_is_ordered_stably():
    """An unordered list re-shuffles between refreshes, so a reader cannot tell whether
    anything changed."""
    assert "order by b.id" in " ".join(OVERVIEW_SQL.lower().split())


# --------------------------------------------------------------------- structural hygiene ---
def test_the_read_layer_writes_nothing():
    """A read endpoint that can write is a read endpoint that will, eventually."""
    for name, src in _read_sources():
        body = _code_only(src).lower()
        for verb in ("insert ", "update ", "delete ", "truncate", "_execute("):
            assert verb not in body, f"{name} can write: {verb.strip()}"


def test_the_read_layer_invokes_no_agent():
    for name, src in _read_sources():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("agents"), f"{name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agents"), f"{name} imports {node.module}"


def test_the_projection_is_a_pure_function():
    """It takes rows and returns models — no store, no connection, no clock. That is what
    makes every case above testable without a database."""
    params = list(inspect.signature(project_overview).parameters)
    assert params == ["rows"]


def test_the_response_models_are_frozen():
    """A projection a caller can edit after the fact is not a projection of anything."""
    assert BridgeOverview.model_config.get("frozen") is True
    assert CurrentRisk.model_config.get("frozen") is True
