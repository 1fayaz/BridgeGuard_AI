# API Layer — Implementation Plan

**Status:** Draft — awaiting review before `tasks.md`.
**Date:** 2026-07-27
**Constitution:** v2.1.0 (`.specify/memory/constitution.md`)
**Spec:** `specs/api/spec.md` (behaviour — 13 endpoints, 12 AC, 7 invariants)
**Research:** `specs/api/research-api.md`
**Supersedes:** `specs/003-backend-api/plan.md` (same layer, stale premises — see §0)

> **Architecture and data-flow only. No implementation code in this document.**
>
> **Six decisions confirmed by the user 2026-07-27 and binding on this plan:**
> 1. **Arq** for async jobs (durable queue + worker).
> 2. **DCA scheduler pickup** — no explicit "raw arrived" ingest signal.
> 3. **Two new analysis endpoints** (FFT spectrum, deck heatmap).
> 4. **Signed URL** for report download — **Cloudflare R2** via the **S3-compatible SDK**,
>    **15-minute TTL**.
> 5. **`device_credentials` table owned by this layer.**
> 6. **Five explicit per-agent trigger endpoints** (not one generic path).
> 7. **Job row owned by the API layer; the report artifact owned by Agent 4.**
>
> Auth is settled in the spec: **municipality-scoped JWT** (engineers/dashboard) and **per-device
> API key** (Pi, one per physical device, in the Pi's `.env`, never in code) resolving to exactly one
> `bridge_id` + `municipality_id` — **same RLS enforcement path, different credential shape.**

---

## 0. Relationship to Spec 003, and what is actually new

Spec 003 (`003-backend-api`) planned this same layer against stale premises (constitution v1.0.0,
PostgreSQL+TimescaleDB, "skills README missing", Spec 002 unwritten). Those are now reconciled, and
**`specs/api/spec.md` governs**. What this plan changes versus 003's plan:

| Area | 003's plan | This plan |
|---|---|---|
| GUC name | `app.municipality_id`, cast `::uuid` | **`app.current_municipality_id`**, tenant key is **TEXT** (the as-built 0016 policies) |
| Queue | "Arq or RQ/Celery" (open) | **Arq**, decided |
| Ingest signal | enqueue a "raw arrived" signal | **none** — DCA scheduler pickup |
| Report delivery | PDF or signed URL (open) | **signed URL**, decided |
| Pi key storage | unspecified | **`device_credentials`** table, this layer owns it |
| Agent triggers | absent | **five explicit per-agent endpoints** |
| Chart data | `[SKILL-DEP]`, shape unknown | **two concrete analysis endpoints** (12, 13) |

**The GUC-name correction is the single highest-risk carry-over.** Building to 003's `app.municipality_id`
would have produced a system that silently returned **zero rows everywhere** — the policies would
never match, and fail-closed semantics would make it look like "no data" rather than a bug. §3 makes
this a tested invariant, not a convention.

---

## 1. Layering — where the boundary actually sits

The API is a **boundary, not an orchestrator** (spec Goal). Agents read/write the database directly;
the API never sits between an agent and its data.

```
Pi gateway ─(API key)──────► POST /ingest ──► append raw_readings ──┐
                                                                     │ (no signal —
dashboard ─(JWT)───────────► read endpoints ──► current-state reads  │  DCA polls)
engineer  ─(JWT)───────────► report flow ────► Arq queue ──► worker ─┤
n8n ──────(shared secret)──► 5 trigger endpoints ──► agent entrypoints
                                                                     ▼
                         ┌───────────────────────────────────────────────────┐
                         │  Neon/Postgres — RLS FORCEd, bridgeguard_service   │
                         │  every txn: SET LOCAL app.current_municipality_id  │
                         └───────────────────────────────────────────────────┘
                                        ▲
              agents (DCA/SA/Risk/Report/Alert) read+write here DIRECTLY,
              not through the API — the API only triggers them
```

**Internal layering** (Principle III — no domain logic above the service line):

- **Transport layer** — request/response shapes, status codes, the error envelope. No domain logic.
- **Auth + scope layer** — resolves the principal, derives `municipality_id`, **opens the transaction
  and sets the GUC** (§3). Every request passes through it; there is no bypass.
- **Service layer** — thin orchestration: append, read, enqueue, trigger. Calls agent entrypoints and
  the DB through their published contracts. **Reimplements no agent logic.**
- **Repository layer** — the only place SQL lives. Every repository method executes inside a
  scope-set transaction (§3) — it is structurally unable to run unscoped.

**Boundary rule:** transport → service → (repository | agent entrypoint | queue). A transport handler
that touches SQL, or a service that computes a domain value (a band, an FFT, a ratio), is a defect.

---

## 2. Authentication design

Three credential classes, resolved by one pipeline to one output: a `Principal` carrying exactly one
`municipality_id`.

| Class | Credential | Resolves to | May reach |
|---|---|---|---|
| **Engineer / dashboard** | Bearer **JWT**, `municipality_id` tenant claim + identity/role | `municipality_id`, `user_id` | endpoints 2–10, 12, 13 |
| **Pi gateway** | **Per-device API key** header; one key per physical Pi, in the Pi's `.env` | `municipality_id` **+ `bridge_id`** (via `device_credentials`) | endpoint 1 **only** |
| **n8n** | **Internal shared secret** + network restriction | `municipality_id` from the request's scope key | the five trigger endpoints **only** |

### 2a. `device_credentials` — owned by this layer (decision 5)

A new table this layer owns (agents never read it). Shape:

- `credential_id` — surrogate identity.
- `key_hash` — the API key stored **hashed** (never plaintext, never recoverable). Lookup is by
  hash, so a database dump does not yield usable keys.
- `bridge_id` + `municipality_id` — the **hard-FK'd** pair the key resolves to. `municipality_id` is
  denormalized alongside `bridge_id`, consistent with the existing tenant-column pattern, so
  resolution needs no join up the ownership chain.
- `device_label` — which physical Pi (operator-facing).
- `status` — active / revoked. **Revocation is a state change, not a delete** (audit permanence).
- `created_at`, `last_used_at`, `revoked_at`.

Migration: **`0017_device_credentials.sql`** — verified free 2026-07-31 (`db/migrations/` runs
0001–0016 with no gaps; 0016 is the highest). **`[DB-DEP]`** — reviewable
now, executable when a live Neon instance exists; an in-memory fake mirrors it for tests, matching
the established pattern.

**Rotation** is: insert a new active row for the device, then mark the old row revoked — two active
keys briefly coexist so a Pi can be re-flashed without a data gap. Never an in-place key overwrite.

### 2b. Credential-class separation is structural

Each endpoint declares **which credential class** it accepts; the auth layer rejects a valid
credential of the wrong class with **403** (spec AC-7). This is a positive allow-list per endpoint,
not a negative check — a new endpoint with no declared class is unreachable rather than open.

**Why the Pi key is write-only-to-ingest:** a physically-installed field device is the most likely
credential to be extracted. Scoping it to one bridge's ingestion means a stolen key can append
readings for one bridge — not read a municipality's assessments or request reports.

**Out of scope (separate auth spec):** JWT issuance, signing keys, refresh, and the operator UI for
provisioning device keys. This layer **consumes** and **enforces**.

---

## 3. Tenant scope — the non-negotiable seam

Spec INV-1/INV-2 and AC-6. This is the single most important mechanism in the layer.

```
request ──► resolve principal ──► derive exactly one municipality_id
                                          │
                                   BEGIN transaction
                                   SET LOCAL app.current_municipality_id = <id>   ◄── before ANY query
                                          │
                                   ... every read/write in this request ...
                                          │
                                   COMMIT / ROLLBACK  (GUC resets — cannot leak to the next request)
```

Design commitments:

- **Exact GUC name `app.current_municipality_id`** — matches the as-built 0016 policies. Tenant key
  is **TEXT** (e.g. `MUNI_A`), **not** uuid. No casting.
- **`SET LOCAL`, transaction-scoped — never session-scoped `SET`.** On a pooled connection a
  session-level GUC would leak one tenant's scope into the next request. This is a foot-gun the DB
  layer's operator note calls out explicitly.
- Set via the **parameterized** form (`set_config(..., is_local => true)`) so a tenant id is never
  string-built into SQL — the injection surface at the tenancy seam is closed by construction.
- **Structural enforcement, not discipline:** the repository layer cannot open a connection outside a
  scope-set transaction. There is no "raw connection" helper for handlers to reach for. A forgotten
  scope should be *impossible to express*, not merely caught in review.
- **Fail-closed:** an unresolvable scope means the request never queries. Even if it did, the policy
  predicate uses `current_setting(..., true)` → NULL → zero rows.
- Connect as **`bridgeguard_service`**; never a superuser, never `BYPASSRLS`. RLS is `ENABLE`d **and
  `FORCE`d** so the table-owning role is itself bound.
- **Defense in depth:** service-layer queries still filter by tenant where natural, but that is a
  *secondary* check. RLS is the guarantee (INV-2).

**The 404-not-403 rule (INV-3)** falls out of this naturally: a cross-tenant `bridge_id` yields zero
rows under RLS, so the handler genuinely cannot distinguish "absent" from "another tenant's" — and
reports 404. The safe behaviour is the default behaviour, not an added check.

---

## 4. Ingestion — append + ack, DCA scheduler pickup (decision 2)

```
POST /ingest  (Pi API key → bridge_id + municipality_id)
  │
  ├─ shape-check each reading independently        (fast, deterministic, no validation)
  ├─ reject readings whose sensor_id ∉ this key's bridge_id
  ├─ APPEND accepted readings to raw_readings      (append-only; no update/delete path exists)
  ├─ audit the write                                (principal, tenant, request)
  └─ return per-reading results                     (AC-1)

          ⋯ no signal, no enqueue ⋯

DCA's own 1–5 min scheduler tick ──► finds unprocessed raw rows ──► validates ──► validated_readings
```

- **No "raw arrived" enqueue.** The DCA already owns a 1–5 min cycle; a per-batch signal would either
  duplicate that trigger or make the agent's cadence depend on gateway traffic. Decision 2 keeps the
  agent's cadence its own concern — fewer moving parts, and one place that decides when validation runs.
- **The endpoint's guarantee is narrow and honest:** *raw is durable* + *per-reading shape outcome*.
  It does **not** promise validity. Validation status surfaces later through the read endpoints.
- **Per-reading, not per-batch** (AC-1). Shape-checking is per-item and independent; one bad reading
  cannot reject its neighbours. Rejection reasons come from a **closed enum** so the gateway can act
  programmatically.
- **Cross-bridge rejection is a per-reading reason, not a 403.** The batch is legitimate; individual
  readings naming another bridge's sensors are rejected with a reason. Silently re-attributing them
  would corrupt tenancy.
- **Duplicate tolerance:** a Pi retrying after a network failure is normal. Redelivery is not
  reported to the caller as failure.
- **The API never validates, cleans, interpolates, or flags.** That is the DCA's job (Principle III).

**Consequence to accept:** worst-case latency from reading-arrival to validated is one scheduler
period. That is inherent to the DCA's design, not introduced here.

---

## 5. Report jobs — Arq (decision 1) + signed URL (decision 4)

**Arq**: async-native (fits the async transport layer), Redis-backed, durable across restarts —
which is what spec AC-3 ("`job_id` within 500 ms") plus the survive-a-restart requirement demand.
In-process background tasks were rejected: a restart would orphan a 5–30 s render with no record.

```
POST /bridges/{id}/reports
  ├─ create a job row {PENDING}          ◄── the job's status lives in Postgres, not only in Redis
  ├─ enqueue an Arq job (scope key only: bridge_id + assessment identity)
  └─ return {job_id, PENDING}             within 500 ms  (AC-3)

Arq worker
  ├─ mark RUNNING
  ├─ invoke the Report Agent with the scope key   (the AGENT renders; the API does not)
  ├─ agent writes its append-only artifact + returns a structured outcome
  ├─ upload/locate the artifact in object storage
  └─ mark COMPLETE (+ document marks)  |  mark FAILED (+ structured reason code)

GET /reports/{job_id}/status    ──► reads the job row (cheap; designed to be polled)
GET /reports/{job_id}/download  ──► COMPLETE only → issue a short-lived SIGNED URL; else 409
```

Design commitments:

- **Job status is persisted in Postgres**, not held only in Redis. Redis is the *delivery* mechanism;
  Postgres is the *record*. If Redis is flushed, jobs are still accountable and their status
  answerable — a job must never vanish silently.
- **Status is a closed four-state set** — `PENDING / RUNNING / COMPLETE / FAILED`. No other value.
- **`FAILED` carries a structured `code` + `detail`**, mapped from the Report Agent's own outcome
  vocabulary (e.g. assessment-not-found, provenance-mismatch). **Never a stack trace** (INV-4).
  The agent already never crashes and always returns a structured outcome, so this is a mapping
  exercise, not error-handling invention.
- **The worker triggers; it does not render.** It passes a **scope key** and lets the agent read the
  system of record itself — so a report can never be built from data the API copied and that has
  since drifted (Report FR-4).
- **Idempotency is the agent's, and the API respects it.** A request for an already-rendered current
  assessment returns the existing job/artifact rather than queueing duplicate work.
- **Download is a signed URL** (decision 4): the artifact is streamed from object storage, not
  through the API — a 5–30 s render can produce a large PDF, and proxying it would tie up an API
  worker per download. **The signed URL is generated only after a fresh tenant-scope check**, so the
  URL is the *delivery* mechanism and the API remains the *authorisation* point.
- **`COMPLETE` gating is strict:** `PENDING`/`RUNNING` → 409 (retryable); `FAILED` → 409 with the
  reason. A partial document is never reachable — the agent's artifact write is atomic, so there is
  no half-written file to expose.
- **Storage: Cloudflare R2 via the S3-compatible SDK; signed-URL TTL = 15 minutes.** R2 speaks the
  S3 API, so the storage client is written against the S3 interface and R2 is a configured endpoint —
  the provider stays swappable and is never hard-coded into handler logic. **Credentials come from
  environment configuration, never from code.**
  - **15 minutes** is long enough for an engineer to click through and for a large PDF to transfer on
    a poor connection, short enough that a leaked or logged URL expires quickly. The URL is
    **single-purpose (read-only, one object)** — it grants no bucket listing and no write.
  - **A signed URL is a bearer credential**, so it is treated as one: issued only after a fresh
    tenant-scope check, never logged, and re-issued (not extended) if it expires — a second download
    means a second authorisation check, not a longer-lived token.

### 5a. Job row (API) vs. artifact (Agent 4) — decision 7

**The API layer owns the job row; Agent 4 owns the artifact.** A clean split with no shared writer:

| | Owner | Lifecycle | Discipline |
|---|---|---|---|
| **Report job** (`job_id`, requester, scope, PENDING/RUNNING/COMPLETE/FAILED, error code, timestamps) | **API layer** | created on request, mutated as the job progresses | mutable status row — an API-boundary concept |
| **Report artifact** (`report_artifacts`, the rendered PDF + its provenance/version) | **Agent 4** | appended when a render completes | **append-only, correct-by-supersede** — a regulator-relied-on document is permanent |

- **The job is an API-boundary concept the agent has no need to know about.** Agent 4 is triggered by
  a scope key and knows nothing of `job_id` — consistent with its spec, where the trigger carries a
  scope key only.
- **Nobody writes the other's table.** The API never writes `report_artifacts`; the agent never
  writes the job row. The worker is the *only* place the two meet: it reads the agent's structured
  outcome and projects it onto the job's status.
- **Why the job row may be mutable while the artifact may not:** the job is ephemeral operational
  state (this request's progress); the artifact is the permanent record. Making the job append-only
  would add no audit value, and making the artifact mutable would violate Principle II/VI.
- **Linking:** on completion the job records **which artifact version** it produced, so a `job_id`
  resolves to an exact, immutable document. A re-render creates a **new** job and a **new** artifact
  version; neither overwrites its predecessor.

**Retry policy:** Arq retries a *failed worker execution* (transient infrastructure). It does **not**
retry a job the agent resolved as `WITHHELD` — that is a determinate outcome, and retrying it would
just re-fail. Distinguishing infrastructure failure from a determinate agent outcome is the worker's
responsibility.

---

## 6. Read endpoints — current-state reads, no computation

All reads (2, 3, 4, 5, 9, 12, 13) share one shape: **resolve scope → read current rows → project**.

- **`GET /bridges`** — served from **current, non-superseded assessments** joined to bridges; never a
  scan of reading history. This is what makes the <500 ms target reachable, and it is why the DB
  layer has a partial-unique-current index on assessments.
- **Bands are read, never computed.** `SAFE/WATCH/WARNING/CRITICAL` come from the assessment row. The
  API contains **no band thresholds** — duplicating the 0–30/31–60/61–80/81–100 mapping here would
  create a second source of truth that could silently diverge from the Risk Agent.
- **Null-honest projections.** No assessment, or a withheld score → `risk_score: null` plus the
  verbatim withheld reason. **Never a fabricated `0`** (which would read as "safe"). This is the
  read-layer echo of the agents' refusal to invent values.
- **INV-7 is enforced at the projection boundary:** the response shape makes `explanation` non-optional
  wherever `risk_score` is present, so a score cannot be serialized without its WHY.
- **Time-series (4)** hits the standard `(sensor_id, sensor_time DESC)` composite B-tree index —
  no hypertables exist. **Pagination with an enforced hard maximum** on every list endpoint, so no
  request can pull an unbounded series.
- **Interpolation and gaps are surfaced, not smoothed** — `status` and `is_interpolated` pass through
  from the DCA verbatim (Principle II transparency).

### 6a. The two analysis endpoints (decision 3)

**12 `/spectrum`** (FFT) and **13 `/heatmap`** (strain-gauge deck) close the 004 Q-2 / FR-7 gap.

- Both **read Structural Analysis output**. The API runs **no FFT** and performs **no
  limit comparison** — it projects `analysis_results` rows the SA agent already wrote. This is the
  whole reason these are safe to add: they are reads, not a second analysis path (Principle III/IV).
- Both name the **`analysis_id`** they projected, so a chart traces to an audited row (INV-6).
- **Not-available is an explicit state, never an empty chart.** No spectrum for that sensor / no
  strain array on that bridge / no analysis for that cycle → an explicit not-applicable or
  not-available response. Fabricating an empty grid would read as "all zero," i.e. "fine."
- **OPEN ITEM: gauge position/layout** for the heatmap is bridge configuration; where it lives is
  unresolved. Fallback behaviour is settled: return cells keyed by `sensor_id` so the consumer
  degrades gracefully rather than failing.

---

## 7. The five per-agent trigger endpoints (decision 6)

Five explicit endpoints with **typed scope keys**, rather than one generic path with a union of
optional fields. Rationale: the per-agent contracts genuinely differ (SA needs two id lists; Risk is
per-bridge; Report/Alert are per-assessment), so a union type would make every field optional and
push "did n8n send the right fields?" from a boundary validation into a malformed run inside an agent.

```
n8n (shared secret + network-restricted)
  │
  ├─► trigger/data-collection   { municipality_id }                                    ─┐
  ├─► trigger/structural-analysis { municipality_id, cycle_id,                           │ each:
  │                                 validated_ids[], superseded_ids[] }   ◄── TWO lists  │  validate
  ├─► trigger/risk              { municipality_id, bridge_id, cycle_id }  ◄── per bridge │  set scope
  ├─► trigger/report            { municipality_id, bridge_id, assessment_id }            │  hand off
  └─► trigger/alert             { municipality_id, bridge_id, assessment_id }           ─┘  ack now
```

- **Scope key only — never payload data.** Agents re-read the system of record. A trigger names
  *what* to process, never *the content* (Report FR-4, Alert FR-1). This is why a superseded upstream
  row can never be laundered into a downstream run.
- **Accept-and-ack; never block.** The trigger returns immediately; the agent runs on its own. n8n
  is glue that invokes and moves on.
- **A missing required field is a 422 at the boundary** — caught before an agent starts, not
  discovered mid-run.
- **At-least-once delivery assumed.** n8n retries; every agent is **idempotent per version**, so
  redelivery is a no-op. The API adds no dedup layer of its own — duplicating the agents'
  idempotency would create two competing notions of "already handled."
- **These endpoints implement no agent logic.** They validate a scope key, set the tenant scope, and
  hand off.
- **Triggering the Alert Agent does not bypass its `needs_approval` gate.** The gate lives inside the
  agent. There is deliberately **no API surface that approves a dispatch** — otherwise the boundary
  would become a second, un-gated path to a real-world action, breaking the single-chokepoint
  invariant (Alert FR-5).

**Network restriction is required in addition to the secret.** A leaked shared secret must not be
sufficient to trigger the pipeline from outside.

---

## 8. Errors, rate limiting, and audit

**Errors.** One shared envelope `{error, code, detail, correlation_id}`, produced by a single global
handler so **no** unhandled exception can escape as a stack trace (INV-4, AC-5). `detail` is safe by
construction: no SQL, no internal ids, no paths, no library names. Full detail is logged internally
against the `correlation_id`.

- **401** missing/invalid credential · **403** wrong credential *class* · **422** shape/validation ·
  **404** unknown **or** out-of-tenant · **409** download-before-COMPLETE · **429** rate limited ·
  **500** unexpected (logged only).
- **403 is never used for wrong tenant** — that is 404 (INV-3). 403 would confirm existence.
- **Per-reading ingestion rejections are not HTTP errors** — a batch with bad readings is a
  *successful* call reporting per-reading outcomes.

**Rate limiting.** Per **Pi API key** on ingestion (the Pi sends continuously); per **JWT** elsewhere.
429 + `Retry-After`, as a structured error. **All limit values are config TODO — a stakeholder
supplies them; do not guess.** The critical behavioural commitment: **backpressure rejects a
retryable request; it never accepts a batch and drops readings** (Principle II). Batch and payload
sizes are bounded and rejected explicitly, never truncated.

**Audit (INV-5, Principle VI).** Every write — ingest, report request, alert acknowledgement, report
download access — records timestamp, principal, tenant, and the causing request. Acknowledgement
audit is **append-only**: re-acknowledging never overwrites who acknowledged first.

---

## 9. Testing strategy

Following the repo's established cadence (**write failing test → confirm red → implement → confirm
green → stop**) and its `[DB-DEP]` discipline: no live Neon locally, so in-memory fakes mirror the
SQL guarantees and migration text is asserted structurally.

| # | Test | Asserts | AC |
|---|---|---|---|
| T-1 | Per-reading ingest | mixed batch → correct per-index accept/reject + closed-set reasons; valid ones still appended | AC-1 |
| T-2 | Cross-bridge reading | reading outside the key's `bridge_id` → per-reading rejection, never re-attributed | AC-1 |
| T-3 | Append-only | no code path updates/deletes raw readings | Principle II |
| T-4 | **Scope-set-before-query** | every request sets `app.current_municipality_id` **before** its first query; a repository call outside a scoped transaction is **structurally impossible** | **AC-6** |
| T-5 | **GUC name + type** | the exact string `app.current_municipality_id`, TEXT (no `::uuid`) — a regression guard against 003's wrong name | AC-6 |
| T-6 | **Cross-tenant with valid ids** | A's JWT + B's `bridge_id`/`sensor_id`/`job_id`/`alert_id` → **404**, zero rows of B in any field | **AC-2** |
| T-7 | 404-not-403 | cross-tenant never returns 403 (no existence disclosure) | AC-2 |
| T-8 | Credential separation | Pi key on any read/report/trigger → 403; JWT on ingest/trigger → 403; secret on consumer endpoints → 403 | AC-7 |
| T-9 | Report accept latency | `POST` returns `job_id` **<500 ms** with a stubbed 30 s render | AC-3 |
| T-10 | Job durability | a job enqueued then worker-restarted still reaches COMPLETE/FAILED; status readable from Postgres alone | AC-3 |
| T-11 | Download gating | PENDING/RUNNING → 409; FAILED → 409 + structured reason; COMPLETE → signed URL; partial never reachable | AC-9 |
| T-12 | Signed-URL authorisation | URL issued only after a fresh scope check; another tenant's `job_id` → 404 | AC-2/AC-9 |
| T-13 | **Unacked CRITICAL persists** | appears on **every** alerts call until acknowledged; DELIVERED alone does not remove it | **AC-4** |
| T-14 | Ack idempotency + attribution | re-ack is a no-op preserving the first acknowledger; identity comes from the credential, never the body | AC-4 |
| T-15 | Score never without WHY | no projection serializes `risk_score` without verbatim `explanation`; withheld → null + verbatim reason, never `0` | AC-8 |
| T-16 | No band thresholds in the API | a structural scan finds no 0–30/31–60/61–80/81–100 mapping anywhere in this layer | Principle III |
| T-17 | Analysis endpoints compute nothing | no FFT/limit-comparison code path; missing analysis → explicit not-available, never an empty grid | INV-6 |
| T-18 | Trigger scope-key typing | each of the five validates its own required fields → 422 when incomplete; SA requires **both** id lists | AC-10 |
| T-19 | Trigger idempotency | redelivered trigger → no duplicate report, no double dispatch | AC-10 |
| T-20 | **No real-world action** | a structural check that **no** API module dispatches/notifies/publishes, and **no** endpoint approves a gated dispatch | **AC-11** |
| T-21 | Structured errors | forced internal failure → envelope + correlation_id, no stack trace, no SQL/paths in `detail` | AC-5 |
| T-22 | Rate limit shape | 429 + `Retry-After`; a shed batch is explicitly rejected, never partially absorbed | AC-12 |
| T-23 | Audit on writes | ingest, report-create, ack each produce an audit record (ts, principal, tenant, request) | Principle VI |
| T-24 | Pagination bounds | every list endpoint enforces a hard maximum | FR/§6 |

**`[DB-DEP]`:** T-6/T-7 prove isolation against *real* RLS only on a live Neon instance; until then
fakes mirror the predicate and migration text is asserted structurally — the same split the DB layer
documented in `FK-STRATEGY.md`. **T-4 and T-20 are the two tests that must not be allowed to
regress**: one guards the tenancy seam, the other guards the single-chokepoint invariant.

---

## Constitution Check (v2.1.0)

| Principle | How this plan complies |
|---|---|
| **I — Safety first / human signs off physical actions** | The API exposes **no** real-world action: no dispatch, no notify, no publish, and deliberately **no approve-a-dispatch surface** (§7) — the `needs_approval` chokepoint stays inside the Alert Agent. Ack is an audit fact, not an outbound act. Every score is served with its verbatim WHY (INV-7, T-15). Enforced structurally by T-20. |
| **II — Raw data immutable; every number traceable** | Ingestion appends only; no update/delete path (T-3). Reads project persisted agent rows and compute nothing (T-16, T-17); analysis endpoints name the `analysis_id` they projected. Backpressure rejects retryably rather than dropping readings (§8). |
| **III — Modularity / no agent internals** | The API triggers agents by **scope key** and reads their published tables; it re-implements no validation, math, scoring, rendering, or templating. Agents own their DB access directly (§1). |
| **IV — Reliability over cleverness** | Deterministic handling; a single global error envelope; closed status/reason enums; durable Arq jobs with status in Postgres (§5). Standard Postgres reads — no TimescaleDB. |
| **V — Testability** | 24 tests mapped to the 12 AC (§9), each endpoint testable behind fakes; the never-crash and isolation paths tested explicitly. |
| **VI — Auditability** | Every write audited with principal + tenant + causing request; acknowledgement audit is append-only; report access logged; `correlation_id` links a client error to internal detail (§8). |
| **VII — Tech stack / trace from day one** | Python + FastAPI (per 003's framework decision, unchanged); **Neon/Postgres, standard B-tree only, no TimescaleDB**; **Arq** for jobs; n8n as trigger glue. The API calls **no model**, so the SDK alias-import rule does not arise here; agent-run tracing remains the agents' obligation, and the API's audit log + `correlation_id` cover the boundary. |

---

## Open Items (resolve before or during `tasks.md`)

**Config TODOs (a stakeholder supplies — do not guess):**
1. **Ingestion rate limit** per Pi key: steady rate, burst, max batch size — needs expected
   readings/min per device.
2. **Per-JWT rate limits** for read endpoints.
3. **Report poll interval + max wait** recommended to the dashboard.
4. **Pagination defaults and hard maximums** per list endpoint.

**Resolved 2026-07-27:** object storage = **Cloudflare R2** (S3-compatible SDK), signed-URL TTL =
**15 minutes** (§5); **job row owned by the API layer, artifact owned by Agent 4** (§5a).

**Design decisions still open:**
6. **Gauge position/layout source** for the heatmap endpoint (bridge configuration — where it
   lives). Fallback (cells keyed by `sensor_id`) is already settled.
7. **n8n callback routing** — how provider delivery receipts / webhooks that advance an alert's
   `delivery_state` reach the system, and whether that is an API surface or n8n-direct. If it becomes
   an API surface, it needs a credential class and must **not** become a second dispatch path.
8. **Redis deployment** for Arq (managed vs self-hosted) and its failure posture — confirm that a
   Redis outage degrades to "jobs queue late," never "jobs silently lost" (§5 puts status in
   Postgres for exactly this reason).
9. **`device_credentials` shape sign-off** per §2a (hashed key, revoke-not-delete, denormalized
   `municipality_id`). *Migration number resolved 2026-07-31: 0017 (and 0018 for the report-job
   table) are free — 0016 is the highest existing migration.*
10. **R2 bucket layout + retention** — object key scheme (must not leak tenant identity in a guessable
    path), bucket-level access posture, and how long artifacts are retained. The *provider* and *TTL*
    are settled (§5); the bucket's own policy is not.

**Cross-cutting:**
11. **Auth spec dependency** — JWT issuance/signing/refresh and the device-key provisioning UI. This
    layer consumes credentials; it cannot be end-to-end verified until the auth spec lands.
12. **Live Neon instance** — required before T-6/T-7 (real RLS isolation) can move from
    fake-verified to live-verified.
