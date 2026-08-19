# API Layer — Specification

**Status:** Draft — behaviour only. Awaiting review before `plan.md`.
**Date:** 2026-07-27
**Constitution:** v2.1.0 (`.specify/memory/constitution.md`)
**Anchors:** `CLAUDE.md`; `specs/api/research-api.md` (research); `specs/database/spec.md` +
`db/migrations/RLS.md` (the tenancy contract this API must honour); `specs/003-backend-api/spec.md`
(predecessor — this spec supersedes/extends it); `specs/004-dashboard-frontend/spec.md` (consumer);
the five agent specs (DCA 001, SA 002, Risk 003, Report 004, Alert 005).

> **Behaviour only.** WHAT each endpoint does and WHY. No framework code, no route decorators,
> no SQL, no library choices, no file layout — those are `plan.md` decisions. Paths below are
> **contract names**, not routing syntax.

---

## Goal

The API is the **single external boundary** of the BridgeGuard system. Every agent reads and writes
the database **directly**; the API does not sit between agents and their data, and it does not
orchestrate the pipeline. It exists **only to serve external consumers**:

| Consumer | What it needs from the API |
|---|---|
| **Pi gateway** | push batches of sensor readings inward |
| **Dashboard** (frontend) | bridge overview, bridge detail, time-series, risk, alerts, report flow |
| **n8n** | invoke an agent cycle after the previous stage completes |
| **Government engineers** | download finished PDF reports; acknowledge alerts |

Three consequences of "boundary, not orchestrator":

- **The API re-implements no agent logic** (Principle III). It does not validate readings, compute
  RMS/FFT, score risk, render PDFs, or dispatch notifications. It accepts, reads, enqueues, and
  triggers.
- **The API takes no real-world action** (Principle I). It exposes **no** endpoint that notifies an
  authority, recommends a closure, or dispatches an alert — that is the Alert Agent's single
  `needs_approval`-gated chokepoint. The API's only alert *write* is recording a human's
  acknowledgement, which is an audit fact, not an outbound action.
- **Raw data is append-only through the API** (Principle II). Ingestion appends; no endpoint can
  UPDATE or DELETE a raw reading, a validated reading, an assessment, a report, or a dispatch record.

---

## Cross-cutting invariants (bind every endpoint below)

- **INV-1 — Tenant scope is set before any query, always.** Every authenticated request resolves
  exactly one `municipality_id` from its credential and sets the session GUC
  **`app.current_municipality_id`** (transaction-local) **before any database query runs**. This is
  **non-negotiable**: it is the mechanism that makes Postgres RLS enforce isolation. A request that
  queries before setting the scope is a defect, not a degraded case. An unset scope reads **zero
  rows** (fail-closed) — never all rows.
- **INV-2 — Isolation is the database's job, not a `WHERE` clause.** The API never relies on
  application-side filtering as the primary guarantee. Even a query that forgot its filter must
  return only in-scope rows, because RLS is `ENABLE`d **and** `FORCE`d and the connection role is
  `bridgeguard_service` (never a superuser, never `BYPASSRLS`).
- **INV-3 — A supplied id is never a grant.** Possessing a valid `bridge_id` confers nothing. If the
  id belongs to another municipality, RLS yields zero rows and the API reports **404** (not 403) —
  revealing "this exists but isn't yours" is itself a tenancy leak.
- **INV-4 — No stack trace ever leaves the boundary.** Every failure becomes a structured JSON error
  with a correlation id; full detail is logged internally only.
- **INV-5 — Every write is audited.** Ingestion, report requests, and alert acknowledgements each
  record timestamp, principal, tenant, and the causing request (Principle VI).
- **INV-6 — Reads are traceable.** Any number the API returns traces to a persisted row an agent
  wrote. The API computes no derived value of its own (Principle II).
- **INV-7 — A risk score is never served without its WHY.** Any response carrying a risk score also
  carries the Risk Agent's **verbatim** explanation. A score without its explanation is a defect
  (Principle I). The API never summarises, paraphrases, or truncates that text.

---

## Authentication

