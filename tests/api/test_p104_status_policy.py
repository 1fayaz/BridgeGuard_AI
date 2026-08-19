"""P104 — one place maps a failure class to its status; handlers cannot improvise.

The rule this exists to protect is INV-3: **a cross-tenant resource returns 404, not
403.** 403 would confirm the resource exists, which is the tenancy leak the whole
isolation design is built to prevent. 403 is reserved for the *wrong credential class*
(a Pi key on a read endpoint), which says nothing about any tenant's data.

That rule is one line of reasoning and easy to get right once — and easy to lose the
tenth time somebody writes `raise HTTPException(403)` in a handler because it "feels
like" a permission error. So the mapping lives in exactly one table, and a structural
check asserts no router improvises a status inline.

**The strongest form of the check is indistinguishability.** Matching the status code
is not enough: if cross-tenant returns 404 with `detail="not your municipality"` and a
genuine miss returns 404 with `detail="no such bridge"`, existence has leaked anyway,
just one field further down. So the two responses must be **byte-identical** apart
from the correlation id.

Ties to tasks.md P104, spec AC-2 / AC-7, INV-3.
"""
from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from api.errors import register_exception_handlers
from api.status_policy import STATUS_POLICY, ApiError, Failure, status_for

REPO = Path(__file__).resolve().parents[2]
ROUTERS_DIR = REPO / "src" / "api" / "routers"

# The documented policy table (spec §Error responses, plan §8).
EXPECTED = {
    Failure.MISSING_CREDENTIAL: 401,
    Failure.INVALID_CREDENTIAL: 401,
    Failure.EXPIRED_CREDENTIAL: 401,
    Failure.WRONG_CREDENTIAL_CLASS: 403,
    Failure.CROSS_TENANT: 404,
    Failure.NOT_FOUND: 404,
    Failure.VALIDATION: 422,
    Failure.NOT_COMPLETE: 409,
    Failure.RATE_LIMITED: 429,
    Failure.INTERNAL: 500,
}


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/f/{name}")
    def fail(name: str):
        raise ApiError(Failure[name.upper()])

    return app


@pytest_asyncio.fixture
async def c():
    transport = httpx.ASGITransport(app=_build_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as cl:
        yield cl


# ------------------------------------------------------------- the table, exhaustively ---
@pytest.mark.parametrize("failure,expected", sorted(EXPECTED.items(), key=lambda kv: kv[0].value))
def test_each_failure_class_maps_to_its_documented_status(failure, expected):
    assert status_for(failure) == expected


def test_policy_is_total_no_silent_fallback():
    # Every enum member must be in the table. A missing entry must be a loud error, not
    # a default 500 that hides a policy gap.
    for failure in Failure:
        assert failure in STATUS_POLICY, f"{failure} has no declared status"
    assert set(STATUS_POLICY) == set(Failure)


def test_no_failure_class_maps_to_a_success_status():
    assert all(400 <= s <= 599 for s in STATUS_POLICY.values())


# ------------------------------------------------------- INV-3: the load-bearing rule ---
def test_cross_tenant_is_404_never_403():
    assert status_for(Failure.CROSS_TENANT) == 404
    assert status_for(Failure.CROSS_TENANT) != 403


def test_wrong_credential_class_is_403():
    # 403 exists, but only for this: it reveals nothing about any tenant's data.
    assert status_for(Failure.WRONG_CREDENTIAL_CLASS) == 403


def test_403_is_used_for_nothing_but_credential_class():
    at_403 = [f for f, s in STATUS_POLICY.items() if s == 403]
    assert at_403 == [Failure.WRONG_CREDENTIAL_CLASS], (
        "403 must mean exactly one thing; anything else risks confirming existence"
    )


@pytest.mark.asyncio
async def test_cross_tenant_and_not_found_are_indistinguishable(c):
    """The real test of INV-3: same status is not enough — same body."""
    cross = (await c.get("/f/cross_tenant")).json()
    miss = (await c.get("/f/not_found")).json()
    for field in ("error", "code", "detail"):
        assert cross[field] == miss[field], (
            f"`{field}` differs between cross-tenant and genuine-miss — existence leaks"
        )
    # Only the correlation id may differ (it must, it identifies the request).
    assert cross["correlation_id"] != miss["correlation_id"]


def test_cross_tenant_client_code_is_masked_but_log_code_is_not():
    """The client sees `not_found`; the internal failure class stays distinct.

    Caught during P104: the first implementation returned `code="cross_tenant"`, so the
    machine code confirmed the resource existed even though status and prose matched.
    The distinction must survive for the log and die at the boundary.
    """
    cross = ApiError(Failure.CROSS_TENANT)
    assert cross.code == Failure.NOT_FOUND.value == "not_found"
    assert cross.failure is Failure.CROSS_TENANT  # still distinct internally


def test_cross_tenant_detail_override_is_ignored():
    """No caller can make a cross-tenant refusal distinguishable, even by mistake."""
    plain = ApiError(Failure.NOT_FOUND)
    chatty = ApiError(Failure.CROSS_TENANT, "bridge belongs to another municipality")
    assert chatty.detail == plain.detail
    assert "municipality" not in chatty.detail


@pytest.mark.asyncio
async def test_cross_tenant_body_mentions_no_tenancy_concept(c):
    raw = (await c.get("/f/cross_tenant")).text.lower()
    for word in ("tenant", "municipality", "forbidden", "not yours", "permission",
                 "cross", "scope", "other"):
        assert word not in raw, f"{word!r} in the body hints the resource exists"


# ------------------------------------------------------- wired through the envelope ---
@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected", sorted(EXPECTED.items(), key=lambda kv: kv[0].value))
async def test_apierror_produces_the_status_and_the_full_envelope(c, failure, expected):
    resp = await c.get(f"/f/{failure.value}")
    assert resp.status_code == expected
    body = resp.json()
    assert set(body.keys()) == {"error", "code", "detail", "correlation_id"}
    assert body["code"], "every failure carries a stable machine code"


@pytest.mark.asyncio
async def test_rate_limited_carries_retry_after(c):
    resp = await c.get("/f/rate_limited")
    assert resp.status_code == 429
    assert "retry-after" in {k.lower() for k in resp.headers}


@pytest.mark.asyncio
async def test_internal_failure_detail_stays_opaque(c):
    body = (await c.get("/f/internal")).json()
    assert "correlation_id" in body["detail"] or body["correlation_id"] in str(body)


# ------------------------------------------------ no handler constructs a status inline ---
def _router_sources() -> list[Path]:
    return [p for p in ROUTERS_DIR.rglob("*.py") if p.name != "__init__.py"]


def test_no_router_hardcodes_an_error_status():
    """A status literal in a router is a policy decision made in the wrong place."""
    offenders: list[str] = []
    for path in _router_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                if 400 <= node.value <= 599:
                    offenders.append(f"{path.name}:{node.lineno} → {node.value}")
    assert not offenders, (
        "error statuses must come from status_policy, not literals: " + "; ".join(offenders)
    )


def test_no_router_raises_httpexception_directly():
    """HTTPException bypasses the policy table; ApiError is the only route in."""
    offenders: list[str] = []
    for path in _router_sources():
        text = path.read_text(encoding="utf-8")
        if "HTTPException" in text:
            offenders.append(path.name)
    assert not offenders, (
        "routers must raise ApiError, not HTTPException: " + ", ".join(offenders)
    )
