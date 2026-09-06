"""Bridges read router — P501: GET /v1/bridges overview, plus live demo reads.

Returns one item per in-scope bridge with its current (non-superseded) assessment.
No raw reading history is scanned — only risk_assessments joined to bridges.

The live endpoints (`/bridges/{id}/risk`, `/bridges/{id}/sensors/{id}/readings`) are
the demo extension: they read raw_readings directly so the dashboard reflects gateway
traffic within seconds. See read/live_risk.py for the reasoning and its limits.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from typing import Annotated

from ..db.scope import run_scoped
from ..read.bridges import BridgeOverview, OVERVIEW_SQL, project_overview
from ..read.live_risk import READINGS_WINDOW, LiveRisk, SensorReading, compute_live_risk
from ..schemas.common import PageParams


router = APIRouter(prefix="/v1", tags=["bridges"])

# Newest accelerometer readings for one bridge, newest first. The join through
# `sensors` resolves bridge -> its accelerometer without trusting the reading's own
# denormalized bridge_id, so a reading stamped with the wrong bridge cannot surface.
LIVE_RISK_SQL = """
SELECT r.value, r.sensor_time
FROM sensors AS s
JOIN raw_readings AS r ON r.sensor_id = s.id
WHERE s.bridge_id = $1
  AND s.sensor_type = 'accelerometer'
  AND r.value IS NOT NULL
ORDER BY r.sensor_time DESC
LIMIT $2
"""

SENSOR_READINGS_SQL = """
SELECT r.sensor_time, r.value
FROM raw_readings AS r
WHERE r.bridge_id = $1
  AND r.sensor_id = $2
  AND r.value IS NOT NULL
ORDER BY r.sensor_time DESC
LIMIT $3
"""


class ScopedBridgeRepo:
    """Adapts the pool-scoped query to the bridge overview projection."""

    async def list_overview(self, params: PageParams) -> list[BridgeOverview]:
        rows = await run_scoped(OVERVIEW_SQL, params.page_size, params.offset)
        return project_overview(rows)

    async def latest_readings(self, bridge_id: str) -> list[dict[str, object]]:
        return await run_scoped(LIVE_RISK_SQL, bridge_id, READINGS_WINDOW)

    async def sensor_readings(
        self, bridge_id: str, sensor_id: str, limit: int
    ) -> list[dict[str, object]]:
        rows = await run_scoped(SENSOR_READINGS_SQL, bridge_id, sensor_id, limit)
        return list(reversed(rows))


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


@router.get("/bridges/{bridge_id}/risk", response_model=LiveRisk, name="get_bridge_risk")
async def get_bridge_risk(
    bridge_id: str,
    repo: Annotated[ScopedBridgeRepo, Depends(get_bridge_repo)],
) -> LiveRisk:
    """Compute this bridge's risk from its newest raw accelerometer readings.

    Real readings only: with no readings yet the verdict is score 0 / SAFE with the
    awaiting-data explanation, never a fabricated score.
    """
    rows = await repo.latest_readings(bridge_id)
    return compute_live_risk(bridge_id, rows)


@router.get(
    "/bridges/{bridge_id}/sensors/{sensor_id}/readings",
    response_model=list[SensorReading],
    name="list_readings",
)
async def list_readings(
    bridge_id: str,
    sensor_id: str,
    repo: Annotated[ScopedBridgeRepo, Depends(get_bridge_repo)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SensorReading]:
    """Newest raw readings for one sensor, oldest-first (chart order)."""
    rows = await repo.sensor_readings(bridge_id, sensor_id, limit)
    return [SensorReading(sensor_time=row["sensor_time"], value=row["value"]) for row in rows]


__all__ = ["router"]