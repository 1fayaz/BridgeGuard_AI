"""T002 — structured error envelope + global exception handler (AC-5 / INV-4).

Asserts that an unhandled exception becomes a clean envelope with a correlation_id
and NO stack trace / internal detail in the response body.

Updated at P103: the envelope gained the spec's fourth field, `detail`. The exact-set
key assertions below are kept exact on purpose — a loose `>=` check would stop
catching a field accidentally leaking into the envelope.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from api.errors import register_exception_handlers


def _build_app_with_failing_routes() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail: db password = hunter2")

    @app.get("/teapot")
    def teapot():
        raise HTTPException(status_code=418, detail="I'm a teapot")

    return app


@pytest_asyncio.fixture
async def err_client():
    app = _build_app_with_failing_routes()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_unhandled_exception_returns_clean_envelope(err_client):
    resp = await err_client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert set(body.keys()) == {"error", "code", "detail", "correlation_id"}
    assert body["code"] == "internal_error"
    assert body["error"] == "An internal error occurred."
    assert body["correlation_id"]


@pytest.mark.asyncio
async def test_no_internal_detail_leaks(err_client):
    resp = await err_client.get("/boom")
    raw = resp.text
    # The internal exception message / secrets must never reach the client.
    assert "hunter2" not in raw
    assert "secret internal detail" not in raw
    assert "RuntimeError" not in raw
    assert "Traceback" not in raw


@pytest.mark.asyncio
async def test_http_exception_uses_same_envelope(err_client):
    resp = await err_client.get("/teapot")
    assert resp.status_code == 418
    body = resp.json()
    assert set(body.keys()) == {"error", "code", "detail", "correlation_id"}
    assert body["code"] == "http_418"
    assert body["error"] == "I'm a teapot"