Three credential shapes, three trust levels. **Token issuance is a separate auth spec** — this API
*consumes* credentials and enforces scope; it does not mint them.

### A. Municipality-scoped JWT — engineers / dashboard

- Bearer JWT carrying a **`municipality_id`** tenant claim (plus identity/role for audit).
- Resolves to **exactly one** `municipality_id` → set as `app.current_municipality_id` (INV-1).
- Used by every dashboard/engineer endpoint (2–10 below).
- Cannot reach ingestion or internal trigger endpoints.

### B. Per-device API key — Pi gateway

- **One key per physical Pi.** Stored in that Pi's `.env` — **never in code**, never committed.
- The key resolves, **at the database layer**, to **exactly one `bridge_id` + `municipality_id`**.
  That resolved `municipality_id` is set as `app.current_municipality_id` (INV-1) — the **same RLS
  enforcement path** as the JWT. Only the credential *shape* differs; the isolation *mechanism* is
  identical.
- Because the key pins a `bridge_id`, a Pi can only append readings for **its own bridge's** sensors.
  A reading naming a sensor outside that bridge is rejected per-reading (see endpoint 1).
- **Write-to-ingest only.** The key can reach no read endpoint, no report endpoint, no trigger.
- Rotatable and revocable per device without affecting other Pis.
- The key → (`bridge_id`, `municipality_id`) mapping lives in a **`device_credentials` table owned
  by this layer** (confirmed 2026-07-27). Keys are stored **hashed**, never in plaintext.

### C. Internal shared secret — n8n

- Used **only** for the internal trigger endpoints (11). **Never exposed publicly** — network-
  restricted in addition to the secret (defense in depth; a leaked secret must not be sufficient).
- A trigger carries the tenant scope for the cycle it invokes, set per INV-1 like any other request.
- Cannot reach any consumer-facing endpoint.

**No endpoint is unauthenticated.** There is no anonymous surface — with one documented
carve-out.

> **Carve-out: `GET /v1/health`** (P101 Finding 5, resolved 2026-07-31). A liveness probe must be
> reachable without a credential, or an unhealthy process cannot be detected. It is bounded to stay
> harmless: it returns a literal `{"status": "ok"}`, touches **no database, no queue, and no
> storage**, and discloses **no** version, build, hostname, dependency status, or tenant data. It is
> the only anonymous route, and P1007 asserts that it stays the only one — so it cannot quietly grow
> a DB touch or a build-version disclosure later.

---

## Endpoints

Contract names, not routes. Field lists are the **contract**; exact JSON casing is `plan.md`.

### 1. `POST /ingest` — sensor reading batch

- **Purpose:** Accept a batch of sensor readings from a Pi and durably append them as raw data.
- **Who calls it:** **Pi gateway.**
- **Auth:** **Pi API key** (B). Resolves to one `bridge_id` + `municipality_id`.
- **Sync/async:** **Sync ack, async processing.** The call blocks only long enough to shape-check
  and append; it returns "accepted for processing," **not** "validated." Validation is the Data
  Collection Agent's job on its own 1–5 minute cycle. The API **never** runs validation in-request.
- **Input:** `{ readings: [ { sensor_id: string, sensor_type: string, value: number, unit: string,
  sensor_time: timestamp } ] }` — a batch.
- **Output:** `{ batch_id: string, accepted_count: int, rejected_count: int,
  results: [ { index: int, sensor_id: string, accepted: bool, reason?: string } ] }`
  — **one result per reading** (AC-1), positionally indexed.
- **Behaviour:**
  - **Per-reading outcome, never batch-level pass/fail.** One malformed reading does not reject the
    batch; each reading is independently accepted or rejected **with a reason**.
  - Accepted readings are **appended** to raw storage. No path updates or deletes raw data.
  - A reading whose `sensor_id` does not belong to the API key's `bridge_id` is **rejected**
    (per-reading, with a reason) — not silently re-attributed.
  - Rejection reasons are a **closed, documented set** (e.g. unknown sensor, sensor not on this
    bridge, malformed timestamp, missing/non-numeric value, unit mismatch) so the gateway can act
    on them programmatically.
  - **Duplicate/redelivered readings** are tolerated — the Pi may retry after a network failure.
    A redelivered reading is not a failure to report to the caller.

