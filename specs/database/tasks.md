# Database Layer — Tasks (Spec 002)

**Status:** Draft for review (do not implement / write SQL until approved)
**Date:** 2026-07-14
**Spec:** `specs/database/spec.md` (13 FR / 12 AC — approved)
**Plan:** `specs/database/plan.md` (additive migration order 0005 + 0012–0016; RLS via session GUC;
trigger+revoke; three index families; soft provenance / hard tenancy FKs; two-municipality seed)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.1.0** (Neon/Postgres, standard
B-tree indexes only, no TimescaleDB)

## Confirmed decisions (acceptance checks reference these + spec FRs/ACs)

- **Tenancy PKs are TEXT natural keys** for `municipalities` and `bridges` (and `sensors` follows the
  same, matching the existing `sensor_id`/`bridge_id TEXT` columns) — so hard FKs wire in with **no
  column-type change** to the built tables.
- **The session GUC is `app.current_municipality_id`** — exactly this name, no variation — set per
  request/transaction by the API from the auth principal; RLS predicates read
  `current_setting('app.current_municipality_id', true)` and **fail closed** (zero rows) when unset.
- **Seven SOR tables** (not six): `raw_readings`, `decision_log` (append-only total-block);
  `validated_readings`, `analysis_results`, `risk_assessments`, `report_artifacts`, `alert_dispatches`
  (correct-by-supersede). `sensor_status` (0003) is **excluded** — deliberately mutable current-state.
- **Migration order is additive:** `analysis_results` fills the empty **0005** slot; tenancy appends
  as **0012** municipalities → **0013** bridges → **0014** sensors → **0015** tenant-columns+FKs →
  **0016** RLS. **No built file is renumbered** (tests open migrations by filename).
- **Append-only = trigger AND revoke** on all seven SOR tables (defense in depth), two trigger shapes
  (total-block vs. guard-update+block-delete), uniform naming (`<table>_block_mutation` /
  `_guard_update` / `_block_delete`).
- **Soft provenance FKs** (`source_*_ids` arrays, `assessment_id`+version) stay soft — agent
  independence, no cascade on safety data, survive supersession, arrays can't be FKs. **Hard FKs** for
  the tenancy chain + `superseded_by` self-refs.
- **RLS uses a denormalized `municipality_id`** on every tenant-scoped table (single indexed equality,
  not a per-row join), set once at insert, immutable thereafter.

## Conventions

- Each task is **< 1 hour** and **independently verifiable**; acceptance checks are concrete (tied to
  an FR/AC or a decision above), never "works correctly". Same granularity as the DCA/SA/Risk/Report/
  Alert builds.
- **[DB-DEP]** = needs a live Neon instance to fully verify (RLS policies, triggers, FK enforcement
  only truly fire in-engine). Built/verified against an **in-memory fake** now (mirroring the
  `FakeStore`/`FakeRiskStore`/`FakeAlertStore` pattern); live enforcement honestly deferred — **no
  Neon instance locally**. This is the same discipline every prior migration used (`[DB-DEP]` headers
  on 0001–0011).
- **Test-first cadence** (same as the agent builds): write the failing check → confirm red →
  implement → confirm green → STOP. Fakes carry the guarantees the live engine will later enforce.
- **Task prefix `D`** (**D**atabase) — no collision with DCA `T`, SA `S`, Risk `R`, Report `G`,
  Alert `A`.
- **No SQL is written until this task list is approved.** Every task below describes *what* to build
  and *how it's checked*, not the DDL.

---

## Phase 1 — Foundation tables (municipalities, bridges, sensors)

The tenant root. Nothing downstream can be tenant-attributed until these exist; built first so every
later phase can reference real rows.

- **D101 — `municipalities` migration (0012) [DB-DEP].**
  New migration `0012_municipalities.sql`: `id` TEXT PK, `name` TEXT NOT NULL, `created_at` TIMESTAMPTZ
  DEFAULT now(). Header states Neon/Postgres, standard B-tree only, `[DB-DEP]`.
  **Acceptance:** table + TEXT PK representable; a duplicate `id` is rejected; `name` NOT NULL enforced.
  In-fake: a `FakeTenantStore` accepts a municipality and rejects a duplicate id. = spec FR-1 (root of
  the ownership chain), AC-1.

