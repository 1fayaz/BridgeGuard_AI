# Tasks: Backend API

**Feature:** `003-backend-api`
**Created:** 2026-06-20
**Status:** Draft — awaiting review before implementation
**Plan:** `specs/003-backend-api/plan.md`
**Spec:** `specs/003-backend-api/spec.md`
**Constitution:** v2.1.0

## Conventions

- **[P]** = parallelizable once its phase's prerequisites are met.
- Each task < 1 hour, one clear **Done** condition.
- **[DB-DEP]** = requires Spec 002 (Database Layer), which is now **BUILT**
  (**Neon/Postgres, standard B-tree indexes only — no TimescaleDB**). Tasks so marked can be
  **built against a fake/in-memory repository** now, but their real Done condition (against a
  live Neon instance with RLS) **cannot be verified** until an instance is available (none
  locally). I will not mark these fully done until they run for real.
- **[SKILL-DEP]** = historical marker. The skills README
  (`skills/bridgeguard-skills-README.md`) **exists**; these response shapes are now
  reconcilable against it rather than assumed.
- All routers→services→agents/DB via contracts (Principle III). No domain logic in
  routers. All errors via the structured envelope (AC-6). All writes audited (AC-6/VI).

---

## Phase 1 — Project Scaffolding

- **T001 — FastAPI app factory + structure.**
  Create `src/api/` tree per plan §1 (`main.py`, `deps.py`, `routers/`, `schemas/`,
  `services/`, `security/`, `jobs/`, `audit.py`). `main.py` builds the app, mounts an
  empty router set, serves `/docs`.
  **Done:** `uvicorn api.main:app` starts; `GET /docs` + `/openapi.json` load; health
  route `GET /v1/health` returns 200.

- **T002 — [P] Structured error envelope + global exception handler.**
  `schemas/errors.py` (`{error, code, correlation_id}`); handler converts any
  unhandled exception → envelope + logs full detail internally; never leaks a trace.
  **Done:** a route that raises → client gets clean envelope w/ correlation_id, full
  detail only in logs (AC-6). Unit test asserts no stack trace in body.

- **T003 — [P] Shared response/pagination models + settings.**
  `schemas/` base models, pagination params, env-based settings (DB URL, queue URL,
  JWT secret, gateway-key store) loaded but not yet wired.
  **Done:** models import; settings load from env with sane defaults; test green.

---

## Phase 2 — Authentication & Tenancy Middleware

- **T101 — JWT user auth dependency.**
  `security/auth.py`: decode/verify bearer JWT, extract `municipality_id` + role;
  invalid/missing → 401 envelope.
  **Done:** unit test — valid token resolves principal; missing/expired/garbage → 401.

- **T102 — Gateway API-key auth dependency.**
  Verify per-gateway hashed API key from header; resolves a device principal scoped to
  ingest + one municipality.
  **Done:** unit test — valid key → device principal; bad key → 401; device principal
  rejected on a read route → 403.

- **T103 — Tenant-scope dependency (RLS session var). [DB-DEP]**
  On each authed request, `SET LOCAL app.municipality_id = <claim>` on the DB session.
  **Done (fake):** against a fake session, the var is set from the principal.
  **Done (real, deferred):** against Postgres, RLS policies observe it (verified in
  T1302 once 002 exists).

- **T104 — [P] Audit-write helper.**
  `audit.py`: `record_write(principal, tenant, request_summary, ts)`.
  **Done:** unit test — calling it produces one audit entry with all fields (VI).

---

## Phase 3 — Sensor Ingestion (US-1, AC-1)

- **T201 — Ingest request/response schemas.**
  `schemas/ingest.py`: batch in; `results: [{index, sensor_id, accepted, reason?}]` out.
  **Done:** Pydantic models validate a sample batch; per-reading result shape matches
  plan §3.1.

- **T202 — Shape-parse + per-reading result logic.**
  Reuse Agent 001 `safe_parse` semantics; each reading individually accepted/rejected;
  malformed never fails the batch.
  **Done:** unit test — mixed good/bad batch → correct per-index accept/reject + reason
  (AC-1); no exception escapes.

