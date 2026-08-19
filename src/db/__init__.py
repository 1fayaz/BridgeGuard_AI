"""BridgeGuard database layer (Spec 002) — the cross-cutting persistence foundation.

Unlike the agent packages, the database layer belongs to no single agent: it owns the tenancy
ownership chain (municipalities -> bridges -> sensors -> readings), the append-only / correct-by-
supersede discipline, and the row-level-security isolation every agent and the API depend on.

The in-memory fakes here ([DB-DEP]) mirror the guarantees the SQL migrations enforce live, so the
logic tests exercise the same invariants the live Neon/Postgres instance will later enforce.
"""