- **D102 — `bridges` migration (0013) with hard FK to municipalities [DB-DEP].**
  `0013_bridges.sql`: `id` TEXT PK, `municipality_id` TEXT NOT NULL **REFERENCES municipalities(id)**,
  `name`, `location`, `created_at`. Index `(municipality_id)` (plan §4).
  **Acceptance:** a bridge referencing a **non-existent** municipality is **rejected** (hard FK); a
  valid one inserts; `(municipality_id)` index present. In-fake: inserting a bridge under an unknown
  municipality raises. = spec FR-1, AC-1 (no orphan bridge).

- **D103 — `sensors` migration (0014) with hard FK to bridges [DB-DEP].**
  `0014_sensors.sql`: `id` TEXT PK, `bridge_id` TEXT NOT NULL **REFERENCES bridges(id)**, `sensor_type`
  TEXT NOT NULL, `config` JSONB, `created_at`. Index `(bridge_id)`.
  **Acceptance:** a sensor referencing a non-existent bridge is rejected; a valid one inserts;
  `sensor_type` NOT NULL; `(bridge_id)` index present. = spec FR-1/FR-2, AC-1 (no orphan sensor; the
  join that makes sensor-keyed rows tenant-attributable).

- **D104 — Ownership-chain resolution check (municipality ← bridge ← sensor) [DB-DEP].**
  A test asserting the chain resolves: given a `sensor_id`, a query walks `sensors.bridge_id →
  bridges.municipality_id` to exactly one municipality; a sensor with no bridge, or a bridge with no
  municipality, cannot exist (proven by D102/D103 FKs).
  **Acceptance:** every seeded sensor resolves to exactly one municipality; the walk has no missing
  hop. = spec FR-1/FR-2/FR-3, AC-2 (sensor-keyed attribution), AC-1.

---

## Phase 2 — Migration 0005 (analysis_results) — the missing SA table

The one genuinely new agent-output table. Fills the empty `0005` slot; completes the provenance chain.

- **D201 — Ratify `analysis_results` column list against SA spec FR-13.**
  A written column manifest (no SQL yet) mapping every SA output-contract field to a column:
  `sensor_id`, `calculation`, `block`/reading identity, `outcome` (RAN|SKIPPED|ERROR), `reason_code`,
  result value(s), `source_validated_ids` (BIGINT[] soft provenance), `input_version`,
  `interpolated_input`/`clock_drift`/`rate_mismatch` flags, `config_version` + constants,
  `superseded_by`, `computed_at`. Reconciled against `specs/structural-analysis-agent/spec.md` §383–391.
  **Acceptance:** every SA FR-13 output field has exactly one column; the manifest is signed off before
  D202. = spec FR-5 (SA table completes the contract).

- **D202 — `analysis_results` migration (0005) — table + enums [DB-DEP].**
  `0005_analysis_results.sql` per D201: the `analysis_outcome` enum (RAN|SKIPPED|ERROR), a closed
  skip-`reason_code`, columns from D201, `source_validated_ids` BIGINT[] (soft, per plan §5). **No
  tenant FK inline** (sensors created later in 0014; wired in 0015). Header: Neon/no-TimescaleDB,
  `[DB-DEP]`, cross-agent decoupling note (mirrors 0006/0008).
  **Acceptance:** enums + columns representable; a `RAN` row carries a finite value; a `SKIPPED` row
  carries a reason_code and no value; a degenerate result is `SKIPPED/DEGENERATE_RESULT`, never `RAN`
  (SA FR-13). In-fake: `FakeAnalysisStore` enforces these shapes. = spec FR-5, AC-5.

- **D203 — `analysis_results` correct-by-supersede + idempotency [DB-DEP].**
  Add the guard-update trigger (block edits to outcome/value/provenance; permit `superseded_by`), the
  block-delete trigger, and the **partial-unique index `(sensor_id, calculation, block, input_version)
  WHERE superseded_by IS NULL`** (SA FR-16 idempotency). Mirrors `risk_assessments` (0006) discipline.
  **Acceptance:** an in-place edit to a result value is rejected; a correction appends + links
  `superseded_by`; DELETE is blocked; a re-trigger for the same input version creates no duplicate
  current row; a new input version supersedes. = spec FR-7/FR-10, AC-7/AC-9.

