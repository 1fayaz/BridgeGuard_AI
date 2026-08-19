# Implementation Plan: Backend API

**Feature:** `003-backend-api`
**Created:** 2026-06-20
**Status:** Draft — awaiting confirmation before task breakdown
**Spec:** `specs/003-backend-api/spec.md`
**Constitution:** v2.1.0

> Architecture and data-flow only. No implementation code here.
>
> **Both former blockers are now RESOLVED (2026-07-27):**
> 1. **Database Layer (Spec 002) is BUILT** — **Neon/Postgres, standard B-tree indexes
>    only, no TimescaleDB**, with the shape this plan assumed (denormalized
>    `municipality_id` + RLS; raw append-only; current-status read model). `[DB-DEP]`
>    markers below now resolve against the as-built schema. **Note:** the as-built GUC is
>    spelled **`app.current_municipality_id`** (see §6) — earlier drafts of this plan wrote
>    `app.municipality_id`.
> 2. **Skills README exists** (`skills/bridgeguard-skills-README.md`). `[SKILL-DEP]`
>    markers are historical, not blocking.
>
> Where this plan and `specs/api/spec.md` overlap, the newer API spec governs.

## 1. Framework & Project Structure

**Decision: FastAPI** (Python 3.11+). Rationale: native async (fits AC-4 async report
jobs), auto-generated OpenAPI/Swagger (satisfies AC-5 for free), Pydantic models give
per-field validation that maps cleanly onto AC-1's per-reading results, and dependency
injection makes the auth + tenant-scoping + audit concerns composable per route.

```
src/api/
  main.py                 # app factory, middleware, exception handlers, OpenAPI
  deps.py                 # DI: current principal, tenant scope, db session, audit
  security/
    auth.py               # JWT decode (users), API-key verify (gateway)
    tenancy.py            # sets Postgres RLS session var per request
  routers/
    ingest.py             # POST /sensors/ingest
    bridges.py            # overview, detail, risk-score, readings, alerts
    reports.py            # create / status / download
  schemas/                # Pydantic request/response models (the contract)
    ingest.py  bridges.py  reports.py  errors.py
  services/               # thin orchestration over agents + DB; NO business logic
    ingest_service.py     # append raw + enqueue Data Collection Agent
    query_service.py      # reads via DB layer (002)
    report_service.py     # enqueue PDF Report Agent, track job
  jobs/
    queue.py              # task queue wiring (see §4/§5)
    report_worker.py      # worker entrypoint for report generation
  audit.py                # write-operation audit log (Principle VI)
tests/api/
  ...                     # see §8
```

Boundary rule (Principle III): routers → services → (agents | DB layer). Routers hold
no domain logic; services call agents/DB only through their defined contracts. The API
never reimplements validation/math/risk logic.

## 2. Authentication Strategy

Two distinct principals (auth **mechanism** design is a separate spec; this plan
consumes it and enforces scope):

| Principal | Mechanism | Used by | Notes |
|-----------|-----------|---------|-------|
| Dashboard user / municipality admin | **JWT bearer** (short-lived access + refresh) | dashboard, engineers | Claims carry `municipality_id` + role. Drives RLS scope (§6). |
| Pi gateway (device) | **API key** (per-gateway, hashed at rest), sent as header | ingestion only | Scoped to one municipality's gateway; can only `POST /sensors/ingest`. Rotatable/revocable. |

- A FastAPI dependency resolves the principal on every route; missing/invalid →
  `401` structured error (AC-3, AC-6). Wrong scope/role → `403`.
- The gateway key is **write-only-to-ingest**; it can never read dashboard data.
- [DEFERRED to auth spec: token issuance, refresh, key provisioning UI.]

## 3. Endpoint List (method, path, request/response)

All paths under `/v1`. All responses use the shared error envelope on failure
(`{error, code, correlation_id}`, AC-6). All list/timeseries endpoints paginated.

> Your prompt listed paths without `/bridges` on ingest and a flatter reports path;
> I reconciled to one consistent tree. Flag if you want the exact strings you gave.

### 3.1 `POST /v1/sensors/ingest`  — gateway only
- **Req:** `{ readings: [{ sensor_id, sensor_type, value, unit, timestamp }] }` (batch).
- **Resp 207-style:** `{ batch_id, results: [{ index, sensor_id, accepted: bool, reason? }] }`
  — **per-reading** outcome (AC-1). Shape-valid readings → `accepted:true` (appended +
  enqueued); malformed → `accepted:false` + reason (ties to 001 `safe_parse`).
- **Semantics:** "accepted for processing," NOT "validated" — validation runs on the
  001 agent's 1–5 min cycle (see §4). [DB-DEP: append to raw_readings.]

