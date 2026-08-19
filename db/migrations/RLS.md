# BridgeGuard — Row-Level Security: Operator Note

This note is for whoever **runs** BridgeGuard against a live Neon/Postgres instance. Multi-tenant
isolation — municipality A must never see municipality B's data (spec AC-4) — is enforced by Postgres
Row-Level Security, configured in migration `0016_rls_policies.sql`. RLS is only as safe as its
operation, so read this before deploying or debugging a tenant-visibility issue.

## The model in one paragraph

There is a single database role, **`bridgeguard_service`**, which **owns** all eleven tenant-scoped
tables and is also the role the application connects as. Every tenant-scoped table has RLS
**`ENABLE`d and `FORCE`d**, with per-table `SELECT`/`INSERT` policies that admit only rows whose
`municipality_id` equals the session GUC **`app.current_municipality_id`** (the `municipalities` table
self-scopes on its `id`). The API sets that GUC once per transaction; if it is unset, the policies
match nothing and every read returns zero rows (**fail-closed**).

## Why `FORCE`, not just `ENABLE`

By default a table's **owner** — and any role with `BYPASSRLS` — skips row-level policies entirely.
Because `bridgeguard_service` *owns* these tables and is the app's connection role, `ENABLE` alone
would leave the application's own connection seeing **every** tenant's rows. `ALTER TABLE … FORCE ROW
LEVEL SECURITY` removes the owner exemption, so the policies bind the owner too. Do **not** grant
`BYPASSRLS` to any role the app uses, and do not connect the app as a Postgres superuser — either
would silently defeat isolation.

## The session GUC — exact name and how the API sets it

The policies key on the custom GUC, spelled **exactly**:

```
app.current_municipality_id
```

The API must set it **per transaction**, using `SET LOCAL` (transaction-scoped — it resets at commit/
rollback, so a scope never leaks into the next request on a pooled connection):

```sql
BEGIN;
SET LOCAL app.current_municipality_id = 'MUNI_A';   -- or: SELECT set_config('app.current_municipality_id', $1, true);
-- … all reads/writes here are automatically scoped to MUNI_A …
COMMIT;
```

`set_config(name, value, is_local => true)` is the parameterized equivalent (use it to avoid string-
building the tenant id into SQL). Setting the GUC at session level (`SET`, not `SET LOCAL`) is a
foot-gun on a connection pool — always use the transaction-local form.

## Fail-closed semantics

The policy predicate is `municipality_id = current_setting('app.current_municipality_id', true)`. The
`true` (`missing_ok`) argument means an **unset** GUC yields `NULL` rather than raising — and
`municipality_id = NULL` is never true, so an unscoped transaction reads **zero rows**, never all.
This is deliberate: a forgotten scope must leak **nothing**. (A bare `current_setting(...)` without the
flag would raise on an unset GUC; the migration never uses that form.) The write side mirrors this —
an `INSERT` whose `municipality_id` is not the current scope is rejected by the policy `WITH CHECK`.

## Out of scope — the auth seam

**How a request is mapped to a municipality is OUT OF SCOPE for the database layer** and is covered by
a **separate spec** (the auth / API layer). This note stops at the contract: *the API must resolve the
authenticated principal to exactly one `municipality_id` and `SET LOCAL app.current_municipality_id`
to it at the start of every transaction.* The database enforces isolation given a correct scope; it
cannot verify that the scope the API set matches the authenticated user — that trust boundary lives in
the auth layer, not here.

## Quick operator checklist

- [ ] App connects as `bridgeguard_service` (not a superuser, no `BYPASSRLS`).
- [ ] Every transaction issues `SET LOCAL app.current_municipality_id = '<tenant>'` before any query.
- [ ] Isolation smoke test: with the GUC set to one tenant, no other tenant's rows are visible; with
      it unset, every tenant table returns zero rows.
- [ ] RLS is `ENABLED` **and** `FORCED` on all eleven tenant tables (a table missing `FORCE` is a
      silent owner-visible hole).
