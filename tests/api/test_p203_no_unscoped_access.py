"""P203 — an unscoped query must be impossible to express, not merely reviewed.

P202 built the scoped primitive. That is necessary and not sufficient: a primitive only
helps if there is no way around it. This file is the "no way around it" half, and it is
the reason Phase 2 is a hard gate — nothing else in the layer may be built until a query
*cannot* run unscoped.

Two kinds of check, deliberately different in nature:

**Structural (AST over `src/api/`).** Catches the future edit, not just today's code. A
handler that acquires its own connection, a helper that returns the raw handle, a second
module that redefines the scope SQL — each is a hole that review would have to catch
every time, forever. The scan catches them once.

**Behavioural (over the fake).** A deliberate attempt to query outside a scoped
transaction must FAIL LOUDLY. Note what is *not* acceptable here: returning zero rows.
Production's RLS predicate does return zero rows for an unset GUC, and that is correct as
defence-in-depth — but as the *primary* signal it is a trap, because "no data" looks like
a quiet day and can ship. The repository layer raises.

Ties to tasks.md P203, spec AC-6, INV-1, INV-2, plan §3.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from api.db.fake_connection import FakeConnection
from api.db.repository import Repository
from api.db.scope import (
    GUC_NAME,
    ScopedConnection,
    ScopeNotSetError,
    scoped_transaction,
)

API_ROOT = Path(__file__).resolve().parents[2] / "src" / "api"

# The ONE module allowed to know how to open a transaction and set a scope. Everything
# else must receive an already-scoped handle.
SCOPE_OWNER = "db/scope.py"

# The fake stands in for a driver, so it is allowed to model connection mechanics.
DRIVER_FAKES = {"db/fake_connection.py"}


def _api_modules() -> list[tuple[str, ast.Module, str]]:
    out = []
    for path in sorted(API_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(API_ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        out.append((rel, ast.parse(src), src))
    return out


@pytest.fixture(scope="module")
def modules() -> list[tuple[str, ast.Module, str]]:
    mods = _api_modules()
    assert mods, "the AST scan found no modules — the scan itself is broken"
    return mods


# ------------------------------------------------------- structural: no side doors ---
def test_no_module_acquires_its_own_connection(modules):
    """Nothing may open a connection or check out of a pool on its own.

    If a handler can call `asyncpg.connect(...)` or `pool.acquire()`, the scope primitive
    is advisory. These are the standard driver spellings across asyncpg / psycopg /
    SQLAlchemy; a new driver would need adding here alongside its adoption.
    """
    banned = (
        "connect", "acquire", "create_pool", "connection",
        "begin", "session", "cursor", "getconn",
    )
    offenders = []
    for rel, tree, _ in modules:
        if rel == SCOPE_OWNER or rel in DRIVER_FAKES:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in banned:
                    offenders.append(f"{rel}: .{node.func.attr}()")
    assert not offenders, (
        "these call sites can obtain a database handle outside the scope primitive: "
        f"{offenders}"
    )


def test_no_module_imports_a_driver_directly(modules):
    """Driver imports belong behind the seam. A router importing asyncpg is a bypass."""
    drivers = {"asyncpg", "psycopg", "psycopg2", "sqlalchemy", "aiopg", "databases"}
    offenders = []
    for rel, tree, _ in modules:
        if rel == SCOPE_OWNER or rel in DRIVER_FAKES:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in drivers:
                        offenders.append(f"{rel}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in drivers:
                    offenders.append(f"{rel}: from {node.module} import ...")
    assert not offenders, f"direct driver imports outside the seam: {offenders}"


def _emitted_strings(tree: ast.Module) -> list[str]:
    """String literals that could become SQL — docstrings and comments excluded.

    A plain text scan is useless here for the same reason it was in P201: these modules
    *document* the scope mechanism at length, so prose explaining `SET LOCAL` trips
    every check. Comments never enter the AST, and docstrings are identified and
    dropped, leaving only literals the code could actually emit.
    """
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstrings
    ]


def test_the_guc_name_is_defined_in_exactly_one_place(modules):
    """A second literal copy of the GUC is a rename waiting to half-apply."""
    definers = [
        rel for rel, tree, _ in modules
        if any(GUC_NAME in s for s in _emitted_strings(tree))
    ]
    assert definers == [SCOPE_OWNER], (
        f"the GUC literal must appear only in {SCOPE_OWNER}, found in: {definers}"
    )


def test_only_the_scope_module_emits_set_config(modules):
    """One place builds the scope statement, so one place can get it wrong."""
    offenders = [
        rel for rel, tree, _ in modules
        if rel != SCOPE_OWNER
        and any("set_config" in s or "SET LOCAL" in s for s in _emitted_strings(tree))
    ]
    assert not offenders, f"scope-setting SQL outside {SCOPE_OWNER}: {offenders}"


def test_scoped_connection_has_no_accessor_returning_the_raw_handle():
    """The private attribute must stay private — no property, no getter, no method."""
    public = [n for n in dir(ScopedConnection) if not n.startswith("_")]
    assert sorted(public) == ["execute", "fetch", "municipality_id"], (
        f"ScopedConnection's public surface widened to {public}; anything returning the "
        "underlying connection is an escape hatch"
    )


def test_scoped_connection_cannot_be_extended_with_new_attributes():
    """__slots__ means a caller cannot smuggle a raw handle onto the object at runtime."""
    handle = ScopedConnection(FakeConnection(), "MUNI_A")
    with pytest.raises(AttributeError):
        handle.raw_conn = object()  # type: ignore[attr-defined]


# ------------------------------------------- structural: repositories take a scope ---
def test_every_repository_requires_a_scoped_connection(modules):
    """A repository constructed from a raw connection would defeat the whole design.

    Enforced at the type level (the annotation) and at runtime (Repository.__init__).
    """
    for rel, tree, _ in modules:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith("Repository"):
                continue
            init = next(
                (n for n in node.body
                 if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
                None,
            )
            if init is None:
                continue  # inherits Repository.__init__, which is itself checked below
            args = [a for a in init.args.args if a.arg != "self"]
            assert args, f"{rel}:{node.name}.__init__ takes no connection at all"
            first = args[0]
            assert first.annotation is not None, (
                f"{rel}:{node.name}.__init__ first arg is unannotated — it must be "
                "declared ScopedConnection"
            )
            assert ast.unparse(first.annotation) == "ScopedConnection", (
                f"{rel}:{node.name}.__init__ takes "
                f"{ast.unparse(first.annotation)}, not ScopedConnection"
            )


def test_repository_rejects_a_raw_connection_at_runtime():
    """Annotations are not enforcement. This is."""
    with pytest.raises(TypeError):
        Repository(FakeConnection())  # type: ignore[arg-type]


def test_repository_rejects_none():
    with pytest.raises(TypeError):
        Repository(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_repository_accepts_a_scoped_handle_and_exposes_its_tenant():
    conn = FakeConnection()
    async with scoped_transaction(conn, "MUNI_A") as scoped:
        repo = Repository(scoped)
        assert repo.municipality_id == "MUNI_A"


def test_repository_exposes_no_raw_handle():
    public = [n for n in dir(Repository) if not n.startswith("_")]
    for banned in ("connection", "conn", "raw", "pool", "cursor", "acquire", "scoped"):
        assert banned not in public, f"Repository.{banned} is an escape hatch"


# ------------------------------------------------------- behavioural: fails loudly ---
@pytest.mark.asyncio
async def test_a_deliberate_unscoped_query_raises_rather_than_returning_rows():
    """The headline acceptance check. Rows exist; the unscoped read must still raise."""
    conn = FakeConnection()
    conn.rows = [{"id": "BRIDGE_1"}, {"id": "BRIDGE_2"}]
    with pytest.raises(ScopeNotSetError):
        await conn.fetch("SELECT * FROM bridges")


@pytest.mark.asyncio
async def test_unscoped_write_also_raises():
    conn = FakeConnection()
    with pytest.raises(ScopeNotSetError):
        await conn.execute("INSERT INTO bridges (id) VALUES ($1)", "BRIDGE_X")


@pytest.mark.asyncio
async def test_a_repository_held_past_its_transaction_raises():
    """The realistic bypass: stash the repo, use it after the request's scope is gone."""
    conn = FakeConnection()
    async with scoped_transaction(conn, "MUNI_A") as scoped:
        repo = Repository(scoped)
    with pytest.raises(ScopeNotSetError):
        await repo._fetch("SELECT 1")


@pytest.mark.asyncio
async def test_zero_rows_is_not_the_signal():
    """Explicitly documents the rejected alternative.

    A silent empty result reads as 'no data' and survives review. If someone ever
    'fixes' the fake to mirror Postgres by returning [], this fails.
    """
    conn = FakeConnection()
    conn.rows = [{"id": "BRIDGE_1"}]
    try:
        result = await conn.fetch("SELECT * FROM bridges")
    except ScopeNotSetError:
        return
    pytest.fail(
        f"unscoped query returned {result!r} instead of raising; a quiet empty result "
        "is the failure mode this gate exists to prevent"
    )