- **T203 — Append raw + enqueue signal. [DB-DEP]**
  `ingest_service`: append shape-valid readings to `raw_readings` (never overwrite),
  enqueue "raw arrived" (or rely on 001 scheduler), audit the write.
  **Done (fake):** fake repo records appends; no update/delete path; audit row written.
  **Done (real, deferred):** rows land in the `raw_readings` table (plain Postgres,
  append-only — no hypertable); needs a live Neon instance.

- **T204 — `POST /v1/sensors/ingest` route (gateway-only).**
  Wire T102 auth + T202 + T203; returns per-reading results.
  **Done:** route test with fake service — gateway key required; per-reading results
  returned; returns "accepted," not "validated" (plan §4, Q-2).

---

## Phase 4 — Dashboard Read Endpoints

- **T301 — Overview endpoint `GET /v1/bridges/overview`. [DB-DEP]**
  Serve current score + band per in-scope bridge from the current-status read model
  (NOT a raw-history scan; no hypertables exist). Tenant-scoped + paginated.
  **Done (fake):** returns OverviewItems for fake tenant data; another tenant's bridges
  absent. **Done (real, deferred):** <500ms at scale verified in T1401.

- **T302 — [P] Overview caching (only if needed).**
  Add a short-TTL cache layer behind the read model **only if** the read model alone
  misses 500ms. Document the decision; don't cache speculatively.
  **Done:** either a benchmarked justification to skip caching, or a cache with a clear
  invalidation rule on new score. (Decision recorded; revisit after T1401.)

- **T303 — Sensor time-series `GET /v1/bridges/{id}/sensors/{sid}/readings`. [DB-DEP]**
  `?from=&to=` or `?window=30d|90d|365d`; paginated; uses the last-N-days index.
  **Done (fake):** returns points {ts,value,status,is_interpolated} for fake data, tenant
  scoped. **Done (real, deferred):** index used (EXPLAIN) once 002 exists.

- **T304 — [P] Risk-score `GET /v1/bridges/{id}/risk-score`. [DB-DEP][SKILL-DEP]**
  Returns score, band, **reasoning_text** (WHY, Principle I), scored_at, inputs_ref.
  **Done (fake):** returns the shape incl. reasoning_text; tenant scoped.

---

## Phase 5 — Reports (async)

- **T401 — Report job schemas + `report_job` repo. [DB-DEP]**
  Job states queued/running/done/failed; create + read.
  **Done (fake):** create job → row {queued}; status transitions persist in fake repo.

- **T402 — Task queue wiring (`jobs/queue.py`).**
  Wire Arq (or chosen lib) + a worker entrypoint; a no-op job round-trips.
  **Done:** enqueue a test job → worker picks it up → marks done. (Local Redis or a
  fakeredis double.)

- **T403 — `POST /v1/bridges/{id}/reports` (202 + job_id). [DB-DEP][SKILL-DEP]**
  Create job, enqueue, return `{job_id, status: queued}` immediately; audit the write.
  **Done:** route test — returns 202 + job_id instantly; audit row written (AC-4).

- **T404 — Report worker: snapshot + render. [DB-DEP][SKILL-DEP]**
  Worker reads the bridge snapshot in one REPEATABLE READ txn, renders PDF, uploads to
  object storage, sets done + download ref (or failed + error).
  **Done (fake):** worker transitions running→done against fake snapshot, produces a
  placeholder artifact ref. **Done (real, deferred):** consistent snapshot needs 002 +
  pdf-report contract.

- **T405 — `GET /v1/reports/{job_id}/status`.**
  **Done:** returns current state; unknown/out-of-scope job → 404.

- **T406 — `GET /v1/reports/{job_id}/download`.**
  **Done:** done → PDF or signed URL; not ready → 409; unknown → 404 (FR-12).

---

## Phase 6 — Alerts

- **T501 — `GET /v1/bridges/{id}/alerts`. [DB-DEP][SKILL-DEP]**
  Read-only alert/notification status; tenant scoped.
  **Done (fake):** returns alert items for fake data; Alert Agent ownership of *sending*
  documented as out of scope here.

---

## Phase 7 — Cross-cutting Hardening

- **T601 — Apply tenant scoping to ALL read routes.**
  Audit every read route uses the T103 scope dependency; add the secondary app-side
  filter as defense in depth.
  **Done:** every read route declares the scope dep; review checklist complete.

