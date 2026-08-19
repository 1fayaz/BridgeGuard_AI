# BridgeGuard — Database Migrations

The system of record is **Neon / PostgreSQL with standard B-tree indexes only — NO TimescaleDB**
(CLAUDE.md / constitution v2.1.0). Migrations are plain numbered `.sql` files applied **in ascending
order, exactly once each**. Nothing here is executed by the test suite (`[DB-DEP]`: no Neon instance
locally) — each migration is written to be reviewable now, with in-memory fakes mirroring its
guarantees until a live instance exists.

> Seed data (`db/seed/seed_dev.sql`) is **not** a migration — it is dev/test data loaded *after* the
> schema exists. Never renumber a migration: tests reference migrations by filename, and applied
> migrations are immutable history.

## Apply order (0001–0017)

| # | File | Creates / changes | Depends on |
|---|------|-------------------|-----------|
| 0001 | `raw_readings` | Immutable raw sensor readings. **Total-block** append-only. `(sensor_id, sensor_time DESC)` index. | — |
| 0002 | `validated_readings` | DCA verdicts. **Correct-by-supersede.** `(sensor_id, sensor_time DESC)` index. | 0001 |
| 0003 | `sensor_status` | Current per-sensor state. **Mutable by design** (NOT an SOR table). | — |
| 0004 | `decision_log` | Shared append-only audit trail + the `decision_kind` enum. **Total-block.** | — |
| 0005 | `analysis_results` | **(gap-fill)** SA outputs. **Correct-by-supersede.** The hop that was dangling before it existed. | 0002 |
| 0006 | `risk_assessments` | Risk verdicts. **Correct-by-supersede.** `(bridge_id, assessed_at DESC)` + partial-unique-current. | 0005 |
| 0007 | `decision_log_risk_kinds` | Extends the shared `decision_kind` enum with Risk kinds (`ADD VALUE IF NOT EXISTS`). | 0004 |
| 0008 | `report_artifacts` | Report outputs. **Correct-by-supersede.** `(bridge_id, rendered_at DESC)` + partial-unique-current. | 0006 |
| 0009 | `decision_log_report_kinds` | Extends `decision_kind` with Report kinds. | 0004 |
| 0010 | `alert_dispatches` | Alert dispatch log. **Correct-by-supersede** + live delivery state machine. `(bridge_id, attempted_at DESC)`. | 0006 |
| 0011 | `decision_log_alert_kinds` | Extends `decision_kind` with Alert kinds. | 0004 |
| 0012 | `municipalities` | **(tenancy root)** TEXT-key tenant table. | — |
| 0013 | `bridges` | Bridges, hard FK → municipalities. | 0012 |
| 0014 | `sensors` | Sensors, hard FK → bridges. | 0013 |
| 0015 | `tenant_columns_and_fks` | **The wiring migration.** Adds denormalized `bridge_id`/`municipality_id` to every tenant table (part A), the hard tenancy FKs + NOT NULL (part B), the consistency guard (part B), and the `(municipality_id)` indexes (part C). | 0001–0014 |
| 0016 | `rls_policies` | Row-level security: `ENABLE` + `FORCE` (part A) and the per-table SELECT/INSERT policies keyed on `app.current_municipality_id` (part B). | 0015 |
| 0017 | `device_credentials` | **(API layer)** Pi gateway credentials: hashed key → exactly one `bridge_id` + `municipality_id`. **Revoke-not-delete** (DELETE blocked); tenant guard trigger; RLS `ENABLE`+`FORCE` + SELECT/INSERT/UPDATE policies. | 0013, 0016 |
| 0018 | `device_credential_key_immutable` | **(API layer)** Narrows 0017's permitted `UPDATE` to the lifecycle columns: `key_hash` / `credential_id` / `bridge_id` / `municipality_id` / `created_at` are immutable and revocation is one-way, so rotation must INSERT-then-revoke rather than overwrite a key in place. | 0017 |

## Additive strategy — why nothing was renumbered

The tables `0001–0011` were built first (one per agent). Two later needs were satisfied **additively**,
appending new numbers rather than renumbering existing files:

- **`0005` fills a gap, not a rename.** The `analysis_results` table (the Structural-Analysis agent's
  output) was initially missing — its slot was empty while `risk_assessments.source_analysis_ids`
  pointed at a table that did not exist. `0005` fills exactly that gap, closing the provenance chain
  `raw → validated → analysis → assessment` (proven end-to-end in the D204 test). Because migrations
  are immutable applied history, it takes the free `0005` slot rather than shifting `0006+`.
- **Tenancy appends late (`0012–0016`).** Multi-tenant isolation was added after the per-agent tables
  existed. Rather than editing eleven built files, the tenancy *foundation* is appended
  (`0012` municipalities → `0013` bridges → `0014` sensors), then a single **wiring** migration
  (`0015`) retro-fits the denormalized tenant columns + hard FKs + consistency guard + indexes onto
  the existing tables, and `0016` switches on RLS. No pre-existing file was renumbered or rewritten.