- **D204 — Analysis-layer of the provenance chain resolves [DB-DEP].**
  A test walking `analysis_results.source_validated_ids → validated_readings` and (upward)
  `risk_assessments.source_analysis_ids → analysis_results` — the two hops impossible before 0005.
  **Acceptance:** given a seeded analysis row, its `source_validated_ids` resolve to real
  `validated_readings`; a risk assessment's `source_analysis_ids` resolve to real analysis rows; no
  missing hop. = spec FR-8, AC-5 (completes the chain).

---

## Phase 3 — Migrations 0012–0016 (tenant columns, FKs, RLS wiring)

Wire the built + new SOR tables to the tenancy foundation, then attach RLS. (0012–0014 are Phase 1;
this phase is the wiring migration 0015 + RLS 0016.)

- **D301 — Tenant-column add: denormalized `municipality_id` on all tenant-scoped tables (0015 part A) [DB-DEP].**
  `0015_tenant_columns_and_fks.sql` (part A): add `municipality_id` TEXT to the seven SOR tables +
  `sensor_status`, and `bridge_id` where absent (`raw_readings`, `validated_readings`,
  `analysis_results`, `sensor_status`, `decision_log`). Plan §2: denormalized for single-equality RLS.
  **Acceptance:** every tenant-scoped table has a `municipality_id` column after the migration; the
  judgment tables already having `bridge_id` are unchanged; column-add is additive (no data loss).
  = spec FR-2/FR-3 (attribution columns exist).

- **D302 — Hard tenancy FKs (0015 part B) [DB-DEP].**
  Part B: add `sensor_id → sensors(id)` on the sensor-keyed tables, `bridge_id → bridges(id)` on the
  bridge-keyed + newly-`bridge_id`'d tables, and `municipality_id → municipalities(id)` on all. Per
  plan §5 (hard, because a dangling tenant is a safety defect). **Soft provenance arrays untouched.**
  **Acceptance:** inserting a reading whose `sensor_id` is not in `sensors` is rejected; a row whose
  `municipality_id` is unknown is rejected; the `source_*_ids` arrays remain plain BIGINT[] (no FK).
  = spec FR-1/FR-2/FR-3, AC-1/AC-2/AC-3.

- **D303 — `municipality_id` consistency guard (denormalized value can't drift) [DB-DEP].**
  A CHECK/trigger asserting a row's `municipality_id` equals the one reached via its
  `sensor_id`/`bridge_id` chain, so the denormalized copy can never contradict the FK chain (plan §2).
  **Acceptance:** a row whose `municipality_id` disagrees with `sensor→bridge→municipality` is
  rejected; a consistent row inserts. = spec FR-2/FR-3 (attribution is trustworthy).

- **D304 — `municipality_id` index pass (0015 part C) [DB-DEP].**
  Add a B-tree `(municipality_id)` index on every tenant-scoped table (RLS predicate performance +
  overview read model, plan §4).
  **Acceptance:** each tenant-scoped table has a `(municipality_id)` index after the migration.
  = spec FR-4/FR-12 (RLS + fast overview backed by an index).

- **D305 — RLS enable + FORCE on all tenant-scoped tables (0016 part A) [DB-DEP].**
  `0016_rls_policies.sql` (part A): `ENABLE ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL SECURITY` on
  `municipalities`, `bridges`, `sensors`, `sensor_status`, `raw_readings`, `validated_readings`,
  `analysis_results`, `decision_log`, `risk_assessments`, `report_artifacts`, `alert_dispatches`.
  FORCE so table-owner/BYPASSRLS cannot silently defeat isolation (plan §2).
  **Acceptance:** RLS is ENABLED + FORCED on all eleven tables (introspection check); a table missing
  FORCE fails the check. = spec FR-4, AC-4.

- **D306 — Per-table RLS policies keyed on `app.current_municipality_id` (0016 part B) [DB-DEP].**
  Part B: a SELECT + INSERT (`WITH CHECK`) policy per table with predicate
  `municipality_id = current_setting('app.current_municipality_id', true)` (self-predicate `id = …`
  for `municipalities`), granted to `bridgeguard_service`. Fail-closed: unset GUC → NULL → zero rows.
  **Acceptance:** with the GUC set to `MUNI_A`, a SELECT returns only `MUNI_A` rows; with the GUC
  **unset**, SELECT returns **zero** rows (fail-closed); an INSERT with a foreign `municipality_id` is
  rejected by `WITH CHECK`. [live in D601; structural presence checked here.] = spec FR-4, AC-4.

---

## Phase 4 — Append-only enforcement (triggers + revoke, all 7 SOR tables)

Ratify the built tables' discipline and apply the identical pattern to the new `0005`. (Built tables
already carry these; this phase is a uniform audit + the 0005 additions from D203.)

