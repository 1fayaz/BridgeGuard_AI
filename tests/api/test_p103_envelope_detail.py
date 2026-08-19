"""P103 — the error envelope carries `detail`, and still leaks nothing.

Spec §Error responses: `{error, code, detail, correlation_id}`. The Spec-003 build
had three of four fields. Without `detail`, a 422 cannot say *which* field failed —
the client is told "validation failed" and must guess.

The hard part is that `detail` is the field most likely to leak. It is the one place
a well-meaning handler writes "helpful" text, and the raw material to hand is an
exception string full of SQL, file paths, and library names. So the leak assertions
here are deliberately stricter than P101's: not just "no traceback", but no SQL
keyword, no absolute path, no library name, no internal secret — checked against
`detail` specifically as well as the whole body.

Finding 2 (P101) resolved: the built field semantics stand — `error` is the stable
machine code's human-readable partner and `code` is the machine code. The spec text
was corrected to match rather than the code.

Ties to tasks.md P103, spec AC-5, INV-4.
"""
from __future__ import annotations

import logging

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from api.errors import register_exception_handlers
from api.schemas.errors import ErrorResponse

ENVELOPE_KEYS = {"error", "code", "detail", "correlation_id"}

# Substrings that must never appear in any client-visible body.
LEAK_MARKERS = (
    "hunter2", "secret internal detail", "RuntimeError", "Traceback",
    "SELECT", "INSERT", "psycopg", "sqlalchemy", "site-packages",
    "D:\\giaic", "/src/api/", ".py", "pydantic_core",
)


class _Body(BaseModel):
    sensor_id: str
    value: float


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail: db password = hunter2")

    @app.get("/sqlboom")
    def sqlboom():
        raise RuntimeError(
            "psycopg.errors.UndefinedTable: SELECT * FROM raw_readings failed at "
            "D:\\giaic\\BridgeGuard\\src\\api\\repo.py line 42"
        )

    @app.get("/teapot")
    def teapot():
        raise HTTPException(status_code=418, detail="I'm a teapot")

    @app.post("/validate")
    def validate(body: _Body):
        return {"ok": True}

    return app


@pytest_asyncio.fixture
async def c():
    transport = httpx.ASGITransport(app=_build_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as cl:
        yield cl


# ------------------------------------------------------------------ all four fields ---
def test_schema_declares_detail():
    assert "detail" in ErrorResponse.model_fields


@pytest.mark.asyncio
async def test_internal_error_returns_all_four_fields(c):
    resp = await c.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    # Exact set, kept from T002: a loose check would stop catching field leakage.
    assert set(body.keys()) == ENVELOPE_KEYS
    assert body["code"] == "internal_error"
    assert body["detail"]
    assert body["correlation_id"]


@pytest.mark.asyncio
async def test_http_error_returns_all_four_fields(c):
    body = (await c.get("/teapot")).json()
    assert set(body.keys()) == ENVELOPE_KEYS
    assert body["code"] == "http_418"


@pytest.mark.asyncio
async def test_validation_error_detail_names_the_offending_field(c):
    resp = await c.post("/validate", json={"value": "not-a-number"})
    assert resp.status_code == 422
    body = resp.json()
    assert set(body.keys()) == ENVELOPE_KEYS
    assert body["code"] == "validation_error"
    # The whole point of `detail`: say WHICH field, without echoing internals.
    assert "sensor_id" in body["detail"] or "value" in body["detail"]


# ------------------------------------------------------------------------- no leakage ---
@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/boom", "/sqlboom"])
async def test_no_internals_leak_anywhere_in_body(c, path):
    raw = (await c.get(path)).text
    for marker in LEAK_MARKERS:
        assert marker not in raw, f"{marker!r} leaked into the response body"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/boom", "/sqlboom"])
async def test_detail_field_specifically_is_safe(c, path):
    detail = (await c.get(path)).json()["detail"]
    for marker in LEAK_MARKERS:
        assert marker not in detail, f"{marker!r} leaked into `detail`"


@pytest.mark.asyncio
async def test_validation_detail_does_not_echo_raw_input(c):
    # A rejected value must not be reflected back verbatim — that is how an
    # injected payload reaches a log viewer or a browser.
    resp = await c.post("/validate", json={"sensor_id": "<script>x</script>", "value": "bad"})
    assert "<script>" not in resp.text


# --------------------------------------------------------- detail is logged internally ---
@pytest.mark.asyncio
async def test_full_detail_reaches_the_log_under_the_same_correlation_id(c, caplog):
    with caplog.at_level(logging.ERROR, logger="bridgeguard.api"):
        body = (await c.get("/boom")).json()
    logged = caplog.text
    # The correlation id ties the safe client response to the full internal record.
    assert body["correlation_id"] in logged
    # And the internal record is the one that keeps the real cause.
    assert "hunter2" in logged, "the real cause must survive in the log, not the response"
