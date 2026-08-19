# Database Layer — Specification (Spec 002)

**Status:** Draft — awaiting human approval (behaviour-only; grounded in
`specs/database/research-db.md` + every existing migration `0001`–`0011`). The tenancy foundation,
the missing `analysis_results` table, and the Neon/no-TimescaleDB constraint are settled here as
**behaviour**; the SQL is deferred to `plan.md`/migrations after approval.
**Date:** 2026-07-13
**Anchors:** `CLAUDE.md` (Neon/Postgres, standard B-tree indexes only, composite `(sensor_id,
sensor_time)` for time-series; raw immutable; municipality-scoped data); `.specify/memory/
constitution.md` v2.1.0 (I safety, II data-immutable, III modular/tenant-scoped, IV
reliability-over-cleverness, V testability, VI auditability, VII stack); `specs/database/
research-db.md` (the six-point findings this spec closes); the built migrations `0001`–`0011`;
every agent's input/output contract (`specs/*/spec.md`); backend API AC-3 (`specs/003-backend-api`)
which is **gated on this layer** for RLS + the <500ms overview read model.

> **Behaviour only.** This spec describes WHAT the persistence layer must guarantee and WHY — no SQL,
> no column types, no index DDL, no migration bodies. Those are design decisions made after approval
> (`plan.md` → migrations). **No migrations will be written until a human approves this spec.**

---

## Goal

The database layer is BridgeGuard's **system of record** — the one place every number a human ever
sees is stored, and the one place data-integrity, tenant-isolation, and audit guarantees are
*enforced at the boundary* rather than trusted from application code. It underpins all five agents
(DCA → SA → Risk → Report → Alert) and the Backend API + Dashboard.

It exists because those consumers are deliberately thin: the agents publish contracts and the API is
"a thin transport layer" (003 §40) — none of them can guarantee, on their own, that raw data is never
mutated, that municipality A can never read municipality B's rows, or that a number is traceable to
its source. Those are **storage guarantees**, and this layer owns them.

Most of this layer **already exists in migration form** (`0001`–`0011`). This spec does two things:
(1) ratifies the guarantees those built tables already encode as the layer's binding behaviour, and
(2) closes the three gaps `research-db.md` found — the missing SA output table, the absent tenancy
foundation, and the datastore stack-conflict — **without which the layer is incomplete and the
Backend API cannot satisfy its own AC-3.**

---

## Core Concepts

- **The ownership chain is the spine of the whole schema: `municipalities → bridges → sensors →
  readings`.** Every stored row must be attributable, by following foreign keys, up to exactly one
  municipality. Sensor-keyed data (`raw_readings`, `validated_readings`, `analysis_results`) resolves
  its tenant via `sensor → bridge → municipality`; bridge-keyed judgment data (`risk_assessments`,
  `report_artifacts`, `alert_dispatches`) via `bridge → municipality`. A row that cannot be traced to
  a municipality is a defect — it cannot be isolated, and isolation is a safety/privacy guarantee, not
  a feature (Principle III).

- **Tenant isolation is enforced by the store, not by the caller.** Row-level isolation is a property
  of the database (RLS or an equivalent mandatory scope filter), so that a bug — or an absent WHERE
  clause — in any consumer *cannot* leak cross-tenant rows. "The API enforces isolation" (dashboard
  FR-17) means the API relies on **this layer** to make leakage structurally impossible.

- **Raw data is immutable; derived data is correct-by-supersede; audit trails are append-only.**
  Three distinct disciplines already proven in the built migrations, ratified here:
  - **Append-only, total-block** (`raw_readings`, `decision_log`): no UPDATE, no DELETE, ever.
  - **Correct-by-supersede** (`validated_readings`, `risk_assessments`, `report_artifacts`,
    `analysis_results`): a correction *appends* a new row and links the old one via `superseded_by`;
    the prior verdict's substance is never rewritten; DELETE is blocked.
  - **Correct-by-supersede with a live state machine** (`alert_dispatches`): identity/verdict/trace
    are frozen, but the delivery/escalation/approval state legitimately advances on the current row.

- **Every number is traceable to its source (the provenance chain).** `raw → validated → analysis →
  assessment → report/alert`. Each derived row carries the identifiers of the rows that produced it,
  so any displayed value can be walked back to the immutable raw reading it descends from
  (Principle II). This chain must be unbroken end-to-end — which is impossible today because the
  `analysis` link (`analysis_results`) has no table.

