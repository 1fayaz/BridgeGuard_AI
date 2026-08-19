"""Database connection pool for the API layer (hackathon demo).

Wraps an asyncpg pool so endpoints get a scoped connection. For the demo we use a
single hardcoded demo municipality; production would resolve this from the Principal.
"""
from __future__ import annotations

import asyncpg
from typing import Final

from api.settings import get_settings

# Demo tenant — the seeded Lahore municipality.
DEMO_MUNICIPALITY_ID: Final = "municipality-lahore"

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Create the connection pool at app startup."""
    global _pool
    settings = get_settings()
    url = settings.database_url
    # Railway injects DATABASE_URL; strip the leading "postgresql://" quote artefacts if present.
    _pool = await asyncpg.create_pool(
        dsn=url,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )


async def close_pool() -> None:
    """Close the pool at shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_connection() -> asyncpg.Connection:
    """Acquire a connection from the pool."""
    if _pool is None:
        raise RuntimeError("database pool not initialized")
    return await _pool.acquire()


async def release_connection(conn: asyncpg.Connection) -> None:
    """Release a connection back to the pool."""
    if _pool is not None:
        await _pool.release(conn)


async def run_scoped(query: str, *params: object) -> list[dict]:
    """Run a query scoped to the demo municipality.

    Sets app.current_municipality_id via parameterized set_config before the query,
    matching migration 0016's RLS predicate. [DB-DEP] on a live instance this enforces
    tenant isolation; for the demo the single tenant is the seeded Lahore municipality.
    """
    conn = await get_connection()
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_municipality_id', $1, true)",
                DEMO_MUNICIPALITY_ID,
            )
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
    finally:
        await release_connection(conn)