### 3.2 `GET /v1/bridges/overview`  — dashboard
- **Req:** optional `?status=`, pagination. Tenant-scoped automatically.
- **Resp:** `{ items: [{ bridge_id, name, score (0-100), band (Safe|Watch|Warning|
  Critical), last_updated }], page }`. <500ms (AC-2). [DB-DEP: served from
  current-status read model, never a raw-history scan — no hypertables exist.]

### 3.3 `GET /v1/bridges/{bridge_id}/sensors/{sensor_id}/readings`
- **Req:** `?from=&to=` (or `?window=30d|90d|365d`), pagination.
- **Resp:** `{ sensor_id, points: [{ ts, value, status, is_interpolated }] }` (US-3).
  [DB-DEP: hits the standard `(sensor_id, sensor_time DESC)` composite B-tree index.]

### 3.4 `GET /v1/bridges/{bridge_id}/risk-score`
- **Resp:** `{ bridge_id, score, band, reasoning_text, scored_at, inputs_ref }` —
  includes the **WHY** (Principle I). [DB-DEP + SKILL-DEP: from Risk agent output.]

### 3.5 `POST /v1/bridges/{bridge_id}/reports`  — async
- **Req:** `{ from, to, options? }`. **Resp 202:** `{ job_id, status: "queued" }`
  immediately (AC-4). [SKILL-DEP: pdf-report inputs.]

### 3.6 `GET /v1/reports/{job_id}/status`
- **Resp:** `{ job_id, status: queued|running|done|failed, error?, ready: bool }`.

### 3.7 `GET /v1/reports/{job_id}/download`
- **Resp:** the PDF, or a **signed object-storage URL** (blobs in object storage per
  prior decision). `409` if not ready, `404` if unknown/out-of-scope.

### 3.8 `GET /v1/bridges/{bridge_id}/alerts`
- **Resp:** `{ items: [{ sensor_id?, level, state, last_changed }] }` — read-only
  status; Alert Agent owns sending. [SKILL-DEP.]

OpenAPI/Swagger auto-served at `/docs` + `/openapi.json` (AC-5).

## 4. Ingestion → Data Collection Agent

**Decision: enqueue + immediate ack** (not synchronous validation). Rationale: Agent
001's plan validates on a **1–5 min scheduled cycle**, not per-request; doing full
validation inside the HTTP call would contradict that design and couple gateway
latency to validation work.

Flow:
```
POST /sensors/ingest
  → shape-parse each reading (fast, deterministic)
  → APPEND valid-shape readings to raw_readings (never overwrite)   [DB-DEP]
  → enqueue a "raw arrived" signal (or rely on the 001 scheduler)
  → return per-reading accept/reject  (AC-1)
[separately] 001 scheduler tick → run_cycle() → validated_readings + validation_log
```
So the endpoint guarantees **durability of raw** + **per-reading shape result**;
validation status appears after the next cycle. [NEEDS CONFIRM Q-2: OK that ingest
returns "accepted," not "valid"?]

## 5. Reports → PDF Report Agent (async + job tracking)

**Decision: a real task queue + worker**, not in-process BackgroundTasks — so a job
survives an API restart and AC-4 is reliable. Recommend **Arq** (async-native, Redis,
fits FastAPI) or **RQ/Celery** if you prefer maturity.

