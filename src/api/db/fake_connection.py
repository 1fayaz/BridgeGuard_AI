"""In-memory stand-in for a Postgres connection (P202).

[DB-DEP] There is no Neon instance locally, so the scope primitive cannot be exercised
against a real engine. This fake mirrors the two engine behaviours the primitive depends
on, so the logic is testable now:

1. **A `SET LOCAL` GUC dies with its transaction.** The fake clears its scope on both
   commit and rollback, which is what makes the pooled-connection leak test meaningful.
2. **A query with no scope is refused.** Postgres would return zero rows here (the RLS
   predicate compares against NULL). The fake raises instead — deliberately louder than
   production, because a silent empty result is exactly the failure mode that survives
   review. Production's quiet version is defence-in-depth, not the control.

It also records every operation in order, which is how the tests assert that the scope
statement lands immediately after BEGIN rather than merely somewhere in the transaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from api.db.rls import visible_rows
from api.db.scope import ScopeNotSetError

GUC_HINT = (
    "no tenant scope is set on this connection; every query must run inside "
    "scoped_transaction() (INV-1)"
)


@dataclass(frozen=True, slots=True)
class Op:
    """One statement issued against the connection, in order."""

    kind: str
    sql: str = ""
    params: tuple[object, ...] = ()


@dataclass
class FakeConnection:
    """Records operations and enforces the scope precondition. Not thread-safe."""

    ops: list[Op] = field(default_factory=list)
    current_scope: str | None = None
    in_transaction: bool = False
    rows: list[dict[str, object]] = field(default_factory=list)

    async def begin(self) -> None:
        if self.in_transaction:
            # One transaction, one tenant. A nested BEGIN would mean a second scope is
            # about to overwrite the first, which is a design error, not a nesting need.
            raise RuntimeError(
                "a scoped transaction is already open on this connection; "
                "re-scoping mid-transaction is not supported"
            )
        self.in_transaction = True
        self.ops.append(Op("begin"))

    async def set_scope(self, sql: str, municipality_id: str) -> None:
        self.ops.append(Op("set_scope", sql, (municipality_id,)))
        self.current_scope = municipality_id

    async def clear_scope(self) -> None:
        self.current_scope = None

    async def commit(self) -> None:
        self.ops.append(Op("commit"))
        self._end_transaction()

    async def rollback(self) -> None:
        self.ops.append(Op("rollback"))
        self._end_transaction()

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self._require_scope(sql)
        self.ops.append(Op("fetch", sql, params))
        # Filtered by the same predicate the engine applies (0016), so a fake read
        # cannot show a caller rows the real database would have hidden.
        return list(visible_rows(self.rows, self.current_scope))

    async def execute(self, sql: str, *params: object) -> None:
        self._require_scope(sql)
        self.ops.append(Op("execute", sql, params))

    def _end_transaction(self) -> None:
        # SET LOCAL does not survive the transaction. Neither does this.
        self.current_scope = None
        self.in_transaction = False

    def _require_scope(self, sql: str) -> None:
        if self.current_scope is None:
            raise ScopeNotSetError(
                f"{GUC_HINT} — refusing to run: {sql[:60]!r}"
            )


@dataclass
class FakePool:
    """A pool that hands out ONE physical connection, over and over (P205).

    Modelling reuse is the entire point. A pool that returned a fresh connection per
    checkout would make every leak test pass while proving nothing — a fresh connection
    has no previous tenant's scope to inherit. So this deliberately has a pool size of
    one: every request gets the same object, carrying whatever state the last request
    left on it. If `SET LOCAL` did not reset, these tests would see it.
    """

    rows: list[dict[str, object]] = field(default_factory=list)
    checkouts: int = 0
    connection: FakeConnection = field(init=False)

    def __post_init__(self) -> None:
        self.connection = FakeConnection(rows=list(self.rows))

    def checkout(self) -> FakeConnection:
        self.checkouts += 1
        return self.connection

    def release(self, conn: FakeConnection) -> None:
        # Deliberately does NOT reset anything. A pool that scrubbed connection state on
        # release would hide the very leak this models — real pools return the
        # connection as-is, which is why the reset has to come from SET LOCAL.
        assert conn is self.connection
