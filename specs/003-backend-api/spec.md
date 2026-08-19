# Feature Specification: Backend API

**Feature Branch:** `003-backend-api`
**Created:** 2026-06-20
**Status:** Draft — awaiting clarifications
**Constitution:** v2.1.0 (`.specify/memory/constitution.md`)

> **Provenance note (reconciled 2026-07-27):** This spec was written from the detailed
> requirements in the request, originally against constitution v1.0.0. Two of its premises
> are now **superseded**: (a) `skills/bridgeguard-skills-README.md` **exists** — the
> `[SKILL-DEP]` markers below are historical and no longer blocking; (b) the datastore is
> **Neon/Postgres with standard B-tree indexes only — no TimescaleDB** (constitution v2.1.0),
> and Spec 002 (Database Layer) is **built**, so `[DB-DEP]` markers now resolve against the
> as-built schema. Where this spec and `specs/api/spec.md` overlap, the newer API spec governs.

## Dependencies (must exist for this API to fully satisfy its ACs)

| Dependency | Status | Affected ACs / stories |
|------------|--------|------------------------|
| **Spec 002 — Database Layer** (tables, indexes, RLS, retention) | **BUILT** (Neon/Postgres, standard B-tree only) | AC-2 (<500ms overview), AC-3 (RLS isolation), US-2/3/4/5 |
| **Spec 001 — Data Collection Agent** | spec+plan+tasks exist; T001 implemented | US-1 (ingestion triggers the pipeline) |
| Skills pipeline contracts (README) | **EXISTS** (`skills/bridgeguard-skills-README.md`) | [SKILL-DEP] markers below are historical |
| Auth/authz (tenancy, tokens) | **separate spec (out of scope here)** | AC-3, US-5/6 — this spec assumes its existence, defers its design |

## Summary

A REST API (FastAPI assumed — see Open Q-1) that is the single boundary between the
BridgeGuard agent/skill pipeline and the outside world. It (a) receives batched
sensor data forwarded from the MQTT/LoRaWAN Raspberry Pi gateway and triggers the
Data Collection Agent, (b) serves the dashboard live risk scores, sensor
time-series, and chart data, (c) issues and serves PDF reports asynchronously, and
(d) exposes alert/notification status. Every call is authenticated; every write is
audit-logged; municipality-scoped reads are row-level isolated.

## Constitution Alignment (Constitution Check)

| Principle | How this feature complies |
|-----------|---------------------------|
| I. Safety First | API serves recommendations/scores + their WHY (reasoning text from Risk agent); it exposes **no endpoint that triggers a physical action**. Any future actuation endpoint must gate on recorded human approval. |
| II. Data Integrity | Ingestion only ever **appends** raw readings; no endpoint can UPDATE/DELETE raw data. Reads expose lineage so an output traces to source. |
| III. Modularity | API is a thin transport/orchestration layer over the agents via their defined contracts; it does not reach into agent internals or reimplement their logic. |
| IV. Reliability over Cleverness | Deterministic request handling; **no raw stack traces to clients** — clean structured errors, every failure becomes a logged status (AC-6, AC-«errors»). |
| V. Testability | Each endpoint testable in isolation with a fake service layer; contract + auth + isolation tests defined in Testing section. |
| VI. Auditability | Every **write** operation logged with timestamp, principal (municipality/user), and the causing request (US-6). |
| VII. Tech Stack | Python (FastAPI) per constitution v2.1.0; consumes MQTT-forwarded data; persists via the **Neon/Postgres** database layer (standard B-tree indexes only — no TimescaleDB). |

## User Scenarios & Testing

### User Stories

1. **As the Pi gateway,** I need a single endpoint to push a batch of sensor
   readings, which then triggers the Data Collection Agent pipeline automatically.
2. **As the dashboard,** I need one fast call returning every (in-scope) bridge's
   current risk score and status, for the overview map/list.
3. **As the dashboard,** I need an endpoint returning time-series data for a
   specific sensor over a chosen date range, for the chart view.
4. **As an engineer,** I need to request a PDF report for a bridge + date range and
   get a download link back.
5. **As a municipality admin,** I need my API access scoped only to my own bridges —
   never another municipality's data.
6. **As the system,** I need every API call authenticated and every write logged for
   audit.

### Acceptance Criteria

- **AC-1 (Per-reading ingestion result):** The ingestion endpoint accepts a batch of
  MQTT-forwarded readings and returns a **per-reading** success/failure result, not
  just a per-batch status. A partially-bad batch reports exactly which readings
  failed and why.
- **AC-2 (Fast overview):** The overview endpoint responds in **under 500ms** even
  with hundreds of bridges. [DEPENDS ON Spec 002 indexing + a current-status read
  model; this API must not scan raw history to answer it.]
- **AC-3 (Auth + isolation):** All endpoints require authentication;
  municipality-scoped endpoints enforce row-level isolation — an authenticated
  principal for municipality A receives **zero** rows belonging to municipality B.
- **AC-4 (Async PDF):** The PDF report endpoint is asynchronous: it returns a **job
  ID immediately**, with a separate status endpoint and a download endpoint.
- **AC-5 (Auto OpenAPI):** Every endpoint is documented via auto-generated
  OpenAPI/Swagger.
- **AC-6 (No leaked internals):** The API never returns raw stack traces; errors are
  logged internally and returned as clean, structured error responses with a
  correlation id.

## Functional Requirements

### Ingestion

- **FR-1:** `POST /v1/ingest/readings` accepts a batch of readings forwarded from the
  MQTT/LoRaWAN gateway and returns a per-reading result array (AC-1).
