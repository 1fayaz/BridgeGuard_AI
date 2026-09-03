"""Bridges read router — P501: GET /v1/bridges overview.

Returns one item per in-scope bridge with its current (non-superseded) assessment.
No raw reading history is scanned — only risk_assessments joined to bridges.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import Annotated

from ..db.scope import run_scoped
from ..read.bridges import BridgeOverview, OVERVIEW_SQL, project_overview
from ..schemas.common import PageParams


router = APIRouter(prefix="/v1", tags=["bridges"])


class ScopedBridgeRepo:
    """Adapts the pool-scoped query to the bridge overview projection."""

    async def list_overview(self, params: PageParams) -> list[BridgeOverview]:
        rows = await run_scoped(OVERVIEW_SQL, params.page_size, params.offset)
        return project_overview(rows)


async def get_bridge_repo() -> ScopedBridgeRepo:
    return ScopedBridgeRepo()


@router.get("/bridges", response_model=list[BridgeOverview], name="list_bridges")
async def list_bridges(
    repo: Annotated[ScopedBridgeRepo, Depends(get_bridge_repo)],
    params: Annotated[PageParams, Depends()],
) -> list[BridgeOverview]:
    """List all bridges in the current municipality with their latest risk assessment.

    Returns one row per bridge. Bridges with no assessment have `current_risk: null`.
    """
    return await repo.list_overview(params)


__all__ = ["router"]