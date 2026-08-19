"""P204 — an unresolvable scope never reaches a query.

Two independent halves, and the independence is the point. They fail closed at
different layers, so neither one being wrong can open the door alone.

**Half 1 — the request layer (loud, primary).** A request whose credential yields no
`municipality_id` gets **401** and executes **zero** queries. Asserted by a spy, not by
reading the code: the claim "no query ran" is exactly the kind of thing that stays true
in review and stops being true in production. The spy records every operation, and the
test asserts the list is empty — not "no SELECT", *nothing at all*, not even BEGIN.

**Half 2 — the engine layer (quiet, defence-in-depth).** Migration 0016's predicate is
`municipality_id = current_setting('app.current_municipality_id', true)`. With
`missing_ok = true` an unset GUC yields NULL, and `<col> = NULL` is never true, so an
unscoped session reads **zero rows** rather than all of them. `[DB-DEP]` — no Neon
locally, so `visible_rows()` mirrors that predicate exactly.

Why model the quiet behaviour at all when P203 makes the loud one raise? Because they
guard different failures. P203's exception catches *our* bug — a repository that forgot
the seam. The RLS predicate catches everything else: a psql session, a future service, a
migration script. If the loud layer is ever bypassed, the quiet one is what stands
between one municipality and another's data. A test that only checked the exception
would leave that unverified.

Ties to tasks.md P204, spec AC-6, INV-1, INV-2.
"""
from __future__ import annotations

import re

import httpx
import pytest

from api.db.fake_connection import FakeConnection
from api.db.rls import visible_rows
from api.db.scope import UnresolvedScopeError, scoped_transaction
from api.errors import register_exception_handlers
from api.status_policy import ApiError, Failure

# A two-tenant world, mirroring db/seed/seed_dev.sql's shape.
ROWS = [
    {"id": "BRIDGE_1", "municipality_id": "MUNI_A"},
    {"id": "BRIDGE_2", "municipality_id": "MUNI_A"},
    {"id": "BRIDGE_3", "municipality_id": "MUNI_B"},
]


# ============================================================ Half 1 — request layer ===
@pytest.fixture
def spy() -> FakeConnection:
    return FakeConnection()


def _app_with_scope_resolver(spy: FakeConnection, resolver):
    """A minimal app whose one route needs a scope, wired to a spy connection.

    Deliberately not the real app: P204 must test the *seam*, and the real credential
    resolution is P301. `resolver` stands in for "what the credential yielded".
    """
    from fastapi import FastAPI

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/v1/bridges")
    async def list_bridges():
        municipality_id = resolver()
        if municipality_id is None:
            # The fail-closed branch. Note what is NOT here: no connection, no BEGIN.
            raise ApiError(Failure.MISSING_CREDENTIAL)
        async with scoped_transaction(spy, municipality_id) as scoped:
            return {"rows": await scoped.fetch("SELECT * FROM bridges")}

    return app


async def _get(app, path: str = "/v1/bridges") -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(path)


@pytest.mark.asyncio
async def test_unresolvable_scope_returns_401(spy: FakeConnection):
    resp = await _get(_app_with_scope_resolver(spy, lambda: None))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unresolvable_scope_executes_zero_queries(spy: FakeConnection):
    """The headline check. Not 'no SELECT ran' — nothing ran, not even BEGIN."""
    await _get(_app_with_scope_resolver(spy, lambda: None))
    assert spy.ops == [], f"a query ran without a scope: {spy.ops}"


@pytest.mark.asyncio
async def test_unresolvable_scope_opens_no_transaction(spy: FakeConnection):
    await _get(_app_with_scope_resolver(spy, lambda: None))
    assert spy.in_transaction is False
    assert spy.current_scope is None


@pytest.mark.asyncio
async def test_401_body_is_the_standard_envelope(spy: FakeConnection):
    resp = await _get(_app_with_scope_resolver(spy, lambda: None))
    body = resp.json()
    assert set(body) == {"error", "code", "detail", "correlation_id"}
    assert body["code"] == Failure.MISSING_CREDENTIAL.value