- **Version pinning outlives supersession.** Consumers that render or dispatch a verdict pin the exact
  revision (`assessment_id` + `assessment_version`), so a report or alert is reproducible against the
  precise verdict it acted on even after that verdict is later superseded (Report FR-11; Alert FR-11).

- **Neon/Postgres, standard B-tree indexes only — no TimescaleDB.** Time-series access is served by a
  composite `(sensor_id, sensor_time)` index, not a hypertable or a time-series extension
  (CLAUDE.md; constitution v2.1.0). The layer must meet its read-latency obligations within that
  constraint.

---

## What this layer is responsible for (the tables it owns)

Behaviour, not schema. `[BUILT]` = migration exists and its guarantees are ratified here.
`[NEW — REQUIRED]` = a gap this spec mandates closing.

| Table | Status | Owns / guarantees |
|---|---|---|
| `municipalities` | **NEW — REQUIRED** | the tenant root: `id`, `name`, `created_at`. Every row in the system traces here. |
| `bridges` | **NEW — REQUIRED** | `id`, `municipality_id` (→ municipalities), `name`, `location`, `created_at`. A bridge belongs to exactly one municipality. |
| `sensors` | **NEW — REQUIRED** | `id`, `bridge_id` (→ bridges), `sensor_type`, `config`, `created_at`. A sensor belongs to exactly one bridge. This is the join that makes the sensor-keyed tables tenant-attributable. |
| `analysis_results` | **NEW — REQUIRED** | the SA agent's output — currently **no table exists**. The RAN/SKIPPED/ERROR result per (sensor, calculation, block), its `source_validated_ids` provenance, `input_version`, the interpolated/clock-drift/rate-mismatch flags, and `config_version` + constants. Correct-by-supersede + DELETE-blocked; idempotent on the input version. |
| `raw_readings` | **BUILT** (0001) | append-only raw payloads; the immutable base of the provenance chain. |
| `validated_readings` | **BUILT** (0002) | DCA verdicts, correct-by-supersede, `source_raw_ids` provenance. |
| `sensor_status` | **BUILT** (0003) | current LIVE/OFFLINE device state. |
| `decision_log` | **BUILT** (0004 + kinds 0007/0009/0011) | the shared append-only audit trail across all agents. |
| `risk_assessments` | **BUILT** (0006) | Risk verdicts, correct-by-supersede, full provenance + version. |
| `report_artifacts` | **BUILT** (0008) | rendered-report records, version-pinned to the assessment. |
| `alert_dispatches` | **BUILT** (0010) | dispatch attempts with a live delivery/escalation/approval state machine over a frozen identity. |

---

## User Scenarios

- **Tenant isolation holds under a missing filter.** A consumer queries `risk_assessments` for
  municipality A **and forgets to scope the query**. The layer still returns **zero** municipality-B
  rows — isolation is enforced by the store (RLS / mandatory scope), so the bug cannot leak data.

- **The full provenance chain resolves end-to-end.** Given a displayed risk score, a reviewer walks
  `risk_assessments.source_analysis_ids → analysis_results.source_validated_ids →
  validated_readings.source_raw_ids → raw_readings` and reaches the immutable raw reading. Every hop
  exists — including the `analysis_results` hop that is impossible today.

- **A raw reading cannot be altered or deleted.** Any UPDATE or DELETE against `raw_readings` or
  `decision_log` is rejected at the database boundary, regardless of the role attempting it.

- **A late correction supersedes without rewriting history.** A DCA late-arrival recompute appends a
  new `validated_readings` row and stamps the old one's `superseded_by`; the old row's value/status is
  never mutated. Same for `analysis_results`, `risk_assessments`, `report_artifacts`.

- **A new sensor is onboarded.** A sensor is created under exactly one bridge, which belongs to
  exactly one municipality; from that moment every reading it produces is tenant-attributable with no
  extra bookkeeping.

- **The overview read is fast without scanning history.** The Backend API's <500ms overview
  (003 AC-2) reads the *current* risk row per bridge for a municipality via an index, never scanning
  raw or historical rows.

- **A dispatch's identity is frozen while its delivery state advances.** An `alert_dispatches` row
  moves `SENT → DELIVERED → ACKNOWLEDGED` on the current row, but its `assessment_id`/
  `assessment_version`/`trace_id`/`dispatch_decision` cannot be rewritten; a correction supersedes.

- **A cross-tenant foreign key is impossible.** A `bridge` cannot reference a non-existent
  municipality; a `sensor` cannot reference a non-existent bridge; the ownership chain has no orphans.

---

## Functional Requirements