```
POST /bridges/{id}/reports → create report_job row {queued} [DB-DEP] → enqueue → 202 {job_id}
worker: status=running → pull snapshot (§ below) → render PDF → upload to object storage
        → status=done + download ref   (or status=failed + error)
GET /reports/{job_id}/status  → reads job row
GET /reports/{job_id}/download → signed URL when done
```
**Consistent snapshot (spec US-6 / FR-12):** the worker reads the bridge's readings,
comparisons, risk score, and chart metadata for the range inside **one read
transaction (REPEATABLE READ)** so the report reflects a single point-in-time view.
[DB-DEP: requires 002's tables; SKILL-DEP: report contents.]

## 6. Multi-Tenant Row-Level Security

**Decision: Postgres RLS, driven by a per-request session variable** (matches the
shared-schema + `municipality_id` decision).

- On each authenticated request, a dependency runs `SET LOCAL app.current_municipality_id =
  <claim>` on the DB session/transaction. **(Corrected: the as-built GUC name is
  `app.current_municipality_id` — an earlier draft here said `app.municipality_id`, which
  would silently fail closed against the real policies.)**
- Every tenant table has an RLS policy `USING (municipality_id =
  current_setting('app.current_municipality_id', true))`. The tenant key is **TEXT**, not
  uuid, and the `true` (`missing_ok`) flag is load-bearing — an unset GUC yields NULL and
  reads **zero rows** (fail-closed). [Policies live in Spec 002, migration 0016 — BUILT.]
- Isolation is enforced **in the database**, not in application `WHERE` clauses — so a
  forgotten filter can't leak data (defense in depth for AC-3). App-side scoping is a
  secondary check, not the primary guarantee.
- The gateway API key also carries a `municipality_id`; ingestion writes are stamped
  with it.

## 7. Rate Limiting / Abuse Protection (public ingestion)

- **Token-bucket rate limit** on `/sensors/ingest`, keyed by gateway API key (e.g.
  `slowapi` or an API-gateway/Redis limiter). Generous steady-state + burst tuned to
  expected reading volume. `429` structured error on breach.
- **Batch size cap** (FR-18) — reject oversized batches with `413`.
- **Payload size limit** + request timeout to bound resource use.
- Auth required even on ingest (API key), so it is not anonymously public.
- All limits return clean structured errors, never stack traces (AC-6).
- [NEEDS CLARIFICATION Q: expected readings/min per gateway to size the bucket — ties
  to the volume question still open from Spec 002.]

## 8. Testing Plan

| # | Test | Asserts | Maps to |
|---|------|---------|---------|
| AT-1 | Ingest per-reading result | mixed good/bad batch → correct per-index accept/reject + reasons | AC-1 |
| AT-2 | Ingest appends, never overwrites | raw row count grows; no UPDATE/DELETE path exists | Principle II |
| AT-3 | Auth required | every endpoint sans creds → 401 structured error | AC-3 |
| AT-4 | Gateway key scope | gateway key cannot hit any read endpoint → 403 | §2 |
| AT-5 | **Tenant isolation** | principal A gets 0 rows of B's bridges/sensors/reports | AC-3, US-5 |
| AT-6 | RLS defense-in-depth | even a query missing app-side filter returns only in-scope rows | §6 |
| AT-7 | **Overview load test** | <500ms at hundreds of bridges (against 002 read model) | AC-2 |
| AT-8 | **Async report flow** | POST→202 job_id; status transitions queued→running→done; download works; restart mid-job doesn't lose it | AC-4 |
| AT-9 | Report not-ready | download before done → 409; unknown job → 404 | FR-12 |
| AT-10 | No leaked internals | forced internal error → structured `{error,code,correlation_id}`, full detail only in logs | AC-6 |
| AT-11 | Audit on writes | ingest + report-create each produce an audit row (ts, principal, tenant, request) | AC-«VI», US-6 |
| AT-12 | OpenAPI present | `/openapi.json` documents every route | AC-5 |

Test doubles: fake service layer + fake queue for router unit tests; a real
Postgres+RLS instance for AT-5/AT-6 (isolation can only be proven against real RLS);
the overview load test (AT-7) needs the 002 read model + seed data (`db/seed/seed_dev.sql`
provides a two-municipality world). **Spec 002 now exists; these DB-backed tests remain
`[DB-DEP]` only because there is no live Neon instance locally** — in-memory fakes mirror
the same guarantees until one exists.

## Constitution Re-Check (post-design)

| Principle | Status |
|-----------|--------|
| I. Safety First | PASS — serves scores + WHY; no physical-action endpoint |
| II. Data Integrity | PASS — ingest appends only; no raw mutation path |
| III. Modularity | PASS — routers→services→agents/DB via contracts; no logic duplication |
| IV. Reliability | PASS — structured errors, no stack traces, deterministic handling |
| V. Testability | PASS — 12 tests incl. isolation + async flow |
| VI. Auditability | PASS — write-ops audit-logged with principal + request |
| VII. Tech Stack | PASS — FastAPI/Python; MQTT-forwarded ingest; **Neon/Postgres** via 002 (standard B-tree only, no TimescaleDB) |

## Open Questions To Confirm Before Tasks

- **Q-1 Path scheme:** I normalized your endpoint paths under `/v1` with a consistent
  `/bridges/...` tree (e.g. `POST /v1/sensors/ingest`, `POST /v1/bridges/{id}/reports`,
  `GET /v1/reports/{job_id}/status`). Keep this, or use the exact strings from your prompt?
- **Q-2 Ingest semantics:** confirm "accepted for processing" (enqueue + ack), not
  synchronous validation — consistent with 001's scheduled cycle.
- **Q-3 Queue choice:** Arq (async, recommended) vs RQ vs Celery for both ingest signal
  and report jobs?
- **Q-4 Gateway auth:** **RESOLVED 2026-07-27** — **per-device API key** (one key per physical
  Pi, stored in the Pi's `.env`, never in code), resolving to exactly one
  `bridge_id` + `municipality_id`. Not mTLS.
- **Q-5 Rate budget:** expected readings/min per gateway (to size the limiter) — still
  a config TODO; do not guess.
- **Q-6 RESOLVED:** Spec 002 (Database Layer) is **written and built**; this API is no
  longer blocked on it.
```
