"""P202 — the scope-setting transaction primitive.

This is the seam INV-1 rests on: *every authenticated request resolves municipality_id
from the credential and sets `app.current_municipality_id` before any database query.*
Rather than trust every handler to remember, this module makes the scoped transaction
the only way to obtain something you can query with.

Four decisions, each with a specific failure behind it:

**The GUC name is a constant, defined once.** Spec 003's plan used
`app.municipality_id`; migration 0016 uses `app.current_municipality_id`. The mismatch
does not raise — the RLS predicate simply never matches, and every table reads as empty.
"No data" is a far worse failure than a crash, because it looks like a quiet Tuesday.
So the name lives in exactly one place, and P206 guards it.

**`set_config(name, value, is_local => true)`, not `SET LOCAL <name> = '<value>'`.**
Both are transaction-local; only the first takes the tenant id as a bound parameter.
`SET` has no parameterized form, so using it would mean concatenating a caller-derived
value into SQL at the tenancy boundary — the one place that must not be string-built.

**Transaction-local, never session-level.** On a pooled connection a session GUC
outlives the request and silently scopes the *next* caller's queries to the previous
tenant. `is_local => true` resets at commit or rollback.

**Fail-closed, before anything runs.** An unresolvable scope raises before BEGIN, so a
request with no tenant executes zero statements rather than executing them unscoped and
relying on RLS to save it. RLS is defence-in-depth here, not the primary control.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Final, Protocol

import asyncpg

from ..settings import get_settings

# The exact GUC read by every RLS policy in migration 0016 and 0017. One definition.
# Changing this string silently empties the entire API. See P206.
GUC_NAME = "app.current_municipality_id"

# Parameterized and transaction-local. The tenant id is $1 — never interpolated.
# `is_local => true` is the set_config equivalent of SET LOCAL.
SET_SCOPE_SQL = f"SELECT set_config('{GUC_NAME}', $1, true)"

DEMO_MUNICIPALITY_ID: Final = "municipality-lahore"

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=get_settings().database_url,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _require_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool not initialized")
    return _pool


async def run_scoped(query: str, *params: object) -> list[dict[str, object]]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(SET_SCOPE_SQL, DEMO_MUNICIPALITY_ID)
            rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


class UnresolvedScopeError(Exception):
    """No usable municipality id — the request cannot be scoped, so nothing may run.

    Raised before BEGIN. The API boundary maps this to 401 (P204): a caller whose scope
    cannot be resolved is not authenticated, regardless of what they asked for.
    """


class ScopeNotSetError(RuntimeError):
    """A query was attempted outside a scoped transaction.

    Deliberately loud. The fail-closed RLS path would return zero rows, which reads as
    "no data" and can survive review; this raises so the mistake is visible in dev.
    """


class Connection(Protocol):
    """The narrow surface `scoped_transaction` needs from a driver connection.

    Structural, so asyncpg, a pooled proxy, and the in-memory fake all satisfy it
    without a shared base class.
    """

    async def begin(self) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def set_scope(self, sql: str, municipality_id: str) -> None: ...
    async def clear_scope(self) -> None: ...
    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]: ...
    async def execute(self, sql: str, *params: object) -> None: ...


class ScopedConnection:
    """A query handle that is scoped to exactly one tenant for exactly one transaction.

    Exposes no accessor for the connection underneath. That is the point: a handler
    given one of these cannot reach around it to an unscoped query, so INV-1 holds by
    construction rather than by review (P203 enforces the same repo-wide).
    """

    __slots__ = ("_conn", "_municipality_id", "_open")

    def __init__(self, conn: Connection, municipality_id: str) -> None:
        self._conn = conn
        self._municipality_id = municipality_id
        self._open = True

    @property
    def municipality_id(self) -> str:
        """The tenant every query through this handle is confined to."""
        return self._municipality_id

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self._require_open()
        return await self._conn.fetch(sql, *params)

    async def execute(self, sql: str, *params: object) -> None:
        self._require_open()
        await self._conn.execute(sql, *params)

    def _close(self) -> None:
        self._open = False

    def _require_open(self) -> None:
        # A handle captured out of its `async with` block is past its transaction, so
        # its SET LOCAL is gone. Using it would be an unscoped query.
        if not self._open:
            raise ScopeNotSetError(
                "this handle's transaction has ended; its scope no longer exists. "
                "Open a new scoped_transaction()."
            )


def _require_scope(municipality_id: str | None) -> str:
    if municipality_id is None or not municipality_id.strip():
        raise UnresolvedScopeError(
            "cannot open a transaction without a municipality scope; "
            "no query may run unscoped (INV-1)"
        )
    return municipality_id.strip()


@asynccontextmanager
async def scoped_transaction(
    conn: Connection, municipality_id: str | None
) -> AsyncIterator[ScopedConnection]:
    """Open a transaction, set the tenant scope, and yield the only usable handle.

    Order matters and is asserted by the tests: validate → BEGIN → set scope → yield.
    The scope statement is the first thing after BEGIN, so there is no window in which
    a query could run inside the transaction but before the scope exists.
    """
    scope = _require_scope(municipality_id)

    await conn.begin()
    try:
        await conn.set_scope(SET_SCOPE_SQL, scope)
        handle = ScopedConnection(conn, scope)
        try:
            yield handle
        finally:
            handle._close()
    except BaseException:
        await conn.rollback()
        raise
    else:
        await conn.commit()
