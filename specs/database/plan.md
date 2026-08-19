# Database Layer — Technical Plan (Spec 002)

**Status:** Plan for review — no SQL written. Turns the approved `specs/database/spec.md` into an
ordered, decided design. **No migrations will be written until this plan is approved.**
**Date:** 2026-07-14
**Anchors:** approved `specs/database/spec.md`; `specs/database/research-db.md`; the built migrations
`0001`–`0011`; `CLAUDE.md` (Neon/Postgres, standard B-tree only); constitution v2.1.0.

> Every decision below follows from three facts established in research + the built migrations:
> (1) **no migration has ever been applied to a live instance** (`[DB-DEP]` on every file), so we have
> freedom to fill the `0005` gap and add wiring migrations; (2) the existing tables use **TEXT natural
> keys** (`sensor_id`, `bridge_id`), so hard FKs can be added **without changing any column type**;
> (3) tests reference migrations **by filename** (`0006_risk_assessments.sql`, `0010_…`), so renumbering
> existing files is high-cost and is rejected.

---

## 0. Correction to the brief: it is **seven** SOR tables, not six

The brief says "the six SOR tables." That count came from `research-db.md` point [2], written **before**
`analysis_results` was added. With the SA table now in scope there are **seven** append-discipline
tables. `sensor_status` (0003) is deliberately **excluded** — it is mutable current-state (one row per
sensor; `missed_count`/`status`/`updated_at` are updated in place by the liveness path), and its
history lives in `decision_log`. The plan treats all seven uniformly and calls this out so the count is
not silently wrong.

| # | Table | Discipline |
|---|-------|-----------|
| 1 | `raw_readings` (0001) | append-only, total-block |
| 2 | `decision_log` (0004) | append-only, total-block |
| 3 | `validated_readings` (0002) | correct-by-supersede |
| 4 | `analysis_results` (**new 0005**) | correct-by-supersede |
| 5 | `risk_assessments` (0006) | correct-by-supersede |
| 6 | `report_artifacts` (0008) | correct-by-supersede |
| 7 | `alert_dispatches` (0010) | correct-by-supersede + live delivery state machine |

---

## 1. Migration order

**Strategy: additive — fill the `0005` gap, append the tenancy tables, then one wiring + one RLS
migration. No existing file is renumbered.** Rationale: filling `0005` with `analysis_results` matches
the dangling "migration 0005" references already in the `0006`/`0008` headers and closes the only gap;
everything else appends contiguously; no test's hard-coded filename breaks.

### Why not renumber to logical dependency order
The natural *dependency* order is `municipalities → bridges → sensors → readings…`, which would put
tenancy at `0001`–`0003`. Rejected: it rewrites immutable migration history and breaks every test that
opens a migration by name. Postgres does not require creation order to match dependency order when FKs
are added by a later `ALTER` — so we create tenancy late and **wire the FKs in afterward**, which is
standard and lossless.

### The final contiguous sequence (no gaps, no conflicts)

| # | File | Creates / does | Depends on |
|---|------|----------------|-----------|
| 0001 | `raw_readings` | *(built; header fixed)* | — |
| 0002 | `validated_readings` | *(built)* | 0001 |
| 0003 | `sensor_status` | *(built)* | — |
| 0004 | `decision_log` | *(built; header fixed)* | 0001 |
| **0005** | **`analysis_results`** *(NEW)* | the SA output table — core columns + append-by-supersede triggers + idempotency index. **No tenant FK inline** (sensors not yet created); wired in 0015. | 0002 |
| 0006 | `risk_assessments` | *(built)* | — |
| 0007 | `decision_log_risk_kinds` | *(built; ALTER TYPE)* | 0004 |
| 0008 | `report_artifacts` | *(built)* | — |
| 0009 | `decision_log_report_kinds` | *(built; ALTER TYPE)* | 0004 |
| 0010 | `alert_dispatches` | *(built)* | — |
| 0011 | `decision_log_alert_kinds` | *(built; ALTER TYPE)* | 0004 |
| **0012** | **`municipalities`** *(NEW)* | tenant root: `id`, `name`, `created_at`. | — |
| **0013** | **`bridges`** *(NEW)* | `id`, `municipality_id`→municipalities (hard FK), `name`, `location`, `created_at`. | 0012 |
| **0014** | **`sensors`** *(NEW)* | `id`, `bridge_id`→bridges (hard FK), `sensor_type`, `config`, `created_at`. | 0013 |
| **0015** | **`tenant_columns_and_fks`** *(NEW)* | add denormalized `municipality_id` + the hard tenancy FKs (`sensor_id`→sensors, `bridge_id`→bridges) to the 7 SOR tables + `sensor_status` + `decision_log`; add `municipality_id` B-tree index on each. | 0005, 0014 |
| **0016** | **`rls_policies`** *(NEW)* | `ENABLE` + `FORCE ROW LEVEL SECURITY` and a per-table SELECT/INSERT policy keyed on the session municipality, granted to `bridgeguard_service`, on every tenant-scoped table. | 0015 |