A build (migration set) that ignores any of these should **visibly fail** a corresponding test.

- **FR-1 — The ownership chain exists and is total.** The layer provides `municipalities`, `bridges`,
  `sensors` such that every bridge references exactly one municipality and every sensor references
  exactly one bridge, with enforced foreign keys (no orphan rows). Every other table in the system is
  reachable to exactly one municipality by following keys. A schema where a reading, assessment,
  report, or alert cannot be resolved to a municipality fails. *(Principle III; research §6.)*

- **FR-2 — Sensor-keyed data is tenant-attributable.** `raw_readings`, `validated_readings`, and
  `analysis_results` resolve their owning municipality via `sensor_id → sensors.bridge_id →
  bridges.municipality_id`. A sensor-keyed row that cannot be joined to a municipality fails.
  *(research §6.)*

- **FR-3 — Bridge-keyed data is tenant-attributable.** `risk_assessments`, `report_artifacts`, and
  `alert_dispatches` resolve their owning municipality via `bridge_id → bridges.municipality_id`.
  *(research §6.)*

- **FR-4 — Row-level isolation is enforced by the store.** An authenticated principal scoped to
  municipality A can read **zero** rows belonging to municipality B, on every tenant-scoped table,
  **even if the querying code omits a scope filter** — isolation is a database guarantee (RLS or an
  equivalent mandatory scope), not a convention the caller must remember. A layer that relies solely
  on callers to filter fails. *(Principle III; backend AC-3; dashboard FR-17.)*

- **FR-5 — The SA output table exists and completes the provenance chain.** `analysis_results` exists
  and stores the SA output contract (SA spec FR-13): per (sensor, calculation, block) an `outcome`
  (`RAN|SKIPPED|ERROR`), a skip `reason_code`, result value(s), the `source_validated_ids` that formed
  the input, the `input_version`, the `interpolated_input`/`clock_drift`/`rate_mismatch` flags, and
  the `config_version` + constants used. Without it, Risk (`source_analysis_ids`) and Report read a
  dangling contract. A layer missing this table fails. *(research §1; SA FR-13/FR-16/FR-17.)*

- **FR-6 — Raw data and audit trails are append-only.** `raw_readings` and `decision_log` reject all
  UPDATE and DELETE at the database boundary, for any role. A layer that permits mutating a raw
  reading or an audit entry fails. *(Principle II/VI; ratifies 0001/0004.)*

- **FR-7 — Derived verdicts are correct-by-supersede, never overwritten; DELETE is blocked.**
  `validated_readings`, `analysis_results`, `risk_assessments`, `report_artifacts`, and
  `alert_dispatches` allow a correction only by appending a new row and linking the prior via
  `superseded_by`; the prior row's substantive fields cannot be rewritten and it cannot be deleted.
  `alert_dispatches` additionally permits its delivery/escalation/approval state to advance on the
  current row while its pinned identity stays frozen. A layer that allows an in-place verdict rewrite
  or a DELETE fails. *(Principle II/VI; ratifies 0002/0006/0008/0010; mandates it for new 0005.)*

- **FR-8 — The provenance chain is unbroken end-to-end.** Each derived row carries the identifiers of
  the rows it was computed from: `validated_readings.source_raw_ids → raw_readings`;
  `analysis_results.source_validated_ids → validated_readings`; `risk_assessments.source_analysis_ids`
  and `report_artifacts.source_analysis_ids → analysis_results`; `report_artifacts`/`alert_dispatches`
  → `risk_assessments` (id + version). Any displayed number is walkable back to an immutable raw row.
  A layer with a broken link fails. *(Principle II; research §3.)*

- **FR-9 — Version pinning survives supersession.** A report or alert records the exact
  `assessment_id` + `assessment_version` it rendered/dispatched, so it is reproducible against that
  precise verdict after the verdict is superseded. A layer that cannot say which version a report/alert
  acted on fails. *(Report FR-11; Alert FR-11.)*

- **FR-10 — Idempotency is a storage guarantee.** At most one *current* (non-superseded) row exists
  per natural key on the correct-by-supersede tables — `validated_readings` per sensor/time,
  `analysis_results` per (sensor, calculation, block, input-version), `risk_assessments` per
  (bridge, cycle), `report_artifacts`/`alert_dispatches` per (assessment_id, assessment_version). A
  redelivered trigger cannot create a duplicate current row. A layer that permits two current rows for
  one key fails. *(Ratifies the partial-unique-current indexes in 0006/0008/0010; mandates for 0005.)*

