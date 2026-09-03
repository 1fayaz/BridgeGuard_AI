"""Database access for the API layer.

Everything in here exists to make one thing true: a query cannot run without a tenant
scope. `scope.py` holds the only way to obtain a usable handle.
"""

from .repository import Repository
from .rls import visible_rows
from .scope import ScopedConnection, close_pool, init_pool, run_scoped

__all__ = [
    "init_pool",
    "close_pool",
    "run_scoped",
    "Repository",
    "set_municipality_context",
    "ScopedConnection",
]