- **Why `analysis_results` = 0005 and not 0012+:** it fills the pre-existing gap and matches the
  header references; putting it later would leave `0005` permanently empty (a "gap") and keep the
  dangling reference. It only depends on `validated_readings` (0002), which precedes it.
- **Why tenancy columns/FKs are one migration (0015), applied to old *and* new tables together:**
  uniform treatment — one place that establishes "every tenant-scoped table has `municipality_id` +
  the right hard FK + an index." Avoids editing eight built files and keeps the wiring auditable in a
  single diff.
- **Why RLS is its own migration (0016), last:** policies can only be attached after the columns
  they key on exist (0015) and after every referenced table exists. Isolating it makes the security
  surface reviewable as one unit.
- **`[DB-DEP]` note:** because nothing has been applied live, 0015's column-adds need no data backfill
  today. When a Neon instance first exists **with data**, 0015 must backfill `municipality_id` from the
  `sensor→bridge→municipality` chain before the `NOT NULL`/FK is validated — flagged as a plan note,
  not a code path now.

---

## 2. RLS implementation (Neon/Postgres)

**Goal (spec FR-4 / AC-4): municipality A gets ZERO municipality-B rows even when the query omits a
scope filter — enforced by the store.**

### The mechanism
- **One application role, `bridgeguard_service`** (already referenced by the append-only grants in
  0001/0004). The API connects as this role. It is **not** the table owner, and every tenant table is
  set `FORCE ROW LEVEL SECURITY` so that ownership/`BYPASSRLS` cannot silently defeat isolation.
