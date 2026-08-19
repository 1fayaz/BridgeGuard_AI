# API Layer — Research Findings (research-api.md)

**Status:** Research only — no routes, no code. Inputs: `CLAUDE.md`, `specs/database/spec.md`,
and all `specs/*/spec.md` (003-backend-api, 004-dashboard-frontend, data-collection,
structural-analysis, risk-reasoning, report-generation, alert-escalation).
**Date:** 2026-07-27

> **Governance note (RESOLVED 2026-07-27).** The stack is settled at **constitution v2.1.0**:
> **Neon/Postgres, standard B-tree indexes only, no TimescaleDB**; `skills/bridgeguard-skills-README.md`
> **exists**. Spec 003's stale premises (it cited v1.0.0 / PostgreSQL+TimescaleDB and a "missing"
> README, with `[SKILL-DEP]` markers) are superseded by this decision — findings below are against
> the **as-built** DB layer, which is authoritative.

## 1. Endpoints the API must expose (from each agent's trigger/consumption contract)

Grouped by the consumer that forces them. Spec 003 already names most (FR-#); gaps are flagged NEW.

| Capability | Driven by | Notes / source |
|---|---|---|
| **Sensor ingestion** (batch, per-reading result) | Pi gateway → DCA (001) | 003 FR-1/FR-4, AC-1. Append raw, then **enqueue** — see §3. |
| **Dashboard overview** (all in-scope bridges: score+band, <500ms) | Frontend US-1 (004) | 003 FR-5, AC-2. Reads a current-status model, never raw scans. |
| **Bridge detail** (sensors, current score + **verbatim reasoning/WHY**, trend) | Frontend US-3 (004) | 003 FR-7. Principle I: score always with its explanation. |
| **Sensor time-series** (`from/to`, 30/90/365 fast-path, `status`/`is_interpolated`) | Frontend US-2 | 003 FR-6, FR-8 (chart data/metadata). |
| **Risk score view** (score, band, reasoning_text, scored_at) | Frontend US-3, FR-5 (004) | 004 references `/risk-score`; fold into bridge-detail or expose distinctly. |
| **Report request → job_id** (async) | Frontend US-4; Report agent (004-agent) | 003 FR-10; render takes **5–30s** → §3. |
| **Report status** + **download** | Frontend AC-4 | 003 FR-11/FR-12. Poll status, then download PDF/signed URL. |
| **Alert list** (municipality-wide + per-bridge, read-only status) | Frontend US-5 | 003 FR-13. **NEW:** muni-wide `GET /v1/alerts` (004 Q-7 gap). |
| **Alert acknowledge** (audited write) | Frontend US-5, FR-13; Alert agent ACK closes WARNING/CRITICAL | **NEW — not in Spec 003** (003 is read-only). This is the human-ACK that FR-6 of the alert spec requires; it is an *audited write*, not a dispatch. |

Read-only for the API throughout: the API **never** dispatches alerts or publishes reports —
those are the Alert agent's gated chokepoint and the Report agent's artifact write.

## 2. Auth shape — resolving `municipality_id` → `app.current_municipality_id`

The DB layer's contract (RLS.md, database spec Out-of-Scope) is explicit and **binding on the API**:
- The API must resolve the authenticated principal to **exactly one** `municipality_id`, then issue
  `SET LOCAL app.current_municipality_id = '<tenant>'` (or `set_config(..., is_local=>true)`)
  **at the start of every transaction, before any query**, connecting as `bridgeguard_service`
  (never superuser, never `BYPASSRLS`). Fail-closed: an unset GUC reads zero rows.
- **Token issuance is a separate auth spec** (003 FR-14, DB Out-of-Scope). This API *consumes*
  identity/tenant claims; it does not mint them.
- **Two distinct principals — CONFIRMED 2026-07-27** (003 FR-3, resolving Q-3):
  - **Engineers / dashboard → municipality-scoped JWT** bearing a `municipality_id` tenant claim
    (stateless, fits the per-request GUC set).
  - **Pi gateway → per-device API key** — one key per physical Pi, stored in the Pi's `.env`, never
    in code. The key resolves to **exactly one `bridge_id` + `municipality_id`** at the database
    layer — the **same RLS enforcement path** as the JWT, just a different credential shape.
- Both credentials converge on the same non-negotiable seam: resolve → set
  `app.current_municipality_id` before any query. The credential *shape* differs; the isolation
  *mechanism* does not.
- The DB **cannot** verify the scope the API set matches the authenticated user — that trust boundary
  is the API's, enforced *before* the transaction opens.

## 3. Async vs sync (fast reads vs job queue)

- **Synchronous / fast reads (can block the request):** overview (<500ms), bridge detail,
  time-series, risk score, alert list, alert-ack write. All are indexed current-state or bounded
  range reads under RLS — no long work.
- **Asynchronous / job queue (must not block):**
  - **Report generation** — the Report agent is **fire-and-notify, 5–30s** (report spec FR-12,
    Core Concepts). API returns `job_id` immediately (003 AC-4), frontend **polls** status then
    downloads (004 AC-4). Infra choice (FastAPI BackgroundTasks vs Celery/RQ/Arq) is 003 Q-4 OPEN;
    a durable queue is safer for a 5–30s job that must survive a restart.
  - **Ingestion** — the API **acks fast and enqueues**; validation runs on the DCA's 1–5 min cycle,
    not in-request (003 Q-2, recommend enqueue). Ingestion is an async *hand-off*, not a job the
    caller polls.

## 4. n8n trigger endpoints (glue invoking each agent after a cycle)

n8n is workflow glue between MQTT ingestion and agent triggers (CLAUDE.md). The API/queue must let
n8n fire each downstream agent with a **scope key only** (identity, never payload — agents re-read
the system of record). The pipeline edges are DCA → SA → Risk → Report → Alert:
- **After ingestion:** trigger **DCA** on its cycle (enqueue drives this).
- **After DCA cycle:** trigger **SA (002)** — carries **two ID lists** (newly-validated + corrected/
  superseded reading/block IDs).
- **After SA cycle:** trigger **Risk (003)** — once per bridge, scope `(bridge_id, cycle_id)`.
- **After Risk finalizes:** trigger **Report (004)** — scope = one assessment id / `(bridge_id,
  cycle_id)`; and **Alert (005)** — same scope, downstream per finalized assessment.
- **Delivery-receipt / ACK callbacks** (provider webhooks advancing `delivery_state`, and the human
  ACK) may also flow back through n8n → the alert-ack write (§1). OPEN: callback routing owner.
These are **internal, service-to-service** endpoints (distinct auth from user + gateway) — n8n owns
detect-and-invoke + trigger retry (at-least-once); each agent is **idempotent per version**, so a
redelivered trigger is a no-op. The trigger sets its own tenant scope per §2.

## 5. Rate limiting — sensor ingestion

The Pi "sends continuously" (003 Q-6 OPEN — currently unanswered). Findings:
- Ingestion is the one endpoint under sustained load; it should be **rate-limited / backpressured
  per device credential**, not per user. Because the API **acks-and-enqueues** (§3), the limit
  protects the queue, not a synchronous validation path.
- Prefer **batch size caps + pagination limits** (003 FR-18) plus a per-gateway throughput ceiling
  over hard per-request rejection — dropping raw safety data is worse than shedding gracefully;
  Principle II keeps raw append-only, so backpressure must not silently lose readings.
- Concrete limits (batch max, per-device rate, burst) are **config a stakeholder supplies — do not
  guess** (mirrors the agents' config-TODO discipline).

## Open questions to resolve before spec/plan (do not guess)

**Resolved 2026-07-27:** stack/constitution version (**v2.1.0**, Neon/no-TimescaleDB, skills README
exists); **003 Q-3 gateway auth** (per-device API key, see §2); **alert-ack write endpoint** and
**muni-wide alerts list** (both adopted into the API surface, 004 Q-4 / Q-7).

**Still open:** 003 Q-2 enqueue-vs-sync ingestion; Q-4 async infra (BackgroundTasks vs durable
queue); Q-6 ingestion rate-limit *values* (config TODO); FFT/heatmap data availability (004 Q-2 —
may expand the API surface); n8n callback-routing owner for delivery/ACK webhooks.