### 2. `GET /bridges` — overview of all bridges + current risk status

- **Purpose:** One fast call returning every in-scope bridge with its current risk band, for the
  overview screen.
- **Who calls it:** **Dashboard.**
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync**, fast. Target **under 500 ms**.
- **Input:** optional filter by band, optional sort, pagination.
- **Output:** `{ items: [ { bridge_id: string, name: string, risk_score: int|null,
  severity: "SAFE"|"WATCH"|"WARNING"|"CRITICAL"|null, review_status: string,
  last_assessed_at: timestamp|null } ], page: {...} }`
- **Behaviour:**
  - Served from **current-state reads** (current, non-superseded assessments) — never a scan of raw
    reading history.
  - Severity bands are the **fixed** `SAFE 0–30 / WATCH 31–60 / WARNING 61–80 / CRITICAL 81–100`
    set, consumed from the assessment — **never recomputed here**.
  - A bridge with **no assessment yet**, or whose assessment **withheld its score**, returns
    `risk_score: null` with an honest status — never a fabricated `0` and never "all clear."
  - Returns only in-scope bridges (INV-1/2). An empty result is a valid answer, not an error.

### 3. `GET /bridges/{id}` — bridge detail + sensor list

- **Purpose:** One bridge's identifying detail and the sensors installed on it.
- **Who calls it:** **Dashboard.**
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync.**
- **Input:** `bridge_id` (path).
- **Output:** `{ bridge_id, name, location?, current_risk: { risk_score, severity,
  explanation, review_status, assessed_at } | null, sensors: [ { sensor_id, sensor_type, unit,
  status, last_reading_at } ] }`
- **Behaviour:**
  - If `current_risk` is present it carries the **verbatim explanation** (INV-7).
  - Per-sensor `status` surfaces liveness (e.g. offline / no-data) as the DCA recorded it — the API
    does not infer it.
  - Out-of-scope or unknown `bridge_id` → **404** (INV-3).

### 4. `GET /bridges/{id}/sensors/{sid}/readings` — time-series

- **Purpose:** Time-series points for one sensor over a range, for charting.
- **Who calls it:** **Dashboard.**
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync**, bounded.
- **Input:** `bridge_id`, `sensor_id` (path); `from`/`to` timestamps **or** a window
  (`30d`/`90d`/`365d`); pagination/limit.
- **Output:** `{ sensor_id, sensor_type, unit, window: {from, to},
  points: [ { sensor_time: timestamp, value: number, status: string, is_interpolated: bool } ],
  page: {...} }`
- **Behaviour:**
  - Returns **validated** readings, and marks **interpolated** points and **gaps** explicitly —
    data quality is never silently smoothed away (Principle II transparency).
  - Every list response is **paginated with an enforced maximum**, so no request can return an
    unbounded series.
  - A sensor not on the named bridge, or out of scope → **404**.

### 5. `GET /bridges/{id}/risk` — current risk assessment

- **Purpose:** The bridge's current risk verdict **with its written WHY**.
- **Who calls it:** **Dashboard** (and engineers).
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync.**
- **Input:** `bridge_id` (path).
- **Output:** `{ bridge_id, risk_score: int|null, severity: string|null,
  recommendation: string, explanation: string, contributing_factors: [...],
  confidence: number, data_completeness: number, review_status: "FINAL"|"PENDING_HUMAN_REVIEW",
  assessed_at: timestamp, assessment_version: int,
  provenance: { source_analysis_ids: [...], standard_code, standard_version, trace_id } }`
- **Behaviour:**
  - Serves the **current** (non-superseded) assessment, and states which `assessment_version` it is.
  - **`explanation` is returned verbatim** — never summarised or truncated (INV-7).
  - **`review_status` is always surfaced.** A `PENDING_HUMAN_REVIEW` verdict must be presented as
    unsettled; the API never launders a pending verdict into a settled one.
  - A **withheld** assessment returns `risk_score: null` plus the verbatim withheld reason — never
    a fabricated number.
  - No assessment yet → an explicit "not yet assessed" state, not a 404 for the bridge itself.

