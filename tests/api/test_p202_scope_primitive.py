"""P202 — the one mechanism that opens a scoped transaction.

This is the seam the whole isolation design rests on. Every query in the layer runs
inside a transaction that has already issued `SET LOCAL app.current_municipality_id`.

Four things must hold, and each has a specific failure mode behind it:

**The GUC name is exactly `app.current_municipality_id`.** Spec 003's plan said
`app.municipality_id`. Because the design is fail-closed, the wrong name does not raise
— every policy predicate simply fails to match and the system returns **zero rows
everywhere**, presenting as "no data" rather than as a bug. This is the documented
highest-risk carry-over in the layer (plan §0), so it is pinned here and again in P206.

**The value is TEXT, uncast.** The tenant key is `MUNI_A`, not a uuid. A `::uuid` cast
would raise on real data.

**`SET LOCAL`, never session `SET`.** On a pooled connection a session-level GUC
outlives the request and leaks one tenant's scope into the next caller's queries. This
is the foot-gun `db/migrations/RLS.md` calls out explicitly.

**Parameterized, never string-built.** The tenant id reaches Postgres as a bound
parameter via `set_config(..., is_local => true)`, so the injection surface at the
tenancy seam is closed by construction rather than by escaping.

Ties to tasks.md P202, spec AC-6, INV-1, plan §3.
"""
from __future__ import annotations

import inspect

import pytest

from api.db.scope import (
    GUC_NAME,
    ScopeNotSetError,
    ScopedConnection,
    UnresolvedScopeError,
    scoped_transaction,
)
from api.db.fake_connection import FakeConnection


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection()


# ------------------------------------------------------------------- the exact GUC ---
def test_guc_name_is_exact():
    assert GUC_NAME == "app.current_municipality_id"


def test_guc_name_is_not_the_spec003_wrong_name():
    # The silent-zero-rows failure. Named explicitly so a rename cannot pass quietly.
    assert GUC_NAME != "app.municipality_id"
    assert GUC_NAME != "app.tenant_id"
    assert GUC_NAME != "current_municipality_id"


# --------------------------------------------------------- the emitted statement ---
@pytest.mark.asyncio
async def test_scope_is_set_before_any_query(conn: FakeConnection):
    async with scoped_transaction(conn, "MUNI_A") as scoped:
        await scoped.fetch("SELECT 1")
    # The scope statement must be the first thing after BEGIN, not merely present.
    kinds = [op.kind for op in conn.ops]
    assert kinds[0] == "begin"
    assert kinds[1] == "set_scope"
    assert "fetch" in kinds
    assert kinds.index("set_scope") < kinds.index("fetch")


@pytest.mark.asyncio
async def test_scope_uses_set_config_with_is_local_true(conn: FakeConnection):
    async with scoped_transaction(conn, "MUNI_A"):
        pass
    scope_op = next(op for op in conn.ops if op.kind == "set_scope")
    sql = scope_op.sql.lower()
    assert "set_config" in sql, "must use the parameterized set_config form"
    assert "true" in sql, "is_local must be true — transaction-scoped"


@pytest.mark.asyncio
async def test_tenant_id_is_a_bound_parameter_not_string_built(conn: FakeConnection):
    async with scoped_transaction(conn, "MUNI_A"):
        pass
    scope_op = next(op for op in conn.ops if op.kind == "set_scope")
    # The id must arrive as a parameter, never interpolated into the statement text.
    assert "MUNI_A" not in scope_op.sql
    assert "MUNI_A" in scope_op.params


@pytest.mark.asyncio
async def test_no_uuid_cast_anywhere(conn: FakeConnection):
    async with scoped_transaction(conn, "MUNI_A"):
        pass
    for op in conn.ops:
        assert "::uuid" not in op.sql.lower(), "the tenant key is TEXT, not uuid"


@pytest.mark.asyncio
async def test_never_uses_session_level_set(conn: FakeConnection):
    async with scoped_transaction(conn, "MUNI_A"):
        pass
    for op in conn.ops:
        sql = op.sql.lower()
        # A bare `SET app...` (no LOCAL, no set_config) is the pooled-connection leak.
        if "app.current_municipality_id" in sql and "set_config" not in sql:
            assert "set local" in sql, f"session-level SET leaks across requests: {op.sql}"