## The seven SOR tables — append-only discipline map

The **system of record is exactly seven (7) tables** (the plan §0 correction from an earlier count of
six — `analysis_results` is included). Two disciplines, defense-in-depth (a `REVOKE` **and** a
trigger on each):

**Total-block** — no `UPDATE`, no `DELETE`, ever. A row is immutable the instant it lands.
- `raw_readings` (0001) — raw data is immutable (Constitution II).
- `decision_log` (0004) — the audit trail is permanent (Constitution VI).
- Mechanism: `<table>_block_mutation` trigger `BEFORE UPDATE OR DELETE` + `REVOKE UPDATE, DELETE, TRUNCATE`.

**Correct-by-supersede** — a mistake is fixed by INSERTing a corrected row and stamping the old row's
`superseded_by`; the old row is retained unchanged (history permanent). `UPDATE` is allowed **only**
to stamp `superseded_by`; `DELETE` is blocked.
- `validated_readings` (0002), `analysis_results` (0005), `risk_assessments` (0006),
  `report_artifacts` (0008), `alert_dispatches` (0010).
- Mechanism: `<table>_guard_update` (`BEFORE UPDATE`, blocks substantive/identity edits) +
  `<table>_block_delete` (`BEFORE DELETE`) + `REVOKE DELETE, TRUNCATE`.
- Nuance: `alert_dispatches` is also a **live state machine** — its guard blocks only the pinned
  verdict identity, letting `delivery_state`/`escalation_state`/`approval_state` advance on the
  current row.

**Deliberately excluded** — `sensor_status` (0003) is **mutable current-state**, not history (the
permanent transition record lives in `decision_log`). It has no mutation guard and is freely
`UPDATE`-able — but `DELETE`/`TRUNCATE` are still revoked (a sensor's state cannot silently vanish).

**Related but not an SOR table** — `device_credentials` (0017) is API-layer config, so it is not one
of the seven. It nonetheless borrows the **DELETE-blocked** discipline: a credential row is the
evidence that a given device was authorised during a given window, so retiring a Pi is
`status = 'revoked'` + `revoked_at`, never a delete. `UPDATE` is permitted (revocation,
`last_used_at`) but confined to the caller's own tenant by the RLS `UPDATE` policy — and, since
**0018**, narrowed by a `<table>_guard_update` trigger to the lifecycle columns only. `key_hash`,
`credential_id`, `bridge_id`, `municipality_id`, and `created_at` are immutable, and revocation is
one-way. Rotation is therefore INSERT-then-revoke (two keys briefly coexist so a Pi can be
re-flashed without a data gap), never an in-place key overwrite: an overwrite would leave one row
claiming it always held the new key, making every reading the old key authorised trace to a
credential that did not exist at the time.

## Multi-tenant isolation (0015 + 0016, extended by 0017)

Every tenant-scoped row carries a **denormalized `municipality_id`** so the RLS predicate is a single
indexed equality rather than a per-row join up the ownership chain
`municipalities → bridges → sensors → readings`. A `BEFORE INSERT OR UPDATE` **consistency guard**
(0015) keeps that copy from drifting from the FK chain. `0016` then `ENABLE`s **and `FORCE`s** RLS on
all eleven tenant-scoped tables (FORCE so the table-owning `bridgeguard_service` role cannot bypass
it) and adds per-table SELECT/INSERT policies keyed on the session GUC **`app.current_municipality_id`**.
Fail-closed: an unset GUC yields NULL, so a forgotten scope reads **zero** rows, never all. See
`RLS.md` for the operator model.

`0017` extends the same model to a twelfth table, `device_credentials`, with its own denormalized
`municipality_id`, guard trigger, and `ENABLE`+`FORCE` policies. One nuance worth knowing: a Pi's
credential lookup happens **before** any tenant scope exists — that lookup is what *determines* the
scope — so the authentication read cannot itself be tenant-scoped. It runs through a separate,
narrowly-privileged path that may read only `(key_hash, bridge_id, municipality_id, status)`; every
query after resolution runs inside the normal scoped transaction.

## Verification & `[DB-DEP]`

Guarantees that need a live Neon instance to fully exercise (trigger firing, RLS filtering, FK
enforcement) are marked `[DB-DEP]` in the tests; in-memory fakes (`FakeTenantStore`,
`FakeAnalysisStore`, `FakeRiskStore`, …) mirror the same rules so the logic is tested now. The seed
`db/seed/seed_dev.sql` provides a two-municipality world for the isolation and provenance tests. See
`db/migrations/FK-STRATEGY.md` for the soft-provenance / hard-tenancy foreign-key decision.
