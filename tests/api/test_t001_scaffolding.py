"""T001 — app factory + structure. Verifies the app starts and core routes load."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_200(client):
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_openapi_schema_loads(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["info"]["title"] == "BridgeGuard Backend API"
    assert "/v1/health" in body["paths"]


@pytest.mark.asyncio
async def test_docs_loads(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
