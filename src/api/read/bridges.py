"""P501 — `GET /bridges`: one item per in-scope bridge, from current assessments.

The dashboard's first screen. Three decisions carry the weight, and each has a specific way
the screen lies if it goes the other way.

**LEFT JOIN, never INNER.** An inner join drops every bridge the Risk Agent has not scored, and
the resulting list looks complete — there is no gap to notice. A bridge nobody has assessed then
becomes indistinguishable from a bridge that does not exist. "Not known" is a state this screen
has to be able to show, so an unassessed bridge is present with no risk attached.

**Bridges and current assessments only.** No reading table is named here. That is not only about
the <500 ms target: a read layer that can reach `raw_readings` is one aggregate away from
producing a mean or a latest-value, and that number would be a second opinion competing with the
DCA's with no audited row behind it (Principle III, INV-6).

**One row per bridge, chosen by recency.** 0006's partial unique index is per
`(bridge_id, cycle_id)` among current rows — per *cycle*, not per bridge — so a bridge with two
un-superseded assessments from different cycles legitimately yields two rows. The LATERAL picks
the newest at the database, and `project_overview` collapses again in Python. Belt and braces on
purpose: the SQL keeps a bridge with a hundred cycles from shipping a hundred rows over the wire,
and the Python half is the part that is testable without Neon.

`explanation` is required on `CurrentRisk`, so a score cannot be serialized without its WHY by
any path (INV-7). That is 0006's own `explanation_present` constraint restated in the response
model rather than a new rule invented here.

[DB-DEP] Runs against `FakeConnection` locally, which applies 0016's RLS predicate. Tenant
isolation is the database's, not a filter in this module — there is no `municipality_id` in the
projection code at all, and that absence is the design (INV-2).

Ties to tasks.md P501, spec AC-2 + §6, plan §6.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Mapping

from api.db.repository import Repository
from api.schemas.common import PageParams
from api.schemas.null_honest import NullHonestModel

# The LATERAL is what makes this "current state" rather than "history": for each bridge, the
# single most recent assessment that has not been superseded. `superseded_by IS NULL` is the
# whole difference between a live verdict and one that has been withdrawn.
OVERVIEW_SQL: Final = """
SELECT
    b.id            AS bridge_id,
    b.municipality_id,
    b.name,
    b.location,
    ra.id           AS assessment_id,
    ra.risk_score,
    ra.severity,
    ra.explanation,
    ra.review_status,
    ra.assessed_at
FROM bridges AS b
LEFT JOIN LATERAL (
    SELECT ra.id, ra.risk_score, ra.severity, ra.explanation,
           ra.review_status, ra.assessed_at
    FROM risk_assessments AS ra
    WHERE ra.bridge_id = b.id
      AND ra.superseded_by IS NULL
    ORDER BY ra.assessed_at DESC
    LIMIT 1
) AS ra ON TRUE
ORDER BY b.id
LIMIT $1 OFFSET $2
"""


class CurrentRisk(NullHonestModel):
    """The bridge's live verdict, as the Risk Agent wrote it.

    `explanation` is required and has no default. A score without its WHY is not a thing this
    model can express, so no serialization path can produce one (INV-7).

    `risk_score` and `severity` are nullable but *not optional* — no defaults. 0006 makes them
    NULL together on a withheld assessment, so the model has to be able to hold the null; giving
    it a default would additionally let one appear when no row said so, which is the fabrication
    P502 exists to prevent. Nullable is the data's shape; optional would be a fallback.

    `NullHonestModel` keeps those nulls on the wire: a `risk_score` key that is missing rather
    than null is read by a dashboard as `undefined` and rendered as whatever its fallback is
    (P502).
    """

    assessment_id: int
    risk_score: int | None
    severity: str | None
    explanation: str
    review_status: str
    assessed_at: datetime


class BridgeOverview(NullHonestModel):
    """One line on the dashboard.

    `current_risk` is None when no assessment exists — distinct from an assessment that exists
    and withheld its score, which is a `CurrentRisk` with a null `risk_score` (P502). Both are
    distinct from a genuine 0, which is a real audited verdict and is served as 0.
    """

    bridge_id: str
    name: str
    location: str | None
    current_risk: CurrentRisk | None


def project_overview(rows: list[Mapping[str, Any]]) -> list[BridgeOverview]:
    """Project joined rows onto one item per bridge. Pure: rows in, models out.

    Keeps the newest assessment when a bridge has more than one current row. Order is the row
    order the query established, so `ORDER BY b.id` is what makes a refresh comparable to the
    one before it.
    """
    chosen: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        bridge_id = str(row["bridge_id"])
        held = chosen.get(bridge_id)
        if held is None or _is_newer(row, held):
            chosen[bridge_id] = row
    return [_item(row) for row in chosen.values()]


def _is_newer(candidate: Mapping[str, Any], held: Mapping[str, Any]) -> bool:
    """Later `assessed_at` wins; an assessed row always beats an unassessed one."""
    theirs = held.get("assessed_at")
    ours = candidate.get("assessed_at")
    if ours is None:
        return False
    if theirs is None:
        return True
    return ours > theirs


def _item(row: Mapping[str, Any]) -> BridgeOverview:
    return BridgeOverview(
        bridge_id=str(row["bridge_id"]),
        name=str(row["name"]),
        location=row.get("location"),
        current_risk=_risk(row),
    )


def _risk(row: Mapping[str, Any]) -> CurrentRisk | None:
    """The assessment's own id decides whether there is a verdict — not the score.

    A withheld assessment has a NULL score and is still a real, audited row with an
    explanation. Keying on `risk_score` instead would erase exactly the case the Risk Agent
    went to some trouble to make visible (FR-6/FR-7).
    """
    if row.get("assessment_id") is None:
        return None
    return CurrentRisk(
        assessment_id=row["assessment_id"],
        risk_score=row.get("risk_score"),
        severity=row.get("severity"),
        explanation=row.get("explanation"),
        review_status=row.get("review_status"),
        assessed_at=row.get("assessed_at"),
    )


class BridgeOverviewRepository(Repository):
    """Reads the overview through an already-scoped handle (P203)."""

    async def list_overview(self, params: PageParams) -> list[BridgeOverview]:
        rows = await self._fetch(OVERVIEW_SQL, params.page_size, params.offset)
        return project_overview(rows)
