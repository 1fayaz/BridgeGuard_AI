"""Bridges read router — P501: GET /v1/bridges overview.

Returns one item per in-scope bridge with its current (non-superseded) assessment.
No raw reading history is scanned — only risk_assessments joined to bridges.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Annotated

from api.db.pool import run_scoped, init_pool, close_pool
from api.db.repository import Repository
from api.read.bridges import (
    BridgeOverview,
    BridgeOverviewRepository,
    OVERVIEW_SQL,
    project_overview,
)
from api.schemas.common import PageParams


router = APIRouter(prefix="/v1", tags=["bridges"])


# --- Lifespan integration --------------------------------------------------------

async def startup() -> None:
    await init_pool()


async def shutdown() -> None:
    await close_pool()


# --- Dependency: repository bound to scoped connection ---------------------------

class ScopedBridgeRepo:
    """Adapts the pool-scoped query to the BridgeOverviewRepository interface."""

    async def list_overview(self, params: PageParams) -> list[BridgeOverview]:
        rows = await run_scoped(OVERVIEW_SQL, params.page_size, params.offset)
        return project_overview(rows)


async def get_bridge_repo() -> ScopedBridgeRepo:
    return ScopedBridgeRepo()


# --- Endpoints -------------------------------------------------------------------

@router.get("/bridges", response_model=list[BridgeOverview], name="list_bridges")
async def list_bridges(
    repo: Annotated[ScopedBridgeRepo, Depends(get_bridge_repo)],
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    page: Annotated[int, Query(ge=1)] = 1,
) -> list[BridgeOverview]:
    """List all bridges in the current municipality with their latest risk assessment.

    Returns one row per bridge. Bridges with no assessment have `current_risk: null`.
    """
    params = PageParams(page_size=page_size, offset=(page - 1) * page_size)
    return await repo.list_overview(params)


# Expose for main.py lifespan
__all__ = ["router", "startup", "shutdown"]