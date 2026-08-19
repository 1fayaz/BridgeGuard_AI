"""P205 — request N+1 must not inherit request N's tenant.

This is the failure that makes `SET LOCAL` non-negotiable, and it is worth stating
plainly because it is not hypothetical. A connection pool hands the *same* physical
connection to unrelated requests. A session-level `SET app.current_municipality_id`
survives the request that issued it, so the next caller — a different municipality,
possibly a different credential class — runs their queries under the previous tenant's
scope. Nothing errors. Both requests return 200. One of them silently reads another
municipality's bridge data.

`SET LOCAL` (here, `set_config(..., is_local => true)`) resets at commit **and** at
rollback, which closes it. These tests prove the reset actually happens on both paths,
on a connection that is genuinely reused.

The vacuity trap is real here: a test that quietly gets a fresh connection per request
proves nothing, because a fresh connection has no scope to leak. So `test_the_pool_hands_
out_the_same_physical_connection` pins connection identity first, and every leak test
runs against that same object.

Ties to tasks.md P205, spec AC-6, INV-1, plan §3.
"""
from __future__ import annotations

import pytest

from api.db.fake_connection import FakeConnection, FakePool
from api.db.rls import visible_rows
from api.db.scope import ScopeNotSetError, scoped_transaction

ROWS = [
    {"id": "BRIDGE_1", "municipality_id": "MUNI_A"},
    {"id": "BRIDGE_2", "municipality_id": "MUNI_A"},
    {"id": "BRIDGE_3", "municipality_id": "MUNI_B"},
]


@pytest.fixture
def pool() -> FakePool:
    return FakePool(rows=ROWS)


async def _request(pool: FakePool, tenant: str) -> list[dict[str, object]]:
    """One request's worth of work: check out, scope, read, release."""
    conn = pool.checkout()
    try:
        async with scoped_transaction(conn, tenant) as scoped:
            return await scoped.fetch("SELECT * FROM bridges")
    finally:
        pool.release(conn)


# --------------------------------------------- the test must not be vacuous ---
@pytest.mark.asyncio
async def test_the_pool_hands_out_the_same_physical_connection(pool: FakePool):
    """Pinned first: a fresh connection per request would make every test below pass."""
    a = pool.checkout()
    pool.release(a)
    b = pool.checkout()
    pool.release(b)
    assert a is b, "the pool is not reusing connections — the leak tests would be vacuous"
    assert pool.checkouts == 2


# ------------------------------------------------------------- the leak itself ---
@pytest.mark.asyncio
async def test_two_sequential_requests_each_see_only_their_own_tenant(pool: FakePool):
    """The headline check, on one reused connection."""
    first = await _request(pool, "MUNI_A")
    second = await _request(pool, "MUNI_B")
    assert [r["id"] for r in first] == ["BRIDGE_1", "BRIDGE_2"]
    assert [r["id"] for r in second] == ["BRIDGE_3"]


@pytest.mark.asyncio
async def test_the_second_request_does_not_inherit_the_first_scope(pool: FakePool):
    await _request(pool, "MUNI_A")
    conn = pool.checkout()
    assert conn.current_scope is None, (
        f"the connection still carries {conn.current_scope!r} after the request ended"
    )


@pytest.mark.asyncio
async def test_scope_is_unset_between_transactions(pool: FakePool):
    conn = pool.checkout()
    async with scoped_transaction(conn, "MUNI_A") as scoped:
        assert conn.current_scope == "MUNI_A"
        await scoped.fetch("SELECT 1")
    assert conn.current_scope is None
    async with scoped_transaction(conn, "MUNI_B") as scoped:
        assert conn.current_scope == "MUNI_B"
    assert conn.current_scope is None


@pytest.mark.asyncio
async def test_a_third_unscoped_query_reads_nothing(pool: FakePool):
    """tasks.md's exact wording: after two scoped requests, an unscoped read is empty.

    Here it raises — the repository layer is louder than the engine on purpose (P203).
    The engine's quiet zero-rows equivalent is asserted immediately below.
    """
    await _request(pool, "MUNI_A")
    await _request(pool, "MUNI_B")
    conn = pool.checkout()
    with pytest.raises(ScopeNotSetError):
        await conn.fetch("SELECT * FROM bridges")


@pytest.mark.asyncio
async def test_the_engine_equivalent_of_that_third_query_is_zero_rows(pool: FakePool):
    """What Postgres itself would do with the GUC unset — fail-closed, not fail-open."""
    await _request(pool, "MUNI_A")
    conn = pool.checkout()
    assert visible_rows(ROWS, conn.current_scope) == []


# ------------------------------------------------ the rollback path leaks too ---
@pytest.mark.asyncio
async def test_a_failed_request_leaves_no_scope_behind(pool: FakePool):
    """Rollback must clear it too — otherwise one 500 poisons the next caller."""
    conn = pool.checkout()
    with pytest.raises(RuntimeError):
        async with scoped_transaction(conn, "MUNI_A"):
            raise RuntimeError("handler blew up")
    assert conn.current_scope is None
    pool.release(conn)
    # And the next request on that same connection is correctly scoped.
    assert [r["id"] for r in await _request(pool, "MUNI_B")] == ["BRIDGE_3"]


@pytest.mark.asyncio
async def test_a_failed_request_closes_its_transaction(pool: FakePool):
    conn = pool.checkout()
    with pytest.raises(RuntimeError):
        async with scoped_transaction(conn, "MUNI_A"):
            raise RuntimeError("boom")
    assert conn.in_transaction is False
    assert conn.ops[-1].kind == "rollback"


@pytest.mark.asyncio
async def test_an_unresolvable_scope_does_not_disturb_the_pooled_connection(pool: FakePool):
    """A 401 request must leave the connection exactly as it found it."""
    from api.db.scope import UnresolvedScopeError

    await _request(pool, "MUNI_A")
    conn = pool.checkout()
    ops_before = list(conn.ops)
    with pytest.raises(UnresolvedScopeError):
        async with scoped_transaction(conn, None):
            pass
    assert conn.ops == ops_before, "the refused request touched the connection"
    assert conn.current_scope is None


# ------------------------------------------------------ re-scoping is refused ---
@pytest.mark.asyncio
async def test_overlapping_transactions_are_refused_not_silently_rescoped(pool: FakePool):
    """Two open scopes on one connection means one of them is wrong. Refuse, don't pick."""
    conn = pool.checkout()
    with pytest.raises(RuntimeError):
        async with scoped_transaction(conn, "MUNI_A"):
            async with scoped_transaction(conn, "MUNI_B"):
                pass


@pytest.mark.asyncio
async def test_many_alternating_requests_never_cross(pool: FakePool):
    """Repetition matters: a leak that only appears on the Nth reuse still counts."""
    for _ in range(10):
        assert [r["id"] for r in await _request(pool, "MUNI_A")] == ["BRIDGE_1", "BRIDGE_2"]
        assert [r["id"] for r in await _request(pool, "MUNI_B")] == ["BRIDGE_3"]
    assert pool.checkouts == 20
    assert pool.connection.current_scope is None


@pytest.mark.asyncio
async def test_every_transaction_reissues_the_scope(pool: FakePool):
    """No caching of 'already scoped'. Each transaction sets it again, from scratch."""
    await _request(pool, "MUNI_A")
    await _request(pool, "MUNI_A")
    scope_ops = [op for op in pool.connection.ops if op.kind == "set_scope"]
    assert len(scope_ops) == 2
    assert all(op.params == ("MUNI_A",) for op in scope_ops)
