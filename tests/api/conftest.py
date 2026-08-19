"""Shared API test fixtures.

Uses httpx.ASGITransport instead of starlette TestClient: httpx>=0.28 removed
the `app=` shortcut that the bundled TestClient relies on, so we drive the ASGI
app directly via an AsyncClient.
"""
from __future__ import annotations

import httpx
import pytest_asyncio

from api.main import app


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