- **D401 — Total-block audit: `raw_readings` + `decision_log` [DB-DEP].**
  Verify both carry `REVOKE UPDATE, DELETE, TRUNCATE` **and** a `BEFORE UPDATE OR DELETE` → RAISE
  trigger (built in 0001/0004; this task confirms and, if the tenant-column add in 0015 disturbed
  anything, re-asserts). Naming: `<table>_block_mutation`.
  **Acceptance:** UPDATE and DELETE on `raw_readings` and `decision_log` both raise; TRUNCATE revoked;
  the tenant-column add (D301) did not weaken the block. = spec FR-6, AC-6.

- **D402 — Correct-by-supersede audit: the five supersede tables [DB-DEP].**
  Confirm `validated_readings` (0002), `risk_assessments` (0006), `report_artifacts` (0008),
  `alert_dispatches` (0010), and `analysis_results` (0005, from D203) each carry a guard-update trigger
  (blocks substantive/identity edits, permits `superseded_by`) + a block-delete trigger + DELETE
  revoke. Uniform naming (`_guard_update` / `_block_delete`).
  **Acceptance:** an in-place substantive edit raises on **all five**; DELETE raises on all five;
  stamping `superseded_by` succeeds on all five; `alert_dispatches` still permits its delivery-state
  advance (the one nuance). = spec FR-7, AC-7.

- **D403 — Uniformity check across all seven SOR tables [DB-DEP].**
  A single test enumerating the seven tables and asserting each has the expected trigger(s) + revokes
  by the naming convention — so the discipline is provably consistent, not per-file drift. Confirms
  `sensor_status` is **correctly excluded** (mutable current-state).
  **Acceptance:** all seven SOR tables match their expected discipline; `sensor_status` is excluded and
  remains freely UPDATE-able; no SOR table is missing a guard. = spec FR-6/FR-7, plan §0/§3.

---

## Phase 5 — Index pass (all three index families)

- **D501 — `(sensor_id, sensor_time)` family verified (time-series tables) [DB-DEP].**
  Confirm the composite `(sensor_id, sensor_time DESC)` on `raw_readings` (0001) and
  `validated_readings` (0002), and the time-ordered read index on `analysis_results` (0005). Assert
  **no** TimescaleDB/hypertable anywhere.
  **Acceptance:** the composite exists on both built tables; `analysis_results` has its time-ordered
  read index; a grep for `timescale`/`hypertable`/`create_hypertable` across all migrations returns
  nothing. = spec FR-11/FR-13, AC-10/AC-12.

- **D502 — `(bridge_id, <ts>)` family verified (bridge-keyed trend) [DB-DEP].**
  Confirm `(bridge_id, assessed_at DESC)` on `risk_assessments`, `(bridge_id, rendered_at DESC)` on
  `report_artifacts`, `(bridge_id, attempted_at DESC)` on `alert_dispatches` — using each table's
  **real** timestamp column (not a uniform `created_at`, per plan §4).
  **Acceptance:** each of the three has its `(bridge_id, <real ts>)` index; the timestamp column
  matches the built schema. = spec FR-12 (trend reads).

- **D503 — Assessment-keyed idempotency indexes verified [DB-DEP].**
  Confirm the partial-unique-current indexes: `(bridge_id, cycle_id)` on `risk_assessments`,
  `(assessment_id, assessment_version)` on `report_artifacts` + `alert_dispatches`, and
  `(sensor_id, calculation, block, input_version)` on `analysis_results` — all `WHERE superseded_by IS
  NULL`.
  **Acceptance:** each partial-unique exists; a second current row for the same key is rejected; a
  superseded row frees the slot. = spec FR-10, AC-9.

- **D504 — Overview read-model index confirmed (fast, no history scan) [DB-DEP].**
  Confirm the "current risk per bridge for a municipality" read is served by `(municipality_id)`
  (D304) + the `risk_assessments` partial-unique-current index — no raw/historical scan.
  **Acceptance:** the overview query plan uses indexes only (no seq-scan of raw/historical rows on a
  seeded set); returns the latest current row per bridge. = spec FR-12, AC-11 (backend AC-2 dependency).