### 6. `POST /bridges/{id}/reports` — request a PDF report

- **Purpose:** Request a report for a bridge; returns a job handle immediately.
- **Who calls it:** **Dashboard / engineer.**
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **ASYNC — returns a `job_id`.** Rendering takes **5–30 seconds** (Report Agent
  FR-12, fire-and-notify), so the request must never block on it.
- **Input:** `bridge_id` (path); optional `{ from, to }` range; optional assessment identity for a
  **historical reprint**.
- **Output:** `{ job_id: string, status: "PENDING", bridge_id, requested_at: timestamp }` —
  returned **within 500 ms** regardless of how long rendering takes.
- **Behaviour:**
  - The API **enqueues**; the Report Agent renders. The API does not assemble the PDF.
  - Requesting a report is **not** publication — nothing is emailed, submitted, or dispatched
    (Report Agent FR-13).
  - A request for an already-rendered current assessment may return the **existing** job/artifact
    rather than duplicating work (the agent is idempotent per assessment version).
  - Audited as a write (INV-5).

### 7. `GET /reports/{job_id}/status` — poll report job

- **Purpose:** Report progress for a requested job.
- **Who calls it:** **Dashboard** (polling) / engineer.
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync**, cheap — designed to be polled.
- **Input:** `job_id` (path).
- **Output:** `{ job_id, status: "PENDING"|"RUNNING"|"COMPLETE"|"FAILED",
  bridge_id, requested_at, completed_at?, document_marks?: [...],
  error?: { code: string, detail: string } }`
- **Behaviour:**
  - Status is exactly one of the **four** values — a closed set.
  - **`FAILED` carries a structured reason** (`code` + human-readable `detail`) — **never a stack
    trace** (INV-4). Reasons map to the agent's outcome vocabulary (e.g. assessment not found,
    provenance mismatch).
  - A `COMPLETE` job may carry the agent's **document marks** (e.g. not-final, score-withheld,
    historical, section-unavailable) so the consumer can warn the reader before download.
  - A `job_id` belonging to another municipality → **404** (INV-3).

### 8. `GET /reports/{job_id}/download` — download completed report

- **Purpose:** Retrieve the finished PDF.
- **Who calls it:** **Engineer** (and dashboard).
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync.**
- **Input:** `job_id` (path).
- **Output:** the PDF document, or a short-lived signed reference to it.
- **Behaviour:**
  - **Only works when `status = COMPLETE`.** `PENDING`/`RUNNING` → **409** (not-ready, retry);
    `FAILED` → **409** with the structured failure reason. A partially-rendered document is
    **never** downloadable.
  - Unknown or out-of-scope `job_id` → **404**.
  - The artifact is **immutable**: the same `job_id` always yields the same document. A re-render
    produces a **new** job/version; it never overwrites this one.
  - Audited as an access event.

### 9. `GET /bridges/{id}/alerts` — active alerts for a bridge

- **Purpose:** The alert/escalation status for one bridge, so an engineer can see what is
  outstanding.
- **Who calls it:** **Dashboard / engineer.**
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync.**
- **Input:** `bridge_id` (path); optional filter by severity or state; pagination.
- **Output:** `{ items: [ { alert_id, bridge_id, severity, dispatch_decision,
  delivery_state, escalation_state, approval_state?, raised_at, acknowledged_at?,
  acknowledged_by?, assessment_id, assessment_version } ], page: {...} }`
- **Behaviour:**
  - **Read-only status.** The API never dispatches, retries, or escalates — the Alert Agent owns all
    outbound action behind its `needs_approval` gate.
  - **An unacknowledged alert stays visible.** An alert whose escalation is still `OPEN`/`ESCALATED`
    appears on **every** call until it is explicitly acknowledged (AC-4). Delivery does **not**
    remove a WARNING/CRITICAL alert from this list — only a recorded acknowledgement does.
  - Reflects the agent's distinct states honestly: `SENT` ≠ `DELIVERED` ≠ `ACKNOWLEDGED`.