def test_source_contains_no_session_level_set():
    """Belt-and-braces: the module itself must not contain a session-scope statement."""
    import api.db.scope as mod

    src = inspect.getsource(mod).lower()
    assert "is_local" in src or "set local" in src
    # A plain `set app.` with no LOCAL would be the foot-gun.
    assert "\"set app." not in src and "'set app." not in src


# ------------------------------------------------------------------- fail-closed ---
@pytest.mark.asyncio
async def test_empty_scope_is_refused_before_any_query(conn: FakeConnection):
    with pytest.raises(UnresolvedScopeError):
        async with scoped_transaction(conn, ""):
            pass
    # Nothing ran at all — not even BEGIN.
    assert conn.ops == []


@pytest.mark.asyncio
async def test_none_scope_is_refused(conn: FakeConnection):
    with pytest.raises(UnresolvedScopeError):
        async with scoped_transaction(conn, None):
            pass
    assert conn.ops == []


@pytest.mark.asyncio
async def test_whitespace_scope_is_refused(conn: FakeConnection):
    with pytest.raises(UnresolvedScopeError):
        async with scoped_transaction(conn, "   "):
            pass
    assert conn.ops == []


# ------------------------------------------------- transaction lifecycle / no leak ---
@pytest.mark.asyncio
async def test_commits_on_success_and_clears_scope(conn: FakeConnection):
    async with scoped_transaction(conn, "MUNI_A") as scoped:
        await scoped.fetch("SELECT 1")
    assert conn.ops[-1].kind == "commit"
    # SET LOCAL dies with the transaction: the fake mirrors that reset.
    assert conn.current_scope is None


@pytest.mark.asyncio
async def test_rolls_back_on_error_and_clears_scope(conn: FakeConnection):
    with pytest.raises(RuntimeError):
        async with scoped_transaction(conn, "MUNI_A") as scoped:
            await scoped.fetch("SELECT 1")
            raise RuntimeError("boom")
    assert conn.ops[-1].kind == "rollback"
    assert conn.current_scope is None


@pytest.mark.asyncio
async def test_scope_does_not_leak_to_the_next_transaction(conn: FakeConnection):
    """The pooled-connection case: request N+1 must not inherit request N's tenant."""
    async with scoped_transaction(conn, "MUNI_A") as scoped:
        assert scoped.municipality_id == "MUNI_A"
    assert conn.current_scope is None
    async with scoped_transaction(conn, "MUNI_B") as scoped:
        assert scoped.municipality_id == "MUNI_B"
    assert conn.current_scope is None


@pytest.mark.asyncio
async def test_query_outside_a_scoped_transaction_fails_loudly(conn: FakeConnection):
    """Not "returns zero rows" — raises. A silent empty result reads as 'no data'."""
    with pytest.raises(ScopeNotSetError):
        await conn.fetch("SELECT * FROM bridges")


@pytest.mark.asyncio
async def test_scoped_handle_cannot_outlive_its_transaction(conn: FakeConnection):
    async with scoped_transaction(conn, "MUNI_A") as scoped:
        pass
    # Holding the handle past the block must not grant an unscoped query.
    with pytest.raises(ScopeNotSetError):
        await scoped.fetch("SELECT 1")


@pytest.mark.asyncio
async def test_scoped_connection_exposes_no_raw_handle():
    """No escape hatch: a handler must not be able to reach an unscoped connection."""
    for name in ("connection", "conn", "raw", "pool", "cursor", "acquire"):
        assert not hasattr(ScopedConnection, name), (
            f"ScopedConnection.{name} would be an unscoped escape hatch"
        )


@pytest.mark.asyncio
async def test_nested_scope_change_is_refused(conn: FakeConnection):
    """One transaction, one tenant. Re-scoping mid-transaction is a design error."""
    with pytest.raises(Exception):
        async with scoped_transaction(conn, "MUNI_A"):
            async with scoped_transaction(conn, "MUNI_B"):
                pass