- **Per-request municipality resolution via a session GUC.** At the start of each request/transaction
  the API calls `set_config('app.municipality_id', <principal.municipality_id>, true)` (transaction-
  scoped). The principal's municipality comes from the **auth layer** (out of scope here — spec §Out
  of Scope); this layer only *consumes* it. No per-tenant DB role, no connection-per-tenant (doesn't
  scale on Neon's pooled connections).
- **Uniform policy shape.** Every tenant-scoped table carries a denormalized `municipality_id`, so
  each policy is the same predicate: `municipality_id = current_setting('app.municipality_id')::…`.
  Uniform, index-backed, and cheap — no per-row join.
- **Policies per table** (SELECT + INSERT `WITH CHECK`, so a caller can neither read nor write across
  tenants) on: `municipalities` (self: `id = current_setting(...)`), `bridges`, `sensors`,
  `sensor_status`, `raw_readings`, `validated_readings`, `analysis_results`, `decision_log`,
  `risk_assessments`, `report_artifacts`, `alert_dispatches`.
- **Fail-closed default.** If `app.municipality_id` is unset, `current_setting(..., true)` returns
  NULL and the predicate matches nothing → zero rows. A request that forgot to set the scope sees
  **nothing**, never everything.

### Why denormalized `municipality_id` (vs. a join through `sensors→bridges`)
The alternative — RLS policies that subquery `sensor_id → sensors.bridge_id → bridges.municipality_id`
— is more normalized but runs a correlated lookup **per row**, which fights the <500ms overview
obligation (FR-12) and makes the hot `raw_readings`/`validated_readings` reads expensive. Denormalizing
`municipality_id` onto every tenant table makes each policy a single indexed equality. The value is set
**once at insert** (the writing agent already knows the sensor's bridge/municipality) and **never
changes** — consistent with append-only immutability. A CHECK/trigger keeps it consistent with the
`sensor→bridge` chain so it cannot drift.

---

## 3. Append-only enforcement — trigger **and** revoke, consistently

The built migrations already use **both** mechanisms; the plan **ratifies both, everywhere** (defense
in depth) and applies the identical pattern to the new `0005`.

- **`REVOKE UPDATE, DELETE, TRUNCATE`** from `PUBLIC` and from `bridgeguard_service` (re-granting only
  the safe verbs) — closes the normal grant path.
- **A `BEFORE` trigger** — closes the path a `REVOKE` can't (table owner / superuser / future grant
  drift). This is why both are needed: the revoke is the routine guard, the trigger is the backstop.

Two trigger shapes, matching the two disciplines:

| Discipline | Tables | Trigger | Revoke |
|-----------|--------|---------|--------|
| **Total-block** | `raw_readings`, `decision_log` | `BEFORE UPDATE OR DELETE` → always `RAISE` | UPDATE+DELETE+TRUNCATE |
| **Correct-by-supersede** | `validated_readings`, `analysis_results`, `risk_assessments`, `report_artifacts`, `alert_dispatches` | `BEFORE UPDATE` **guard** (blocks changes to substantive/identity columns; permits stamping `superseded_by`) **+** `BEFORE DELETE` → always `RAISE` | DELETE+TRUNCATE (UPDATE allowed but guarded) |

- **`alert_dispatches` nuance (already in 0010):** its guard blocks only `assessment_id`/
  `assessment_version`/`dispatch_decision`/`trace_id`/`bridge_id`/`cycle_id`; the delivery/escalation/
  approval columns may advance on the current row. The new `0005` guard follows the
  `validated_readings`/`risk_assessments` shape (block value/outcome/provenance edits; allow
  `superseded_by`).
- **Consistency requirement:** every SOR migration names its trigger functions with the same
  convention already in use (`<table>_block_mutation` / `<table>_guard_update` /
  `<table>_block_delete`) so the pattern is greppable and uniform across 0001–0016.
- **Orthogonal to RLS:** these triggers block mutation regardless of tenant; RLS blocks cross-tenant
  visibility. Both apply.

---

## 4. Index strategy — driven by each agent's actual query patterns

Note the real timestamp columns differ per table (**not** a uniform `created_at`): sensor tables use
`sensor_time`; judgment tables use `assessed_at`/`rendered_at`/`attempted_at`; the new tenancy tables
use `created_at`. The plan uses each table's real column.

| Table | Composite / key index | Driven by (spec) | Status |
|-------|----------------------|------------------|--------|
| `raw_readings` | **`(sensor_id, sensor_time DESC)`** | DCA per-sensor baseline/gap/late-arrival window | built (0001) |
| `validated_readings` | **`(sensor_id, sensor_time DESC)`** + partial `WHERE status='PENDING'` | SA per-sensor window (SA §102) + backend timeseries (003 FR-6) + PENDING sweep | built (0002) |
| `analysis_results` *(new)* | **partial-unique `(sensor_id, calculation, block, input_version) WHERE superseded_by IS NULL`** (idempotency, FR-10) + a `(bridge_id, computed_at DESC)` read for Risk/trend | SA FR-16 idempotency; Risk reads current results per scope | **0005** |
| `risk_assessments` | **`(bridge_id, assessed_at DESC)`** + partial-unique `(bridge_id, cycle_id) WHERE superseded_by IS NULL` + partial `WHERE review_status='PENDING_HUMAN_REVIEW'` | dashboard/trend + idempotency + review queue | built (0006) |
| `report_artifacts` | **`(bridge_id, rendered_at DESC)`** + partial-unique `(assessment_id, assessment_version) WHERE superseded_by IS NULL` | trend + idempotency (FR-9/10) | built (0008) |
| `alert_dispatches` | **`(bridge_id, attempted_at DESC)`** + partial `WHERE escalation_state IN ('OPEN','ESCALATED')` + partial-unique `(assessment_id, assessment_version) WHERE superseded_by IS NULL` | alert timeline + escalation queue + idempotency | built (0010) |
| `bridges` | `(municipality_id)` | tenant listing | 0013 |
| `sensors` | `(bridge_id)` | bridge-detail sensor listing | 0014 |
| **all tenant tables** | **`(municipality_id)`** | RLS predicate performance (§2) + <500ms overview (FR-12) | 0015 |

**The three index families, made explicit (answering the brief):**
- **`(sensor_id, sensor_time)`** → `raw_readings`, `validated_readings` (and the time-ordered read on
  `analysis_results`). These are the time-series tables; served by a **standard B-tree composite, no
  TimescaleDB** (FR-11).
- **`(bridge_id, <ts>)`** → `risk_assessments`, `report_artifacts`, `alert_dispatches` — bridge-keyed
  trend reads (the real column is `assessed_at`/`rendered_at`/`attempted_at`, not `created_at`).
- **assessment-keyed** → the partial-unique `(assessment_id, assessment_version)` on
  `report_artifacts`/`alert_dispatches` and `(bridge_id, cycle_id)` on `risk_assessments` — these back
  **idempotency**, not trend.
- **overview read model (FR-12):** "current risk per bridge for a municipality" is served by
  `(municipality_id)` + the partial-unique-current index on `risk_assessments` — latest current row
  per bridge without scanning history.

---

## 5. Soft vs. hard FK — confirmed intentional, and why

**Confirmed: cross-agent *provenance* links stay soft; the *tenancy* chain and `superseded_by` are
hard.** Two categories, two rules:

### Soft (kept as `BIGINT[]` arrays / `BIGINT`+version, **no** SQL FK)
`validated_readings.source_raw_ids`, `analysis_results.source_validated_ids`,
`risk_assessments.source_analysis_ids`, `report_artifacts.source_analysis_ids`, and the
`assessment_id`+`assessment_version` pins on report/alert. **Intentional**, for four reasons:
1. **Agent independence (Principle III).** Each agent publishes its table as a *contract*, not a
   schema coupling. A hard FK would make the SA table's existence a compile-time dependency of Risk's
   inserts and bind their migration lifecycles together; the array keeps them decoupled — exactly the
   "documented decoupling" the `0006`/`0008` headers already assert.
2. **No cascade on safety data.** A hard FK invites `ON DELETE` semantics; on append-only safety data
   we **never** want a cascade to touch a verdict because an input row changed. DELETE is blocked
   anyway, so a cascade could never even fire — the FK would be enforcement theater.
3. **Provenance must survive supersession.** A report legitimately points at a **now-superseded**
   analysis/assessment row (that's the point of version pinning — FR-9). A naive FK is fine with that,
   but the *array* case (`source_*_ids` referencing many rows, some later superseded) cannot be a SQL
   FK at all, and mixing hard-FK scalars with soft-FK arrays for the same "provenance" concept would be
   inconsistent. One rule — soft — keeps provenance uniform.
4. **Arrays can't be FKs.** `BIGINT[]` provenance simply has no `REFERENCES` form in Postgres;
   integrity is asserted by the writing agent + the append-only guarantee that targets never vanish.

### Hard (real `REFERENCES`, added in 0013/0014/0015)
The **tenancy ownership chain** — `bridges.municipality_id → municipalities`,
`sensors.bridge_id → bridges`, `<sensor-keyed>.sensor_id → sensors`,
`<bridge-keyed>.bridge_id → bridges` — and the `superseded_by` **self-references** (already hard on the
built tables). **Intentional**, because:
- Isolation is a **safety/privacy guarantee** (Principle III) that must be **structurally impossible**
  to violate: no orphan bridge/sensor/reading with a dangling or absent tenant, ever (spec AC-1).
- These references are to **long-lived, never-deleted** parent rows (a municipality/bridge/sensor is
  onboarded, not churned), so there is **no cascade-delete hazard** — the concern that argues *against*
  hard FKs on provenance does not exist here.
- `superseded_by` self-FKs keep each correction chain internally valid within one table.

**Net:** hard where a missing/renamed parent would be a safety defect (tenancy) or an internal
inconsistency (`superseded_by`); soft where a hard link would couple agents, risk cascades on safety
data, or is structurally impossible (arrays). This matches — and now documents the *why* behind — the
pattern the built migrations already chose.

---

## 6. Seed data (test suite runs with no live hardware)

**A dedicated seed fixture, kept OUT of the numbered schema migrations** (e.g. `db/seed/seed_dev.sql`
or a fixture builder the fakes load), so test/dev data never enters production schema history. It
populates the ownership chain minimally but sufficiently to exercise every guarantee:

- **≥ 2 municipalities** — `MUNI_A`, `MUNI_B`. Two is the **minimum to prove isolation**: every RLS
  test asserts a `MUNI_A` principal sees zero `MUNI_B` rows (AC-4). One municipality could never prove
  a negative.
- **Bridges per municipality** — e.g. `MUNI_A` → `BRIDGE_A1`, `BRIDGE_A2`; `MUNI_B` → `BRIDGE_B1`.
  Gives cross-tenant pairs and an intra-tenant multi-bridge overview (AC-11).
- **Sensors per bridge, covering the type catalogue** — at least one of each `sensor_type` the SA/DCA
  handle (accelerometer, strain gauge, crack, load cell, temperature, tiltmeter, displacement/LVDT)
  under `BRIDGE_A1`, so the agent fakes have real `sensor_id`s that resolve up the chain and every
  calculation path has an eligible sensor.
- **Optional shallow downstream rows** — a couple of `raw_readings`/`validated_readings` and one
  `risk_assessments` per bridge, so provenance-walk (AC-5) and overview (AC-11) tests have end-to-end
  data. Kept minimal; the agent test-harnesses generate their own richer fixtures.

The seed sets each row's denormalized `municipality_id` consistently with the chain, so RLS tests are
meaningful. This is **config/fixture, not schema** — real municipalities/bridges/sensors are stakeholder
onboarding data (spec Open Items), never guessed into a migration.

---

## Constitution Check (v2.1.0)

| Principle | How this plan complies |
|---|---|
| I — Safety First | Isolation + immutability enforced at the store (RLS FORCE + triggers) so no consumer bug can leak or mutate safety data; no action logic here. |
| II — Data Integrity | Both revoke+trigger on all seven SOR tables; hard tenancy FKs prevent orphans; soft provenance links keep the traceable chain intact across supersession. |
| III — Modularity | Soft provenance FKs preserve agent independence; the ownership chain is the shared tenant contract; RLS is the store-side isolation the API depends on. |
| IV — Reliability over Cleverness | Plain Postgres RLS + B-tree composites; no TimescaleDB; uniform, greppable trigger/policy conventions over clever per-row joins. |
| V — Testability | Two-municipality seed proves isolation; every FR→AC verifiable via fakes now and live constraints on a Neon instance (`[DB-DEP]`). |
| VI — Auditability | Append-only `decision_log`; supersede chains + version pinning keep verdicts reproducible; RLS/append triggers are declarative and reviewable. |
| VII — Tech Stack | Neon/Postgres, standard B-tree only, no TimescaleDB; single `bridgeguard_service` role; migration headers reconciled. |

---

## Open Items (resolve before / during migration writing)

1. **Key types for the tenancy PKs.** `sensors.id`/`bridges.id` as **TEXT natural keys** (matching the
   existing `sensor_id`/`bridge_id TEXT` columns, so hard FKs add with **no type change**) vs. surrogate
   BIGINT + a TEXT business key. Recommendation: **TEXT natural keys** for zero-churn FK wiring;
   confirm.
2. **`municipality_id` type + where it's minted** — TEXT code (e.g. `MUNI_A`) vs. surrogate; and the
   exact GUC name (`app.municipality_id`) the auth layer will set. Coordinate with the auth spec seam.
3. **`sensors.config` shape** — what per-sensor config belongs here vs. in the DCA/SA shared registry
   (JSONB blob vs. typed columns). Deferred from spec Open Items.
4. **Backfill step in 0015** — when a live instance first has data, the order (add nullable
   `municipality_id` → backfill from chain → set NOT NULL + validate FK). No-op on today's empty DB.
5. **`policy_version` on `alert_dispatches`** — add the AlertPolicy audit stamp now (new column in a
   small ALTER) or defer. Flagged in research §4.
6. **Soft-ref integrity checks** — whether to add lightweight validation (e.g. a periodic check that
   `source_*_ids` resolve) since they aren't FK-enforced. Optional; not blocking.
7. **`analysis_results` full column list** — ratify against SA spec FR-13 before writing 0005 (the one
   genuinely new table; the rest is wiring).