- **Also required (surfaced by research):** a **municipality-wide** variant — the same contract
  without a `bridge_id`, listing every in-scope bridge's alerts, sortable by severity and bridge.
  The dashboard's alerts screen is cross-bridge; a per-bridge-only surface would force N calls.

### 10. `POST /alerts/{id}/acknowledge` — engineer acknowledges an alert

- **Purpose:** Record that a named human has seen and taken responsibility for an alert — the
  acknowledgement that closes a WARNING/CRITICAL escalation.
- **Who calls it:** **Engineer** (via dashboard).
- **Auth:** **Municipality-scoped JWT** (A) — the acknowledging identity comes from the credential,
  **never** from the request body (an ack must be attributable and unforgeable).
- **Sync/async:** **Sync.**
- **Input:** `alert_id` (path); optional `{ note: string }`.
- **Output:** `{ alert_id, escalation_state, acknowledged_at, acknowledged_by }`
- **Behaviour:**
  - This is an **audited write**, appended — never an overwrite of the dispatch history
    (Alert Agent FR-13; dispatch records are permanent).
  - Acknowledging **closes the escalation ladder** for WARNING/CRITICAL alerts (Alert Agent FR-6).
    That is its whole purpose.
  - **Idempotent:** re-acknowledging an already-acknowledged alert is a no-op returning the
    original acknowledger and timestamp — it never overwrites who acknowledged first.
  - **This is not the approval gate.** Acknowledging an alert is *not* approving a dispatch; the
    `needs_approval` sign-off lives in the Alert Agent. This endpoint never causes an outbound
    notification.
  - Out-of-scope or unknown `alert_id` → **404**.

### 11. `POST /internal/trigger/{agent}` — n8n invokes an agent cycle

- **Purpose:** Let n8n invoke the next agent in the pipeline after the previous stage completes.
- **Who calls it:** **n8n only.**
- **Auth:** **Internal shared secret** (C) + network restriction. **Never publicly exposed.**
- **Sync/async:** **ASYNC — accepts and returns immediately.** The trigger is acknowledged; the
  agent runs on its own. The call never blocks for the agent's work.
- **Input:** `agent` (path — one of a **closed set**: the Data Collection, Structural Analysis, Risk
  Reasoning, Report Generation, and Alert Escalation agents) plus a **scope key only**:
  `{ municipality_id, bridge_id?, cycle_id?, assessment_id?, reading_ids?: [...],
     superseded_ids?: [...] }` — which fields apply depends on the agent.
- **Output:** `{ accepted: bool, agent, run_id|job_id, scope_echo: {...} }`
- **Behaviour:**
  - **Scope key only — never payload data.** Agents re-read the system of record themselves, so a
    trigger names *what* to process, never *the content*. This prevents trigger data drifting from
    the database (Report FR-4, Alert FR-1, SA/Risk input contracts).
  - The **Structural Analysis** trigger carries **two id lists** — newly-validated and
    corrected/superseded — per that agent's input contract.
  - **Risk** is triggered **once per bridge** per completed SA cycle; **Report** and **Alert** are
    triggered per finalized assessment.
  - **At-least-once delivery is assumed.** n8n may retry; every agent is **idempotent per version**,
    so a redelivered trigger is a **no-op**, never a double-dispatch or duplicate artifact.
  - An unknown `agent` name → **404**; a malformed/incomplete scope key → **422**.
  - **The API does not implement the agent.** It validates the scope, sets the tenant scope, and
    hands off (Principle III).
  - This endpoint **cannot** cause an outbound real-world action. Triggering the Alert Agent does
    not bypass its `needs_approval` gate — the gate lives in the agent, not at this boundary.

**Confirmed 2026-07-27:** the trigger surface is **five explicit per-agent endpoints**, not one
generic path — so each agent's scope key is a **distinct, typed contract** rather than a union of
optional fields. `{agent}` above enumerates the five; the per-agent scope keys are:

| Trigger | Scope key | Fired when |
|---|---|---|
| Data Collection (001) | `{ municipality_id }` (+ optional bridge/sensor narrowing) | on the DCA's own 1–5 min cycle |
| Structural Analysis (002) | `{ municipality_id, cycle_id, validated_ids: [...], superseded_ids: [...] }` — **two id lists** | after a DCA cycle completes |
| Risk Reasoning (003) | `{ municipality_id, bridge_id, cycle_id }` — **once per bridge** | after an SA cycle completes |
| Report Generation (004) | `{ municipality_id, bridge_id, assessment_id }` (+ optional historical-reprint flag) | per finalized assessment |
| Alert Escalation (005) | `{ municipality_id, bridge_id, assessment_id }` | per finalized assessment |

A trigger whose scope key omits a field its agent requires → **422**. Typed per-agent contracts make
that a validation failure at the boundary rather than a malformed run inside an agent.

### 12. `GET /bridges/{id}/sensors/{sid}/spectrum` — FFT spectrum data

- **Purpose:** Serve the **already-computed** FFT spectrum for a vibration/accelerometer sensor, for
  the dashboard's spectrum chart.
- **Who calls it:** **Dashboard.**
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync**, bounded.
- **Input:** `bridge_id`, `sensor_id` (path); optional `cycle_id` or `as_of` to select which
  analysis; pagination/limit on bins.
- **Output:** `{ sensor_id, cycle_id, analysis_id, computed_at,
  bins: [ { frequency_hz: number, magnitude: number } ],
  dominant_frequency_hz: number, provenance: { source_validated_ids: [...] } }`
- **Behaviour:**
  - **Reads Structural Analysis output; computes nothing** (INV-6). The API runs no FFT — if the SA
    agent has not produced a spectrum for that sensor, the response is an explicit "not available,"
    never a computed-on-the-fly result.
  - Serves the **current** (non-superseded) analysis and names the `analysis_id` it came from, so a
    chart traces to an audited row.
  - Only meaningful for sensor types SA computes spectra for; other types return an explicit
    not-applicable state rather than an empty chart.

### 13. `GET /bridges/{id}/heatmap` — strain-gauge deck heatmap data

- **Purpose:** Serve the **already-computed** per-gauge values that the dashboard renders as a deck
  heatmap.
- **Who calls it:** **Dashboard.**
- **Auth:** **Municipality-scoped JWT** (A).
- **Sync/async:** **Sync.**
- **Input:** `bridge_id` (path); optional `cycle_id` or `as_of`.
- **Output:** `{ bridge_id, cycle_id, computed_at,
  cells: [ { sensor_id, position?: {...}, value: number, unit: string,
  vs_limit?: { limit: number, exceeded: bool } } ],
  provenance: { source_analysis_ids: [...] } }`
- **Behaviour:**
  - **Assembles existing analysis facts; derives no new quantity** (INV-6). Pass/fail-vs-limit is
    read from the analysis result, **not** recomputed by comparing here.
  - A bridge with no strain-gauge array, or no analysis for the cycle, returns an explicit
    not-available state — never a fabricated or interpolated grid.
  - Gauge **position/layout** is bridge configuration; if positions are unknown the cells are still
    returned keyed by `sensor_id` so the consumer can degrade gracefully.

---

## Async job model

Only **report generation** is a job; everything else is a fast read or a fast append.

- `POST /bridges/{id}/reports` returns a **`job_id` immediately** — within **500 ms**, regardless of
  the 5–30 s render time.
- `GET /reports/{job_id}/status` returns exactly one of **`PENDING` / `RUNNING` / `COMPLETE` /
  `FAILED`** (closed set).
- `GET /reports/{job_id}/download` works **only** when `status = COMPLETE`; otherwise **409**.
- A **`FAILED`** job carries a **structured error reason** (`code` + `detail`) — never a stack trace.
- **Jobs must survive an API restart.** A job accepted and then lost is a silent failure; a job in
  `PENDING`/`RUNNING` must eventually reach `COMPLETE` or `FAILED`, never linger forever.
- **Ingestion is not a job** — the Pi gets a per-reading result synchronously and does not poll.
  Validation status appears later via the normal read endpoints, not via a job handle.

---

## Error responses

