"""P203 — the base every repository inherits, and the reason none can go around the seam.

`scoped_transaction` (P202) is only load-bearing if there is no other way to reach the
database. This class is the enforcement half: a repository is *constructible* only from
an already-scoped handle, so "I forgot to set the scope" is not a mistake a caller can
make — there is nothing to forget, because an unscoped handle will not go in.

The runtime `isinstance` check is deliberate, not defensive noise. This is a system
boundary in the sense that matters: on the far side of a wrong answer is one
municipality reading another's structural data. An annotation is a note to a reader and
to mypy; neither runs in production. So the constructor rejects the raw connection at
runtime, and P203's AST scan additionally rejects it at edit time.

Subclasses get `_fetch` / `_execute` and nothing else. There is no accessor that returns
the connection, no `.raw`, no escape hatch — a subclass author who wants one has to
change *this* file, which is exactly the review the design wants to force.
"""
from __future__ import annotations

from .scope import ScopedConnection


class Repository:
    """Base for every table-facing repository in the API layer.

    Holds a handle whose tenant scope was set before it existed, and exposes only the
    two verbs a repository needs.
    """

    __slots__ = ("_scoped",)

    def __init__(self, scoped: ScopedConnection) -> None:
        # Not an assert: asserts vanish under -O, and this one is an isolation control.
        if not isinstance(scoped, ScopedConnection):
            raise TypeError(
                "a repository must be constructed from a ScopedConnection obtained via "
                f"scoped_transaction(); got {type(scoped).__name__}. A raw connection "
                "would run unscoped queries (INV-1)."
            )
        self._scoped = scoped

    @property
    def municipality_id(self) -> str:
        """The tenant every query from this repository is confined to.

        Exposed because handlers legitimately need to know whose data they are holding
        — for audit rows and log lines. It is a string, not a handle: reading it grants
        nothing.
        """
        return self._scoped.municipality_id

    async def _fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return await self._scoped.fetch(sql, *params)

    async def _execute(self, sql: str, *params: object) -> None:
        await self._scoped.execute(sql, *params)