---

## Phase 6 — RLS verification (prove municipality A cannot see B's data)

The explicit isolation acceptance. Requires the seed (Phase 7 D701 provides ≥2 municipalities) —
**D601 depends on D701**; listed here to keep the verification story together.

- **D601 — Cross-tenant SELECT isolation: A sees zero B rows [DB-DEP].**
  With `app.current_municipality_id = MUNI_A`, SELECT every tenant-scoped table and assert **zero**
  rows belonging to `MUNI_B`, across all eleven tables — the core AC-4 proof. Then flip to `MUNI_B`
  and assert the mirror.
  **Acceptance:** MUNI_A principal sees only MUNI_A rows on every table; **zero** MUNI_B rows anywhere;
  and vice-versa. = spec FR-4, **AC-4 (explicit RLS criterion)**.

- **D602 — Fail-closed on unset scope [DB-DEP].**
  With `app.current_municipality_id` **unset**, SELECT every tenant-scoped table.
  **Acceptance:** every table returns **zero** rows (never all rows) — a forgotten scope leaks
  nothing. = spec FR-4, AC-4 (store-enforced, not caller-enforced).

- **D603 — Cross-tenant INSERT blocked by WITH CHECK [DB-DEP].**
  As `MUNI_A`, attempt to INSERT a row with `municipality_id = MUNI_B`.
  **Acceptance:** the INSERT is rejected by the policy `WITH CHECK`; a same-tenant INSERT succeeds.
  = spec FR-4, AC-4 (write-side isolation).

- **D604 — FORCE defeats owner/BYPASS attempt [DB-DEP].**
  Confirm that even a connection as the table owner is subject to RLS (FORCE), so isolation cannot be
  silently bypassed by connecting as owner.
  **Acceptance:** an owner-role SELECT with a set scope still returns only in-scope rows; FORCE is
  active on all eleven tables. = spec FR-4, AC-4 + plan §2.

---

## Phase 7 — Seed data + test fixtures

- **D701 — Seed fixture: two municipalities + bridges + full sensor-type coverage.**
  `db/seed/seed_dev.sql` (OUT of numbered schema migrations, per plan §6): `MUNI_A`, `MUNI_B`;
  `MUNI_A → BRIDGE_A1, BRIDGE_A2`, `MUNI_B → BRIDGE_B1`; under `BRIDGE_A1` one sensor of **each**
  `sensor_type` (accelerometer, strain gauge, crack, load cell, temperature, tiltmeter,
  displacement/LVDT). Each row's `municipality_id` set consistent with its chain.
  **Acceptance:** seed loads with all FKs satisfied; ≥2 municipalities exist (isolation provable);
  every SA-handled sensor_type has a real `sensor_id` resolving up the chain. = spec §Testability, AC-1;
  enables D601.

- **D702 — Shallow downstream seed (provenance + overview data).**
  A couple of `raw_readings` + `validated_readings` per seeded sensor and one `risk_assessments` (with
  resolvable `source_analysis_ids` → one seeded `analysis_results` → `source_validated_ids`) per
  bridge, so provenance-walk and overview tests have end-to-end rows. Minimal; agents' own harnesses
  generate richer data.
  **Acceptance:** each seeded assessment's provenance resolves to a raw reading; each bridge has a
  current risk row for the overview. = spec FR-8/FR-12; enables D801/D504.

- **D703 — In-memory fake store parity (`FakeTenantStore` + wiring into agent fakes).**
  A fake that mirrors the tenancy chain + RLS-scoping + append/supersede guarantees for tests that
  can't hit live Neon (same pattern as `FakeRiskStore`/`FakeAlertStore`). Lets existing agent fakes
  attach a `municipality_id`/`sensor→bridge` context.
  **Acceptance:** the fake rejects orphan bridges/sensors, enforces append/supersede, and scopes reads
  by a set municipality — so `[DB-DEP]` tests are meaningful without Neon. = spec §Testability.

---

## Phase 8 — End-to-end provenance test (risk score → raw reading)