- **FR-11 — Time-series reads are served by a standard composite index, no TimescaleDB.** The
  `(sensor_id, sensor_time)` access pattern (DCA windows, SA windows, the backend timeseries endpoint)
  is served by a standard B-tree composite index on `raw_readings` and `validated_readings` (and the
  time-ordered read on `analysis_results`), with **no** TimescaleDB/hypertable/time-series extension.
  A layer that depends on TimescaleDB fails. *(CLAUDE.md; constitution v2.1.0; research §5.)*

- **FR-12 — The overview read model avoids scanning history.** The current-status-per-bridge read
  that backs the Backend API's <500ms overview (003 AC-2) is served by an index over current rows,
  not a scan of raw/historical data. *(Backend AC-2; research §5.)*

- **FR-13 — The datastore is Neon/Postgres and the migrations agree.** All migration headers and
  constraints reflect Neon/Postgres with standard B-tree indexes only; none reference Supabase or
  TimescaleDB as the datastore. *(CLAUDE.md; constitution v2.1.0; research §4 — the 0001/0004 header
  fix is done, this FR keeps them consistent.)*

---

## Edge Cases & Rules

- **Orphaned reference.** Creating a bridge under a non-existent municipality, or a sensor under a
  non-existent bridge, is rejected (FR-1).
- **Cross-tenant read with no scope filter.** Returns zero foreign-tenant rows regardless of the
  omission — the store enforces it (FR-4).
- **In-place verdict edit attempt.** Rejected; corrections must append + supersede (FR-7).
- **Raw reading UPDATE/DELETE by a privileged role.** Rejected at the DB boundary (FR-6).
- **Redelivered trigger.** No duplicate current row on any correct-by-supersede table (FR-10).
- **Dispatch state advance vs. identity edit.** Advancing `delivery_state` is allowed; rewriting
  `assessment_id`/`trace_id`/`dispatch_decision` is rejected (FR-7).
- **A reading whose sensor was deleted.** History is permanent; sensor lifecycle vs. reading retention
  is a retention-policy decision deferred to plan (see Open Items) — but a reading must never lose its
  municipality attribution.
- **`analysis_results` for a degenerate calc.** Stored as SKIPPED/`DEGENERATE_RESULT`, not as a RAN
  value — a NaN never reaches Risk as a real number (SA FR-13); the table must represent this.

---

## Out of Scope

- **Authentication / token issuance / how a principal acquires its municipality scope** — a separate
  auth spec (003 §22, §157). This layer provides the *scoping columns + RLS* a principal plugs into;
  it does not mint or validate tokens.
- **The REST endpoints themselves** — Backend API (Spec 003). This layer serves them.
- **Agent logic** — each agent (Specs 001/002-agents/003-risk/004-report/005-alert) owns its own
  computation; this layer stores their outputs and enforces integrity, it never re-computes.
- **The concrete SQL, column types, index DDL, RLS policy bodies, and migration files** — deferred to
  `plan.md` and the migrations, written **only after this spec is approved**.
- **Retention / archival policy** (how long historical superseded rows live) — a plan/ops decision;
  the constitution's default is "retained indefinitely unless a period is specified."
- **Soft-ref vs hard-FK for the provenance *arrays*** (`source_*_ids`) — currently deliberately soft
  (Principle III decoupling); whether to harden any is a plan decision (research §4). The *tenancy*
  FKs (FR-1) and `superseded_by` self-refs are hard FKs and are in scope here.

---

## Acceptance Criteria

Each is testable against a scenario above (verified via the in-memory fakes until a Neon instance
exists, mirroring the established `[DB-DEP]` pattern).

- **AC-1 — Ownership chain.** `municipalities`, `bridges`, `sensors` exist with enforced FKs; a bridge
  with no municipality and a sensor with no bridge are both rejected. *(FR-1)*
- **AC-2 — Sensor-keyed attribution.** Every `raw_readings`/`validated_readings`/`analysis_results`
  row resolves to exactly one municipality via `sensor → bridge → municipality`. *(FR-2)*
- **AC-3 — Bridge-keyed attribution.** Every `risk_assessments`/`report_artifacts`/`alert_dispatches`
  row resolves to exactly one municipality via `bridge → municipality`. *(FR-3)*
- **AC-4 — RLS isolation (explicit).** An authenticated principal for **municipality A receives ZERO
  rows belonging to municipality B** on every tenant-scoped table, **including when the query omits a
  scope filter** — isolation is enforced by the store. A test proving a foreign-tenant row leaks
  fails the build. *(FR-4; backend AC-3.)*