**No stack trace ever reaches any external caller** (INV-4). Every error is structured JSON:

```
{ error: <client-safe summary message>, code: <stable machine-readable code>,
  detail: <safe specifics — which field, which precondition>,
  correlation_id: <id for internal log lookup> }
```

> **Corrected 2026-07-31 (P101 Finding 2 / P103).** An earlier draft of this block had
> `error` and `code` the other way round (`error: <short machine code>`, `code: <http status>`),
> which contradicted the as-built handlers. The built shape above stands: the HTTP status is
> already in the status line, so `code` is better spent on a code a client can branch on
> (`validation_error`, `internal_error`, `http_418`).

| Condition | Status |
|---|---|
| Missing / invalid / expired credential | **401** |
| Authenticated but not permitted — wrong municipality, or a credential used outside its role (Pi key on a read endpoint, JWT on an internal trigger) | **403** |
| Request shape / field validation failure | **422** |
| Unknown resource, **or** a resource outside the caller's tenant scope | **404** |
| Report download requested before `COMPLETE` | **409** |
| Rate limit exceeded | **429** (+ `Retry-After`) |
| Unexpected internal failure | **500** — full detail **logged internally only** |

- **404-over-403 for cross-tenant reads (INV-3):** a valid `bridge_id` from another municipality
  returns **404**, not 403. 403 would confirm the resource exists — a tenancy leak. **403 is
  reserved for wrong *credential class*, not wrong tenant.**
- Error `detail` is **safe by construction**: no SQL, no internal identifiers, no file paths, no
  library names, no row contents.
- **Per-reading ingestion rejections are not HTTP errors.** A batch containing bad readings is a
  **successful** call reporting per-reading outcomes (AC-1); HTTP-level failure is reserved for the
  batch as a whole (auth, shape, size, rate).

---

## Rate limiting

- **Ingestion** — limited **per Pi API key**, because the Pi sends continuously. Limits are
  **config TODO** (steady rate, burst allowance, max batch size); a stakeholder supplies them —
  **do not guess**.
- **All other endpoints** — limited **per JWT**. Limits are **config TODO**.
- **Internal triggers** are network-restricted rather than throughput-limited, but must not be
  unbounded.
- Exceeding a limit returns **429 with a `Retry-After` header**, as a structured error.
- **Backpressure must not lose raw data.** Rate limiting sheds load by *rejecting a request the Pi
  can retry* — it must never accept a batch and silently drop readings (Principle II). A rejected
  batch is explicitly rejected so the gateway knows to resend.
- Oversized batches and payloads are bounded and rejected explicitly, not truncated.

---

## Acceptance Criteria

- **AC-1 (Per-reading ingestion result).** A Pi sending a batch receives a **per-reading**
  accept/reject result with a reason for each rejection — not a batch-level ok/fail. A mixed batch
  reports exactly which readings failed and why, and the valid ones are still appended.
- **AC-2 (Tenant isolation is absolute).** Municipality A's JWT cannot retrieve municipality B's
  data from **any** endpoint, **even with a valid `bridge_id`, `sensor_id`, `job_id`, or
  `alert_id`** — the response is 404, and zero rows of B's data appear in any field. This holds for
  reads, the report flow, and the alert list.
- **AC-3 (Report request is fast regardless of render time).** `POST /bridges/{id}/reports` returns
  a `job_id` **within 500 ms** even though generation takes 5–30 seconds; the call never blocks on
  rendering.
- **AC-4 (Unacknowledged CRITICAL alerts persist).** An unacknowledged CRITICAL alert appears on
  **every** `GET /bridges/{id}/alerts` call until it is **explicitly acknowledged** — delivery
  alone does not remove it. After acknowledgement it reports the acknowledger and timestamp.
- **AC-5 (Structured errors only).** Every endpoint returns structured JSON on every error path,
  **never a stack trace** and never an internal identifier. A forced internal failure yields
  `{error, code, detail, correlation_id}` with full detail only in the internal log.
- **AC-6 (Scope set before query).** Every authenticated request sets
  `app.current_municipality_id` from its credential **before** its first database query; a request
  with no resolvable scope reads **zero rows** rather than proceeding unscoped.