- **D801 — Full-chain walk: a risk score traces to an immutable raw reading [DB-DEP].**
  Over the seed (D702), start from one `risk_assessments` row and walk every hop:
  `risk_assessments.source_analysis_ids → analysis_results.source_validated_ids →
  validated_readings.source_raw_ids → raw_readings`, asserting each hop resolves and the terminal
  `raw_readings` row is append-only (UPDATE/DELETE raise).
  **Acceptance:** every hop resolves to a real row with no missing link; the terminal raw row is
  immutable; the walk is possible **only because 0005 now exists**. = spec FR-8, **AC-5** (chain
  completeness), FR-6.

- **D802 — Provenance survives supersession [DB-DEP].**
  Supersede the analysis row mid-chain (append a new version, stamp `superseded_by`); confirm the
  original report/assessment still resolves to the **pinned** version it acted on.
  **Acceptance:** after supersession the report/alert still walks to the exact `assessment_version` it
  pinned; the superseded row is still readable (history permanent). = spec FR-7/FR-9, AC-7/AC-8.

- **D803 — Provenance walk respects tenant isolation [DB-DEP].**
  Run D801's walk under `app.current_municipality_id = MUNI_A` for a `MUNI_B` assessment.
  **Acceptance:** the walk returns **zero** rows (RLS blocks a cross-tenant provenance trace) — a
  provenance chain cannot be used to exfiltrate another tenant's data. = spec FR-4/FR-8, AC-4/AC-5.

---

## Phase 9 — Migration documentation

- **D901 — `db/migrations/README.md`: ordering, dependencies, discipline map.**
  Document the full 0001–0016 sequence: what each migration creates, its dependencies, the additive
  strategy (why 0005 fills the gap and tenancy appends late + wires via 0015), and the seven-SOR-table
  discipline map (total-block vs. correct-by-supersede vs. excluded `sensor_status`).
  **Acceptance:** README lists every migration 0001–0016 with dependency + discipline; a reader can
  reconstruct apply-order and why no file was renumbered. = plan §1/§3; Definition of Done (docs match).

- **D902 — RLS + GUC operator note.**
  Document the RLS model for operators: the `bridgeguard_service` role, `FORCE`, the
  `app.current_municipality_id` GUC (exact name), how the API sets it per transaction, and the
  fail-closed behaviour. Note the auth seam is out of scope (separate spec).
  **Acceptance:** the note names the exact GUC `app.current_municipality_id`, states fail-closed
  semantics, and points to where the API must set it. = spec FR-4/§Out-of-Scope; plan §2.

- **D903 — Soft-vs-hard-FK + `[DB-DEP]` rationale note.**
  A short doc recording the soft-provenance / hard-tenancy decision and its four reasons (agent
  independence, no cascade on safety data, survive supersession, arrays can't be FKs), plus what
  `[DB-DEP]` defers and how the fakes stand in.
  **Acceptance:** the note states the rule (soft provenance, hard tenancy + `superseded_by`) with
  rationale, and lists which guarantees are live-verified vs. fake-verified. = plan §5; research §3/§4.

---

## Dependency summary (ordering that unblocks later work)

```
Phase 1 (D101→D102→D103→D104)         tenant foundation — nothing attributes without it
        │
Phase 2 (D201→D202→D203→D204)         0005 analysis_results — independent of tenancy; needs 0002
        │  (D104 + D204 both feed the wiring)
Phase 3 (D301→D302→D303→D304→D305→D306) 0015 columns/FKs then 0016 RLS — needs Phases 1&2 tables
        │
Phase 4 (D401,D402→D403)              append-only audit — needs 0005 (D203) + post-0015 re-assert
        │
Phase 5 (D501,D502,D503→D504)         index pass — needs all tables + 0015 municipality_id index
        │
Phase 7 (D701→D702→D703)              seed — needs Phases 1–3 (FKs + RLS columns) to load
        │
Phase 6 (D601,D602,D603,D604)         RLS proof — needs D306 policies + D701 two-muni seed
        │
Phase 8 (D801→D802→D803)              e2e provenance — needs 0005 + seed (D702) + RLS (D306)
        │
Phase 9 (D901,D902,D903)              docs — after the schema is settled
```

**Note on Phase 6 vs 7:** RLS *policies* (D305/D306) are built in Phase 3; RLS *verification*
(Phase 6) is separated out per the brief's grouping but **depends on the Phase 7 seed** — so the true
run order interleaves: Phases 1→2→3→7→6→(4,5 anytime after their tables)→8→9. The phase numbers follow
the brief's grouping; the dependency graph above is the authoritative order.