@pytest.mark.asyncio
async def test_401_body_names_no_tenant_and_no_internals(spy: FakeConnection):
    """A 401 must not become a probe. It says nothing about what exists."""
    resp = await _get(_app_with_scope_resolver(spy, lambda: None))
    blob = resp.text.lower()
    for banned in ("muni_", "bridge_", "app.current_municipality_id", "set_config",
                   "select", "traceback", ".py"):
        assert banned not in blob, f"{banned!r} leaked into a 401 body"


@pytest.mark.asyncio
async def test_a_resolvable_scope_does_reach_a_query(spy: FakeConnection):
    """The other side of the gate — else 'zero queries' passes by doing nothing at all."""
    spy.rows = [{"id": "BRIDGE_1"}]
    resp = await _get(_app_with_scope_resolver(spy, lambda: "MUNI_A"))
    assert resp.status_code == 200
    kinds = [op.kind for op in spy.ops]
    assert kinds[0] == "begin" and kinds[1] == "set_scope" and "fetch" in kinds


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", ["", "   ", "\t\n"])
async def test_blank_scope_is_refused_before_any_query(spy: FakeConnection, empty: str):
    """A credential yielding whitespace is unresolvable, not a tenant named ' '."""
    with pytest.raises(UnresolvedScopeError):
        async with scoped_transaction(spy, empty):
            pass
    assert spy.ops == []


@pytest.mark.asyncio
async def test_unresolved_scope_error_carries_no_tenant_guess(spy: FakeConnection):
    """The exception must not invent a fallback tenant.

    Checks for a tenant *identifier*, not the word "municipality" — the message is
    allowed (and expected) to explain that a municipality scope is what is missing.
    What it must never do is name one, which would hint that a default exists.
    """
    with pytest.raises(UnresolvedScopeError) as exc:
        async with scoped_transaction(spy, None):
            pass
    message = str(exc.value)
    assert not re.search(r"MUNI_\w+", message.upper()), (
        f"the fail-closed error names a tenant: {message!r}"
    )
    assert "default" not in message.lower()


# ============================================================= Half 2 — engine layer ===
def test_unset_scope_sees_zero_rows():
    """`<col> = NULL` is never true — the whole fail-closed argument in one line."""
    assert visible_rows(ROWS, None) == []


def test_unset_scope_does_not_see_all_rows():
    """The failure being guarded: fail-OPEN would return everything."""
    assert len(visible_rows(ROWS, None)) < len(ROWS)


def test_empty_string_scope_sees_zero_rows():
    """An empty GUC is not a wildcard. It matches no municipality_id."""
    assert visible_rows(ROWS, "") == []


def test_a_set_scope_sees_only_its_own_tenant():
    seen = visible_rows(ROWS, "MUNI_A")
    assert [r["id"] for r in seen] == ["BRIDGE_1", "BRIDGE_2"]
    assert all(r["municipality_id"] == "MUNI_A" for r in seen)


def test_the_other_tenant_is_invisible_not_forbidden():
    """INV-2/INV-3: B's rows are simply absent from A's read — the basis for 404."""
    seen = visible_rows(ROWS, "MUNI_A")
    assert not any(r["id"] == "BRIDGE_3" for r in seen)


def test_an_unknown_scope_sees_zero_rows():
    """A well-formed but non-existent tenant reads empty, never everything."""
    assert visible_rows(ROWS, "MUNI_NOPE") == []


def test_scope_matching_is_exact_not_prefix():
    """`LIKE`-style matching here would let MUNI_A read MUNI_A2."""
    rows = ROWS + [{"id": "BRIDGE_4", "municipality_id": "MUNI_A2"}]
    assert [r["id"] for r in visible_rows(rows, "MUNI_A")] == ["BRIDGE_1", "BRIDGE_2"]


def test_a_row_with_no_municipality_is_never_visible():
    """0015 makes the column NOT NULL; if one ever appears, it belongs to nobody."""
    rows = [{"id": "ORPHAN", "municipality_id": None}]
    assert visible_rows(rows, "MUNI_A") == []
    assert visible_rows(rows, None) == []


def test_visible_rows_does_not_mutate_its_input():
    before = [dict(r) for r in ROWS]
    visible_rows(ROWS, "MUNI_A")
    assert ROWS == before
