# BridgeGuard — Foreign-Key Strategy: Soft Provenance, Hard Tenancy

The schema uses **two deliberately different** foreign-key strategies. This is not an inconsistency to
clean up — a reader who "fixes" the soft links into hard FKs would break agent independence, risk
cascading deletes onto safety-critical audit data, and hit a Postgres limitation. Read this before
changing any `REFERENCES` clause.

## The rule

| Relationship | Strategy | How it's declared |
|---|---|---|
| **Provenance** — `source_raw_ids`, `source_validated_ids`, `source_analysis_ids` | **SOFT** | plain `BIGINT[]` arrays, **no FK** |
| **Tenancy chain** — `sensor_id → sensors`, `bridge_id → bridges`, `municipality_id → municipalities` | **HARD** | real `REFERENCES` + `NOT NULL` |
| **Correction link** — `superseded_by` | **HARD** | self-referential `REFERENCES <table>(id)` |

Provenance is a *soft* reference (an id an agent recorded, validated by convention and test, not by a
DB constraint). Tenancy and the supersede link are *hard* (the database structurally guarantees they
point at a real, existing row).

## Why provenance is SOFT — four reasons

1. **Agent independence.** Each agent (DCA, SA, Risk, Report, Alert) owns and writes its own table. A
   hard FK from `analysis_results.source_validated_ids` to `validated_readings` would couple the SA
   agent's writes to the DCA's table structure and write ordering — a cross-agent write dependency the
   modularity principle (Constitution III) forbids. Soft links let each agent write independently and
   record *what it consulted* without a structural handshake.
2. **No cascade on safety data.** A hard FK invites `ON DELETE` semantics. On safety-critical audit
   data that is exactly wrong: deleting (or having a delete cascade to) an upstream reading must never
   make the downstream assessment/report/dispatch that cited it vanish. Provenance must survive even
   if an upstream row is somehow removed — the audit trail is permanent (Constitution VI). Soft links
   carry no cascade.
3. **Survive supersession.** Provenance is pinned by **row id**, so when an upstream row is corrected
   (a new version appended, the old one stamped `superseded_by`), a downstream record still references
   the **exact old version it acted on**. A hard FK to "the current row" would falsify the historical
   record; a soft pinned id keeps an audit reproducible (proven in the D802 test).
4. **Arrays can't be FKs.** Provenance is naturally *one-to-many* (an assessment consults several
   analyses; a validated reading derives from several raw samples), stored as a `BIGINT[]`. Postgres
   **has no array-element foreign key** — there is no way to declare "every element of this array
   references that table." So even setting reasons 1–3 aside, a hard FK on the array is not expressible.

## Why tenancy and `superseded_by` are HARD

The tenancy chain is the isolation backbone: an **orphan** row (a reading whose `sensor_id` isn't a
real sensor, or any row whose `municipality_id` isn't a real tenant) must be *impossible*, because RLS
keys on the denormalized `municipality_id` and a mis-attributed row would leak across tenants. Here a
cascade-free **hard** FK + `NOT NULL` is exactly right: it structurally rejects orphans at write time.
`superseded_by` is likewise hard — it's an *internal* self-reference within one table, so it carries
none of the cross-agent-coupling concerns, and pointing it at a non-existent row would corrupt the
correction history. (A consistency guard additionally checks the *denormalized* tenant copies agree
with the chain — see `RLS.md` / migration 0015.)

## `[DB-DEP]` — what is deferred, and how the fakes stand in

There is **no live Neon instance in local development**, so migrations cannot be executed and their
constraints/triggers/policies cannot fire against real rows in the test suite. Tests that depend on a
live database are marked **`[DB-DEP]`**. To keep the logic tested now, in-memory **fakes**
(`FakeTenantStore`, `FakeAnalysisStore`, `FakeRiskStore`, `FakeAlertStore`, …) mirror — in Python —
exactly the guarantees the SQL will enforce, so nothing is faked *away*.

### Live-verified vs. fake-verified

| Guarantee | Verified **now** (fake / static) | Verified **live** (Neon, `[DB-DEP]`) |
|---|---|---|
| Hard-FK orphan rejection (tenancy chain) | `FakeTenantStore` raises on orphan bridge/sensor/reading | FK constraint rejects the INSERT |
| Append-only / supersede triggers | fakes block overwrite/delete; migration text asserts the trigger exists | `BEFORE UPDATE/DELETE` trigger actually raises |
| Tenant-consistency guard | `FakeTenantStore.check_tenant_consistency` | `BEFORE INSERT/UPDATE` guard trigger raises on drift |
| RLS isolation (read + write) | `FakeTenantStore` scoped readers + `check_insert_scope`; 0016 predicate applied to seed rows | policies filter/reject on a real connection |
| Soft-provenance resolution | walk over the fakes / seed resolves every id | (n/a — soft links are convention, no DB constraint) |
| Index presence / shape | migration text asserts `CREATE [UNIQUE] INDEX …` | `EXPLAIN` shows the index is used, no seq scan |

The soft links are the one place there is *nothing* for the live DB to enforce — by design. Their
integrity is a **test** guarantee (the provenance-walk tests D204/D801), not a **schema** guarantee,
which is the whole point of choosing soft over hard for reasons 1–4 above.