- **AC-7 (Credential separation).** A Pi API key cannot reach any read, report, or trigger endpoint
  (403); a dashboard JWT cannot reach ingestion or internal triggers (403); the internal trigger
  secret cannot reach any consumer endpoint (403).
- **AC-8 (Score never without its WHY).** No response containing a risk score omits the Risk
  Agent's verbatim explanation; a withheld assessment returns a null score with its verbatim
  withheld reason, never a fabricated number.
- **AC-9 (Download gating).** Download before `COMPLETE` returns 409; a `FAILED` job returns a
  structured reason; a partially-rendered document is never downloadable.
- **AC-10 (Trigger idempotency).** A redelivered `POST /internal/trigger/{agent}` for
  already-processed scope is a no-op — no duplicate report, no double dispatch, no double-page.
- **AC-11 (No real-world action at the boundary).** No API endpoint dispatches an alert, notifies
  an authority, or publishes a report. Acknowledging an alert produces no outbound notification.
- **AC-12 (Rate limit shape).** Exceeding a limit returns 429 with `Retry-After`; a shed ingestion
  batch is explicitly rejected (retryable) and never partially absorbed with readings dropped.

---

## Out of Scope

- **Serving the frontend assets** — the dashboard is deployed separately (Vercel's job). This API
  serves data only.
- **Agent logic** — validation, RMS/FFT/threshold math, risk scoring, PDF assembly, message
  templating. Agents are **invoked** via endpoint 11 and read/write the database themselves; none of
  their logic is re-implemented here.
- **Email / SMS dispatch, escalation, and the `needs_approval` gate** — the Alert Agent owns the
  system's single real-world-action chokepoint. The API records acknowledgements; it sends nothing.
- **Auth mechanism design** — token issuance, refresh, key provisioning/rotation UI, and the
  identity provider are a **separate auth spec**. This API consumes credentials and enforces scope.
- **The database schema** — Spec 002 (built).
- **Clearing a `PENDING_HUMAN_REVIEW` assessment** — the human-review workflow is a separate
  downstream concern. The API only *surfaces* `review_status`.
- **Report publication/submission to an authority** — explicitly out of scope for the Report Agent
  too; no endpoint publishes.

---

## Open Items (resolve at `plan.md` — do not guess)

**Config TODOs (a stakeholder supplies):**
- Ingestion rate limit per Pi key (steady rate, burst, max batch size) and expected readings/min.
- Per-JWT rate limits for read endpoints.
- Report status poll interval + max wait recommended to the dashboard.
- Retention/expiry of signed download references.

**Resolved 2026-07-27 (carried into `plan.md`):**
- **Async infrastructure:** **Arq** (durable queue + worker) for report jobs — satisfies AC-3 and
  the survive-a-restart requirement. Not in-process background tasks.
- **Ingestion hand-off:** **DCA scheduler pickup — no explicit "raw arrived" signal.** `POST /ingest`
  appends and acks; the DCA's own 1–5 min cycle finds the rows. (Resolves 003 Q-2; ack ≠ validated.)
- **Analysis-derived chart data:** **two new endpoints added** (12 spectrum, 13 heatmap) — closes the
  004 Q-2 / FR-7 gap. Both read SA output; neither computes.
- **Report download:** **signed URL** (not streamed through the API). *Storage provider remains an
  Open Item.*
- **Pi key mapping:** a **`device_credentials` table owned by this layer** (hashed keys).
- **Trigger surface:** **five explicit per-agent endpoints** with typed scope keys, not one generic path.

**Still open (deferred to `plan.md` or later):**
- **Object-storage provider** for report artifacts + signed-URL signature lifetime (the signed-URL
  *approach* is settled; the provider is not).
- **n8n callback routing** — how provider delivery receipts / webhook callbacks that advance an
  alert's `delivery_state` reach the system, and whether that is an API surface or n8n-direct.
- **Pagination defaults and hard maximums** per list endpoint.
- **Gauge position/layout source** for endpoint 13 (bridge configuration — where it lives).