- **FR-2:** Accepted readings are appended to raw storage (never overwriting) and the
  Data Collection Agent pipeline is triggered. [NEEDS CLARIFICATION Q-2: trigger
  **synchronously** within the request, or enqueue and process on the agent's cycle?
  The 001 plan runs validation on a 1–5 min scheduler, which argues for enqueue +
  ack, not synchronous validation.]
- **FR-3:** Gateway authentication is distinct from user/dashboard auth (a device
  credential). [NEEDS CLARIFICATION Q-3: device token, mTLS, or shared gateway key?]
- **FR-4:** Malformed readings in a batch do not fail the whole batch; each is
  individually accepted-or-rejected with a reason (ties to 001's `safe_parse`).

### Dashboard reads

- **FR-5:** `GET /v1/overview` returns current risk score + status band
  (Safe/Watch/Warning/Critical) for every in-scope bridge, in one call, <500ms
  (AC-2). Served from a current-status read model, not raw scans. [SKILL-DEP: status
  bands/score come from the Risk Reasoning agent; DB-DEP: read model from Spec 002.]
- **FR-6:** `GET /v1/sensors/{sensor_id}/timeseries?from=&to=` returns clean
  time-series for one sensor over a date range (US-3). Honors the "last 30/90/365
  days" fast-path. [DB-DEP.]
- **FR-7:** `GET /v1/bridges/{bridge_id}` returns a bridge's detail: sensors, current
  score + **reasoning text** (the WHY, Principle I), recent trend.
- **FR-8:** `GET /v1/sensors/{sensor_id}/charts` returns chart **data/metadata** for
  the visual-output skill's charts. [SKILL-DEP: chart payload shape; blobs live in
  object storage with URIs per prior decision.]
- **FR-9:** All read endpoints are municipality-scoped and return only in-scope rows
  (AC-3).

### Reports (async)

- **FR-10:** `POST /v1/reports` (bridge_id + date range) creates a report job and
  returns `{job_id, status: queued}` immediately (AC-4). [SKILL-DEP: pdf-report
  input contract.]
- **FR-11:** `GET /v1/reports/{job_id}` returns job status (queued/running/done/failed).
- **FR-12:** `GET /v1/reports/{job_id}/download` returns the finished PDF (or a signed
  object-storage URL). 404/409 if not ready.

### Alerts

- **FR-13:** `GET /v1/alerts` / `GET /v1/bridges/{id}/alerts` expose alert/
  notification **status** (read-only here; the Alert Agent owns sending). [SKILL-DEP.]

### Cross-cutting

- **FR-14:** Every endpoint requires authentication (AC-3). [Auth mechanism = separate
  spec; this API consumes its identity/tenant claims.]
- **FR-15:** Every **write** (ingest, report-create) is audit-logged with timestamp,
  principal, tenant, and the causing request (US-6, Principle VI).
- **FR-16:** A global exception handler converts any unhandled error into a clean
  structured response `{error, code, correlation_id}`, logs the full detail
  internally, and never leaks a stack trace (AC-6).
- **FR-17:** OpenAPI/Swagger auto-generated and served (AC-5).
- **FR-18:** Standard pagination + sane limits on all list/time-series endpoints to
  bound response size and latency.

## Key Entities (API-level views, not new storage)

- **ReadingBatch / ReadingResult** — ingestion input and the per-reading outcome.
- **OverviewItem** — bridge_id, name, current score, status band, last-updated.
- **TimeSeriesPoint** — timestamp, value, status, is_interpolated (from 001).
- **ReportJob** — job_id, bridge_id, range, status, download ref.
- **AlertStatus** — bridge/sensor, level, state, last-changed.
- **Principal** — authenticated identity + municipality scope (from auth spec).

## Out of Scope

- The actual AI/math logic (other agents/skills).
- Frontend rendering (next spec).
- **Auth/authz mechanism design** (separate spec) — this API assumes authenticated,
  tenant-scoped principals and enforces isolation, but does not define how tokens are
  issued.
- The database schema itself (Spec 002).

## Open Questions (resolve before `/sp.plan`)

- **Q-1 Framework:** FastAPI (async-native, auto-OpenAPI, fits AC-4/AC-5 best) vs
  Flask? Constitution allows either; I recommend **FastAPI**.
- **Q-2 Ingestion trigger:** synchronous validation in-request vs **enqueue + ack**
  (matches 001's 1–5 min cycle)? Recommend enqueue.
- **Q-3 Gateway auth:** device token / mTLS / shared key?
- **Q-4 Async infra:** background tasks for report jobs — in-process (FastAPI
  BackgroundTasks), or a real queue/worker (Celery/RQ/Arq)? Affects AC-4 reliability.
- **Q-5 Overview read model:** confirm a dedicated current-status table (Spec 002) is
  the source for AC-2, so this endpoint never scans raw history. *(No hypertables exist —
  Neon/Postgres, standard B-tree only per constitution v2.1.0.)*
- **Q-6 Versioning/SLA:** `/v1` prefix assumed; confirm. Any rate-limit on ingestion?
- **Q-7 [SKILL-DEP] payload shapes:** exact JSON for charts (FR-8), report contents
  (FR-10), and alert status (FR-13) await the skills README.

## Review Checklist

- [x] README supplied (`skills/bridgeguard-skills-README.md` exists) → [SKILL-DEP] markers
      are historical, no longer blocking.
- [x] Spec 002 (Database Layer) written **and built** → AC-2/AC-3 dependencies are real.
- [ ] Q-1…Q-6 answered.
- [ ] Auth spec cross-referenced for FR-14.