- **AC-5 — SA table completes the chain.** `analysis_results` exists and stores the full SA output
  contract; a walk `risk_assessments → analysis_results → validated_readings → raw_readings` resolves
  with no missing hop. *(FR-5/FR-8)*
- **AC-6 — Append-only raw + audit.** UPDATE and DELETE on `raw_readings` and `decision_log` are
  rejected for any role. *(FR-6)*
- **AC-7 — Correct-by-supersede.** An in-place edit to a verdict field on `validated_readings`,
  `analysis_results`, `risk_assessments`, `report_artifacts`, or `alert_dispatches` is rejected;
  a correction appends + links `superseded_by`; DELETE is blocked. *(FR-7)*
- **AC-8 — Version pinning.** A `report_artifacts`/`alert_dispatches` row records the exact
  `assessment_version` and remains reproducible after the assessment is superseded. *(FR-9)*
- **AC-9 — Idempotent current rows.** At most one current (non-superseded) row per natural key on each
  correct-by-supersede table; a redelivered write creates no duplicate. *(FR-10)*
- **AC-10 — Standard index, no TimescaleDB.** The `(sensor_id, sensor_time)` pattern is served by a
  standard B-tree composite index and the schema references no TimescaleDB/hypertable. *(FR-11/FR-13)*
- **AC-11 — Fast overview read model.** The current-risk-per-bridge overview for a municipality is
  served without scanning raw/historical rows. *(FR-12; backend AC-2.)*
- **AC-12 — Datastore consistency.** No migration header or constraint references Supabase or
  TimescaleDB as the datastore; all reflect Neon/Postgres standard-B-tree-only. *(FR-13)*

---

## Open Items

Behaviour is settled above. What remains is design pinning for `plan.md` (post-approval) and config a
human must supply — none to be guessed in a safety-critical system.

**Deferred to plan.md (design decisions, not spec behaviour):**
- **RLS mechanism:** native Postgres Row-Level Security policies keyed on the principal's
  `municipality_id`, vs. an enforced mandatory-scope pattern — and how the principal's municipality
  reaches the session (the auth spec's seam).
- **`sensors.config` shape** — what per-sensor config the SA/DCA registry needs stored here vs. in
  agent config (the DCA/SA "shared sensor registry/profiles" — SA §111).
- **Soft-ref vs hard-FK** for the provenance arrays (`source_raw_ids`, `source_validated_ids`,
  `source_analysis_ids`); tenancy FKs are already decided (hard).
- **`analysis_results` indexes** — its idempotency key `(sensor, calculation, block, input_version)`
  and any bridge/cycle + time-ordered lookup indexes.
- **`policy_version` on `alert_dispatches`** — whether to add an audit stamp for the AlertPolicy
  revision (research §4, currently absent).
- **Retention/archival** of superseded historical rows (default: indefinite).
- **Migration numbering for the new tables** — `analysis_results` is referenced as `0005` by existing
  headers; the tenancy tables need numbers (and, since bridges/sensors are referenced by existing
  bridge_id/sensor_id columns, an ordering/backfill approach for the already-built tables).

**Config a stakeholder supplies (placeholders until then — do not guess):**
- The actual municipalities, bridges, and sensor inventory (seed data / onboarding).

---

## Constitution Check (v2.1.0)

| Principle | How this spec complies |
|---|---|
| I — Safety First | Isolation and immutability are enforced at the store so a consumer bug cannot leak or corrupt safety data; no endpoint/action logic lives here (the `needs_approval` chokepoint is Alert 005). |
| II — Data Integrity | Raw append-only; derived correct-by-supersede; DELETE blocked; the unbroken provenance chain (FR-6/7/8) makes every number traceable to an immutable raw row. |
| III — Modularity / tenant-scoped | The ownership chain + store-enforced RLS (FR-1..FR-4) are the modular contract every agent and the API depend on; agents publish rows, the store guarantees isolation. |
| IV — Reliability over Cleverness | Deterministic storage guarantees over standard Postgres; no TimescaleDB cleverness — a plain composite index serves the time-series pattern (FR-11). |
| V — Testability | Every FR maps to an AC verifiable via in-memory fakes now and live constraints when a Neon instance exists (`[DB-DEP]`). |
| VI — Auditability | `decision_log` append-only across all agents; version pinning + supersede chains make every verdict reproducible (FR-7/FR-9). |
| VII — Tech Stack | Neon/Postgres, standard B-tree indexes only, no TimescaleDB; migration headers reconciled (FR-13). |