- **T602 — Rate limiting on `/sensors/ingest`.**
  Token-bucket keyed by gateway API key; batch-size cap (413); payload cap; 429 envelope
  on breach.
  **Done:** unit test — exceeding the bucket → 429 envelope; oversize batch → 413. (Bucket
  size uses a placeholder until Q-5 volume number is given.)

- **T603 — [P] Audit wired on all write ops.**
  Ingest + report-create both call the T104 audit helper.
  **Done:** test — each write produces an audit entry (ts, principal, tenant, request).

---

## Phase 8 — Docs & Tests

- **T701 — OpenAPI verification.**
  **Done:** `/openapi.json` documents every route with request/response schemas; a test
  asserts each registered path is present (AC-5).

- **T702 — Auth test suite.**
  No-creds → 401 on every endpoint; gateway key → 403 on reads; user token → 403 on
  ingest.
  **Done:** suite green (AC-3, §2).

- **T703 — Tenant isolation test suite. [DB-DEP]**
  Principal A receives **0** rows of B's bridges/sensors/reports/alerts.
  **Done (fake):** passes against fake multi-tenant data. **Done (real, deferred):**
  T1302 proves it against real Postgres RLS.

- **T1302 — RLS isolation against real Postgres. [DB-DEP, BLOCKED on a live Neon instance]**
  With real RLS policies (from 002, migration 0016 — now BUILT), a query **missing** its
  app-side filter still returns only in-scope rows (defense in depth, §6).
  **Done:** cannot run until a live Neon instance is available. Explicitly blocked; not
  counted as passing until executed.

- **T1401 — Overview load test. [DB-DEP, BLOCKED on a live Neon instance]**
  Seed hundreds of bridges; assert overview p95 < 500ms against the read model (AC-2).
  **Done:** 002's schema + seed data exist; blocked only on a live **Neon** instance.

- **T704 — Async report flow test.**
  POST→202 job_id; status queued→running→done; download works; **job survives a worker
  restart** mid-flight.
  **Done:** suite green against the real queue (or fakeredis) (AC-4, AT-8).

- **T705 — [P] Error-handling test.**
  Forced internal error → structured envelope + correlation_id; full detail only in
  logs; no stack trace in body (AC-6).
  **Done:** test green.

---

## Dependency Order

```
Phase 1 ─► Phase 2 ─► Phase 3 (ingest) ──┐
                   └─► Phase 4 (reads)    ├─► Phase 7 (hardening) ─► Phase 8 (docs/tests)
                   └─► Phase 5 (reports)  │
                   └─► Phase 6 (alerts) ──┘
```
- Phases 3–6 are largely parallel once auth/tenancy (Phase 2) lands.
- **Real verification of every [DB-DEP] task, and all of T1302/T1401, is gated on a live
  Neon instance** (Spec 002 itself is built). Until then those are buildable against fakes only.

## Coverage Check (tasks ↔ acceptance criteria)

| AC | Task(s) |
|----|---------|
| AC-1 per-reading ingest | T201, T202, T204 |
| AC-2 <500ms overview | T301, T302, **T1401 (blocked)** |
| AC-3 auth + isolation | T101–T103, T601, T702, T703, **T1302 (blocked)** |
| AC-4 async PDF | T401–T406, T704 |
| AC-5 OpenAPI | T001, T701 |
| AC-6 clean errors | T002, T705 |
| Principle II append-only | T203 |
| Principle VI audit | T104, T603 |

## Blockers & Open Items (must resolve before/within implementation)

- **RESOLVED — Spec 002 (Database Layer) is written and BUILT** (Neon/Postgres, standard
  B-tree only, no TimescaleDB). [DB-DEP] tasks still build against fakes, but only because
  no live instance exists locally.
- **No local Neon/Postgres instance** — DB-backed tests need one before T1302/T1401 can run.
- **RESOLVED — skills README exists** (`skills/bridgeguard-skills-README.md`); [SKILL-DEP]
  response shapes (risk reasoning, report contents, alerts) can now be reconciled against it.
- **RESOLVED — Q-4 gateway auth:** per-device API key (one per physical Pi, in the Pi's
  `.env`, never in code) resolving to one `bridge_id` + `municipality_id`.
- Carried: Q-1 paths, Q-2 ingest semantics, Q-3 queue lib, Q-5 rate budget (config TODO).
```
