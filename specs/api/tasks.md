# API Layer — Tasks

**Status:** Draft for review (**do not write code until approved**)
**Date:** 2026-07-27
**Spec:** `specs/api/spec.md` (13 endpoints / 12 AC / 7 invariants — approved)
**Plan:** `specs/api/plan.md` (boundary-not-orchestrator; three credential classes; scope seam;
Arq + R2 signed URLs; five typed triggers)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.1.0** (Neon/Postgres,
standard B-tree indexes only, no TimescaleDB)

## Confirmed decisions (acceptance checks reference these + spec ACs)

- **Auth = two consumer principals + one internal.** Engineers/dashboard → **municipality-scoped
  JWT** with a tenant claim. Pi gateway → **per-device API key** (one per physical Pi, in the Pi's
  `.env`, never in code) resolving to **exactly one `bridge_id` + `municipality_id`** — **same RLS
  path, different credential shape**. n8n → **internal shared secret**, network-restricted.
- **The session GUC is `app.current_municipality_id`** — exactly this name, TEXT (no `::uuid`),
  set with `SET LOCAL` **before any query**, every request. Fail-closed.
- **Arq** (durable queue + worker) for report jobs; **job status persisted in Postgres**, not only
  Redis.
- **Ingestion = append + ack; DCA scheduler pickup** — no explicit "raw arrived" signal.
- **Report download = Cloudflare R2 signed URL** via the **S3-compatible SDK**, **15-minute TTL**.
- **Job row owned by the API layer; report artifact owned by Agent 4.** Neither writes the other's
  table.
- **`device_credentials` table owned by this layer** — hashed keys, revoke-not-delete.
- **Five explicit per-agent trigger endpoints** with typed scope keys (not one generic path).
- **Two analysis endpoints** (spectrum, heatmap) that **read** SA output and compute nothing.

## Conventions

- Each task is **< 1 hour** and **independently verifiable**; acceptance checks are concrete and tied
  to a spec **AC**, an invariant (**INV**), or a decision above — never "works correctly." Same
  granularity as the DCA/SA/Risk/Report/Alert/Database builds.
- **Test-first cadence** (unchanged): write the failing check → confirm red → implement → confirm
  green → **STOP**. Per the standing per-task cadence: show the change, run its acceptance check,
  confirm it passes, stop and wait before the next task.
- **[DB-DEP]** = needs a live Neon instance to fully verify (RLS filtering, FK enforcement, triggers
  only truly fire in-engine). Built/verified against **in-memory fakes** now, mirroring the
  `FakeTenantStore`/`FakeRiskStore`/`FakeAlertStore` pattern; live enforcement honestly deferred —
  **no Neon instance locally**.
- **[INFRA-DEP]** = needs Redis (Arq) or an R2 bucket. Built against a **fake queue / fake storage
  client** now; live verification deferred. Never silently marked done.
- **[AUTH-DEP]** = depends on the separate auth spec for real token issuance. Verified here against
  locally-minted test tokens; end-to-end verification deferred.
- **Task prefix `P`** (**P**erimeter/API) — no collision with DCA `T`, SA `S`, Risk `R`, Report `G`,
  Alert `A`, Database `D`. *(Note: `src/api/` already contains T001–T003 scaffolding from Spec 003 —
  app factory, error envelope, settings. Phase 1 audits and extends it rather than rebuilding.)*
- **No code is written until this task list is approved.** Every task describes *what* to build and
  *how it is checked*, not the implementation.

---

## Phase 1 — Foundation: audit existing scaffolding, settings, error envelope

`src/api/` already has an app factory, a structured error envelope, and settings from the earlier
Spec 003 work. This phase reconciles that to the current spec rather than duplicating it.

- **P101 — Audit existing scaffolding against `specs/api/spec.md`.**
  A written reconciliation of what `src/api/` already provides (app factory, `errors.py` envelope,
  `settings.py`, health router) versus what this spec requires; list what is reusable, what must
  change, what is missing. No behaviour change in this task.
  **Acceptance:** the note names every existing module and marks it keep / modify / replace, and
  identifies the envelope-field gap in P103. Reviewed before P102. = plan §0.

- **P102 — Settings for the confirmed stack.**
  Extend `settings.py` with config for: Arq/Redis, R2 (endpoint, bucket, credentials **from
  environment only**), signed-URL TTL (default **900 s**), rate-limit placeholders, JWT verification
  params. Secrets have **no usable defaults** — a missing secret is a startup error, not a silent
  insecure fallback.
  **Acceptance:** every new value is environment-overridable; instantiating settings with no R2/JWT
  secret in a production-mode flag **raises** rather than defaulting; TTL default is exactly 900 s.
  = decision (R2/TTL), INV-4.

- **P103 — Error envelope carries `detail`; assert no leakage.**
  The spec's envelope is `{error, code, detail, correlation_id}`; the built one omits `detail`. Add
  it, and ensure `code` carries the documented status semantics.
  **Acceptance:** a forced internal error returns all four fields; the body contains **no** stack
  trace, no SQL, no file path, no library name; full detail appears in the log against the same
  `correlation_id`. = **AC-5**, INV-4.

- **P104 — Status-code policy helpers (401/403/404/409/422/429).**
  One place that maps a failure class to its status, so handlers cannot improvise. Encodes the
  **404-not-403 for cross-tenant** rule and **403 = wrong credential class only**.
  **Acceptance:** a table-driven test asserts each failure class maps to its documented status; a
  cross-tenant failure maps to **404** and a wrong-credential-class failure to **403**; no handler
  constructs a status inline. = **AC-2**, **AC-7**, INV-3.

---

## Phase 2 — The tenancy seam (the highest-risk mechanism in the layer)

Nothing else may be built until a query **cannot** run unscoped. This phase is deliberately first.

- **P201 — `device_credentials` migration (0017) [DB-DEP].**
  New migration `0017_device_credentials.sql`: `credential_id` PK, `key_hash` (hashed, never
  plaintext), `bridge_id` + `municipality_id` (hard FKs, denormalized tenant per the established
  pattern), `device_label`, `status` (active|revoked), `created_at`, `last_used_at`, `revoked_at`.
  Index on `key_hash`. Header states Neon/Postgres, standard B-tree only, `[DB-DEP]`.
  **Acceptance:** a credential referencing a non-existent bridge is rejected (hard FK); `key_hash`
  is unique; **no column stores a plaintext key**; revocation is a `status` change — the migration
  provides **no** delete path. In-fake: a `FakeCredentialStore` mirrors these. = decision
  (`device_credentials`), plan §2a.

- **P202 — Scope-setting transaction primitive.**
  The single mechanism that opens a transaction and issues `SET LOCAL app.current_municipality_id`
  (parameterized, never string-built) before returning a usable handle.
  **Acceptance:** the exact GUC string is `app.current_municipality_id`, value passed as **TEXT**
  with no `::uuid` cast, using the **transaction-local** form (never session `SET`); a test asserts
  the emitted statement. = **AC-6**, INV-1.

- **P203 — Structural impossibility of an unscoped query.**
  The repository layer exposes **no** connection/session accessor outside the P202 primitive.
  **Acceptance:** a structural scan finds no code path that obtains a DB handle without a scope
  having been set; a deliberate attempt to query outside a scoped transaction **fails loudly** in
  tests rather than returning rows. = **AC-6**, INV-1/INV-2 (this is the "impossible to express,
  not merely reviewed" commitment).

- **P204 — Fail-closed on unresolvable scope.**
  A request whose credential yields no `municipality_id` never reaches a query.
  **Acceptance:** such a request returns **401** and executes **zero** queries (asserted by a
  spy/fake, not by inspection); and, independently, a query run with the GUC unset returns **zero
  rows** in the fake mirroring `current_setting(..., true) → NULL`. = **AC-6**, INV-1.

- **P205 — Scope does not leak across pooled requests.**
  Because `SET LOCAL` is transaction-scoped, request N+1 must not inherit request N's tenant.
  **Acceptance:** two sequential requests on the **same pooled connection** with different tenants
  each see only their own scope; after a transaction ends the GUC is unset (a third, unscoped query
  reads zero rows). = **AC-6**, INV-1, plan §3.

- **P206 — GUC-name regression guard.**
  A dedicated test pinning the exact GUC string against the 0016 policies.
  **Acceptance:** the test fails if the name drifts to `app.municipality_id` (Spec 003's wrong name)
  or any variant, and fails if a `::uuid` cast is introduced. = **AC-6**, plan §0 (this is the
  documented highest-risk carry-over: the wrong name silently returns zero rows everywhere).

---

## Phase 3 — Authentication and credential classes

- **P301 — `Principal` resolution contract.**
  One resolver producing a `Principal` carrying exactly one `municipality_id` (plus `bridge_id` for
  device keys, `user_id` for JWTs) and its **credential class**.
  **Acceptance:** each of the three credential classes resolves to exactly one `municipality_id`; an
  ambiguous or multi-tenant credential is **rejected**, never silently narrowed to the first tenant.
  = **AC-6**, **AC-7**, plan §2.

- **P302 — JWT verification + tenant claim extraction [AUTH-DEP].**
  Verify signature/expiry and extract the `municipality_id` claim.
  **Acceptance:** a valid token resolves; expired → **401**; bad signature → **401**; a token with
  **no** tenant claim → **401** (never a default tenant, never an unscoped pass). = **AC-6**,
  **AC-7**.

- **P303 — Pi API-key resolution via `device_credentials` [DB-DEP].**
  Hash the presented key, look it up, resolve `bridge_id` + `municipality_id`, reject revoked keys,
  update `last_used_at`.
  **Acceptance:** a valid active key resolves to exactly one `(bridge_id, municipality_id)`; a
  **revoked** key → **401**; an unknown key → **401**; the presented key is **never logged** and
  never compared in plaintext. = **AC-7**, decision (per-device key).

- **P304 — Per-endpoint credential-class allow-list.**
  Each endpoint declares which class it accepts; the default for an undeclared endpoint is
  **unreachable**, not open.
  **Acceptance:** Pi key on any read/report/trigger → **403**; JWT on `/ingest` or a trigger →
  **403**; internal secret on any consumer endpoint → **403**; a newly-added endpoint with no
  declared class is unreachable (proven by a structural test). = **AC-7**.

- **P305 — Internal trigger secret + network restriction.**
  Constant-time secret comparison, plus a network/origin restriction so a leaked secret alone is
  insufficient.
  **Acceptance:** a wrong secret → **403**; a correct secret from a disallowed origin → **403**; the
  secret is never logged and never returned in any response. = **AC-7**, plan §7.

- **P306 — Key rotation without a data gap.**
  Rotation = insert a new active credential, then revoke the old; both may be briefly active.
  **Acceptance:** during overlap **both** keys authenticate; after revocation the old one → 401 and
  the new one still works; **no key is ever overwritten in place** and no row is deleted. = plan §2a.

---

## Phase 4 — Ingestion (endpoint 1)

- **P401 — Reading batch input contract + shape validation.**
  Per-reading shape check: `sensor_id`, `sensor_type`, `value`, `unit`, `sensor_time`. Batch-size cap
  enforced.
  **Acceptance:** a well-formed batch parses; an oversized batch is rejected as a whole with the
  documented status; per-reading shape failures are **collected**, not raised. = **AC-1**, §8.

- **P402 — Closed-set rejection reasons.**
  An enumerated reason set (unknown sensor, sensor-not-on-this-bridge, malformed timestamp,
  missing/non-numeric value, unit mismatch).
  **Acceptance:** every rejection carries a reason from the closed set; an unlisted reason string is
  impossible to emit (enum-typed); the set is documented for gateway authors. = **AC-1**.

- **P403 — Per-reading results, never batch-level pass/fail.**
  A mixed batch returns one positional result per reading.
  **Acceptance:** given a batch of N with k bad, the response has exactly N results, the k failures
  name the right indices with reasons, and the **N−k valid readings are still appended**. = **AC-1**.

- **P404 — Cross-bridge readings rejected per-reading [DB-DEP].**
  A reading whose `sensor_id` is not on the key's `bridge_id` is rejected individually.
  **Acceptance:** such a reading is rejected **with a reason** (not an HTTP error, not silently
  re-attributed); the rest of the batch still processes; **no row is written** under another
  bridge's tenancy. = **AC-1**, **AC-2**.

- **P405 — Append-only raw write [DB-DEP].**
  Accepted readings append to `raw_readings`; no update/delete path exists anywhere in this layer.
  **Acceptance:** a structural scan finds **no** UPDATE/DELETE against raw tables in `src/api/`;
  appends are observable in the fake; re-appending a duplicate does not overwrite. = Principle II.

- **P406 — Duplicate/redelivered tolerance.**
  A Pi retrying after a network failure is normal traffic.
  **Acceptance:** redelivering an identical batch does not report failure to the caller and does not
  corrupt the append log. = §4.

- **P407 — Ack semantics: accepted ≠ validated; no DCA signal.**
  The response means "durably appended," not "valid."
  **Acceptance:** the response contains **no** validation verdict; a structural test asserts the
  ingest path **enqueues nothing** and invokes no agent (DCA scheduler pickup). = decision
  (scheduler pickup), plan §4.

- **P408 — Ingestion audit record.**
  **Acceptance:** each ingest write records timestamp, principal, tenant, and the causing request.
  = INV-5, Principle VI.

---

## Phase 5 — Read endpoints (2, 3, 4, 5)

- **P501 — `GET /bridges` overview projection [DB-DEP].**
  Current, non-superseded assessments joined to in-scope bridges; paginated.
  **Acceptance:** returns one item per in-scope bridge with score/severity/last-assessed; **no raw
  reading history is scanned** (asserted structurally); another tenant's bridges are absent.
  = **AC-2**, §6.

- **P502 — Null-honest projection for missing/withheld scores.**
  **Acceptance:** a bridge with no assessment, and one whose assessment **withheld** its score, both
  return `risk_score: null` — **never `0`** — and the withheld case carries the **verbatim** withheld
  reason. = **AC-8**, INV-6.

- **P503 — No band thresholds anywhere in this layer.**
  Bands are read from the assessment row, never computed.
  **Acceptance:** a structural scan finds **no** 0–30 / 31–60 / 61–80 / 81–100 mapping and no band
  derivation in `src/api/`; severity values are pass-through. = Principle III, plan §6.

- **P504 — `GET /bridges/{id}` detail + sensor list [DB-DEP].**
  **Acceptance:** returns the bridge, its sensors with `status`/`last_reading_at`, and `current_risk`
  when present; an out-of-scope or unknown `bridge_id` → **404**. = **AC-2**, INV-3.

- **P505 — `GET .../readings` time-series [DB-DEP].**
  Range or window selection; `status` and `is_interpolated` passed through.
  **Acceptance:** interpolated points and gaps are **marked, not smoothed**; a sensor not on the
  named bridge → 404; results are ordered and bounded. = §6, Principle II.

- **P506 — Pagination defaults + enforced hard maximum.**
  **Acceptance:** every list/time-series endpoint applies a default page size and **caps** an
  over-large request rather than honouring it; no request can return an unbounded series.
  = spec §4/§6, plan Open Item 4.

- **P507 — `GET /bridges/{id}/risk` with verbatim explanation [DB-DEP].**
  **Acceptance:** returns the **current** assessment with its `assessment_version`, `review_status`,
  and provenance; `explanation` is **byte-for-byte** the stored text (no truncation, no
  re-wording). = **AC-8**, INV-7.

- **P508 — Score is structurally inseparable from its WHY.**
  **Acceptance:** the response model makes `explanation` non-optional wherever `risk_score` is
  present — serializing a score without its explanation is **impossible to express**, not merely
  untested. = **AC-8**, INV-7, Principle I.

- **P509 — `review_status` always surfaced.**
  **Acceptance:** a `PENDING_HUMAN_REVIEW` assessment is never presented as settled; the field is
  always present in risk-bearing responses. = **AC-8**, Risk FR-11.

---

## Phase 6 — Analysis endpoints (12, 13)

- **P601 — `GET .../spectrum` projects SA FFT output [DB-DEP].**
  **Acceptance:** returns bins + dominant frequency read from `analysis_results`, naming the
  `analysis_id`; a structural scan finds **no FFT computation** in `src/api/`. = INV-6, decision
  (two analysis endpoints).

- **P602 — `GET /bridges/{id}/heatmap` projects SA strain output [DB-DEP].**
  **Acceptance:** returns per-gauge cells with `vs_limit` **read from** the analysis row — the
  comparison is **not** recomputed here; names its `source_analysis_ids`. = INV-6.

- **P603 — Explicit not-available, never an empty chart.**
  **Acceptance:** no spectrum for that sensor type / no strain array on that bridge / no analysis for
  the cycle each return an explicit not-applicable-or-unavailable state — **never** an empty bin list
  or a zero-filled grid (which would read as "fine"). = INV-6, plan §6a.

- **P604 — Heatmap degrades gracefully without gauge positions.**
  **Acceptance:** when layout is unknown, cells are returned keyed by `sensor_id` and the response
  says positions are unavailable; the endpoint does not fail. = plan Open Item 6.

---

## Phase 7 — Report jobs: Arq + R2 (endpoints 6, 7, 8)

- **P701 — Report job table (0018) owned by this layer [DB-DEP].**
  `job_id`, requester principal, `bridge_id`, scope (assessment identity / range), `status`,
  `error_code`, `error_detail`, `artifact_version`, timestamps.
  **Acceptance:** the migration creates a job table this layer owns; a structural check asserts this
  layer **never writes `report_artifacts`** (Agent 4's table) and the agent never writes the job row.
  = decision (job/artifact split), plan §5a.

- **P702 — Closed four-state job status.**
  **Acceptance:** `PENDING | RUNNING | COMPLETE | FAILED` is enum-typed; no fifth value is
  representable; illegal transitions (e.g. COMPLETE → RUNNING) are rejected. = **AC-9**, §5.

- **P703 — `POST /bridges/{id}/reports` accepts in <500 ms [INFRA-DEP].**
  Create the job row, enqueue to Arq, return immediately.
  **Acceptance:** with a **stubbed 30-second** render, the endpoint returns `{job_id, PENDING}` in
  **under 500 ms**; the job row exists before the response is sent. = **AC-3**.

- **P704 — Job status is answerable from Postgres alone [INFRA-DEP].**
  **Acceptance:** with Redis flushed/unavailable, `GET /reports/{job_id}/status` still returns the
  job's last known status — a job is never unanswerable. = **AC-3**, plan §5.

- **P705 — Arq worker triggers Agent 4 by scope key [INFRA-DEP].**
  **Acceptance:** the worker passes a **scope key only** (no report content) and does **not** render;
  a structural scan finds no PDF assembly, no templating, and no chart generation in `src/api/`.
  = Principle III, Report FR-4.

- **P706 — Agent outcome → job status mapping.**
  **Acceptance:** every Report Agent outcome maps to exactly one job status; `WITHHELD/*` maps to
  **FAILED with a structured `code`**; the mapping is total (no outcome falls through) and emits
  **no stack trace**. = **AC-9**, INV-4.

- **P707 — Worker retries infrastructure failures only.**
  **Acceptance:** a transient worker/infra failure is retried; a **determinate** agent outcome
  (`WITHHELD`) is **not** retried; retry counts are bounded and exhaustion lands the job in FAILED
  with a reason — never an infinite loop, never a silently abandoned job. = plan §5.

- **P708 — Job durability across worker restart [INFRA-DEP].**
  **Acceptance:** a job enqueued and then interrupted by a worker restart still reaches COMPLETE or
  FAILED; it never lingers in RUNNING forever. = **AC-3**.

- **P709 — Idempotent report request.**
  **Acceptance:** requesting a report for an already-rendered **current** assessment returns the
  existing job/artifact rather than queueing duplicate work. = Report FR-10.

- **P710 — R2 storage client behind an S3-compatible interface [INFRA-DEP].**
  **Acceptance:** the client is written against the **S3 interface** with R2 as a configured
  endpoint; the provider is swappable without touching handler logic; credentials come **only** from
  environment config and are never logged. = decision (R2 / S3 SDK).

- **P711 — 15-minute signed URL, read-only, single-object [INFRA-DEP].**
  **Acceptance:** the generated URL expires in **exactly 900 s**, grants **read of one object only**
  (no listing, no write), and the URL is **never written to logs**. = decision (TTL), §5.

- **P712 — Download authorises before signing.**
  **Acceptance:** a signed URL is issued **only** after a fresh tenant-scope check; another tenant's
  `job_id` → **404** and **no URL is generated**; an expired URL is **re-issued** (new authorisation
  check), never extended. = **AC-2**, **AC-9**.

- **P713 — Strict `COMPLETE` gating.**
  **Acceptance:** PENDING/RUNNING → **409** (retryable); FAILED → **409** with the structured
  reason; COMPLETE → signed URL; a partially-rendered document is **never** reachable. = **AC-9**.

- **P714 — Report request + download audited.**
  **Acceptance:** report creation and each download access record timestamp, principal, tenant, and
  request. = INV-5, Principle VI.

---

## Phase 8 — Alerts (endpoints 9, 9-wide, 10)

- **P801 — `GET /bridges/{id}/alerts` read-only status [DB-DEP].**
  **Acceptance:** returns dispatch/escalation/approval state per alert; a structural scan finds
  **no** dispatch, retry, or escalation logic in `src/api/`. = **AC-11**, Alert FR-5.

- **P802 — Municipality-wide alerts list [DB-DEP].**
  **Acceptance:** returns in-scope alerts across all the tenant's bridges, sortable by severity and
  bridge, paginated; another tenant's alerts are absent. = **AC-2**, 004 Q-7.

- **P803 — Unacknowledged alerts persist across calls [DB-DEP].**
  **Acceptance:** an unacknowledged **CRITICAL** alert appears on **every** call until explicitly
  acknowledged; a **DELIVERED-but-unacknowledged** alert is **still listed** (delivery does not
  remove it); after acknowledgement it reports acknowledger + timestamp. = **AC-4**, Alert FR-6.

- **P804 — Distinct delivery states surfaced honestly.**
  **Acceptance:** `SENT`, `DELIVERED`, and `ACKNOWLEDGED` are distinct in the response and never
  collapsed into a single "sent" boolean. = Alert FR-7.

- **P805 — `POST /alerts/{id}/acknowledge`, identity from the credential [DB-DEP].**
  **Acceptance:** the acknowledger is taken from the **JWT**, never from the request body (a
  body-supplied identity is ignored/rejected); the write is **appended**, not an overwrite of
  dispatch history. = **AC-4**, INV-5, Alert FR-13.

- **P806 — Acknowledgement idempotency preserves the first acknowledger.**
  **Acceptance:** re-acknowledging returns the **original** acknowledger and timestamp unchanged; a
  second caller cannot overwrite who acknowledged first. = **AC-4**.

- **P807 — Acknowledgement causes no outbound action.**
  **Acceptance:** a structural test asserts the ack path sends **nothing** (no notifier, no
  dispatch) and does **not** touch the approval gate — ack ≠ approval. = **AC-11**, Alert FR-5.

---

## Phase 9 — n8n triggers (endpoint set 11)

- **P901 — Five typed scope-key contracts.**
  One per agent, each with its own required fields (SA carries **both** `validated_ids` and
  `superseded_ids`; Risk is per-bridge; Report/Alert per-assessment).
  **Acceptance:** each endpoint validates **its own** required fields; an incomplete scope key →
  **422**; SA rejects a request missing **either** id list. = **AC-10**, decision (five endpoints).

- **P902 — Scope key only; no payload data accepted.**
  **Acceptance:** a trigger carrying reading/analysis **content** (not ids) is **rejected**; a
  structural test asserts no agent is invoked with content copied from the request. = Report FR-4,
  Alert FR-1.

- **P903 — Accept-and-ack; never block.**
  **Acceptance:** the endpoint returns immediately with `{accepted, run_id}` even when the agent
  entrypoint is stubbed slow; the response does not wait for agent completion. = plan §7.

- **P904 — Trigger idempotency is the agent's; the API adds none.**
  **Acceptance:** a redelivered trigger produces no duplicate report and no double dispatch; a
  structural test asserts the API implements **no** dedup layer of its own (one notion of
  "already handled"). = **AC-10**.

- **P905 — Triggers implement no agent logic.**
  **Acceptance:** a structural scan finds no validation, math, scoring, rendering, or templating in
  the trigger path — only scope validation, scope-setting, and hand-off. = Principle III.

- **P906 — No approval surface; the chokepoint stays in the agent.**
  **Acceptance:** a structural test asserts **no** API endpoint approves a gated dispatch and the
  Alert trigger cannot bypass `needs_approval`. = **AC-11**, Alert FR-5 (single un-bypassable
  chokepoint).

---

## Phase 10 — Cross-cutting hardening

- **P1001 — Rate limiting per Pi key and per JWT.**
  **Acceptance:** ingestion is limited **per device key**, other endpoints **per JWT**; breach
  returns **429** with a `Retry-After` header in the structured envelope; limit **values** are
  config, defaulted as TODO placeholders and **not guessed**. = **AC-12**.

- **P1002 — Backpressure never drops readings.**
  **Acceptance:** a rate-limited or oversized batch is **explicitly rejected** (retryable) — the API
  never accepts a batch and silently drops a subset; a test asserts no partial absorption.
  = **AC-12**, Principle II.

- **P1003 — Cross-tenant isolation sweep across every endpoint [DB-DEP].**
  The single most important test in the layer.
  **Acceptance:** for **every** endpoint, municipality A's JWT presented with B's valid
  `bridge_id` / `sensor_id` / `job_id` / `alert_id` returns **404** with **zero** rows of B's data in
  any field — reads, report flow, alerts, and analysis endpoints alike. = **AC-2**.

- **P1004 — No real-world action anywhere in the layer.**
  **Acceptance:** a structural scan over `src/api/` finds no notifier, mailer, SMS client, publish,
  or dispatch path, and no approval endpoint. = **AC-11**, Principle I.

- **P1005 — Global no-leak error sweep.**
  **Acceptance:** every endpoint's failure paths return the envelope; a fuzz/forced-error pass finds
  no stack trace, SQL fragment, internal id, or file path in any response body. = **AC-5**, INV-4.

- **P1006 — Audit coverage for every write.**
  **Acceptance:** ingest, report-create, report-download, and alert-ack each produce an audit record
  with timestamp, principal, tenant, and causing request; a write path with no audit record fails
  the test. = INV-5, Principle VI.

- **P1007 — OpenAPI documents every endpoint.**
  **Acceptance:** the generated schema lists all 13 endpoints with their auth requirement and error
  envelope; an undocumented endpoint fails the check. = 003 AC-5 (carried forward).

- **P1008 — Full-suite regression gate.**
  **Acceptance:** the entire repo suite is green (no new failures, no new skips beyond documented
  `[DB-DEP]`/`[INFRA-DEP]`), and every deferred item is explicitly marked — never silently passing.
  = plan §9.

---

## Coverage check (tasks ↔ acceptance criteria)

| AC | Tasks |
|---|---|
| **AC-1** per-reading ingestion | P401, P402, P403, P404 |
| **AC-2** tenant isolation absolute | P104, P404, P501, P504, P712, P802, **P1003** |
| **AC-3** report accept <500 ms | P703, P704, P708 |
| **AC-4** unacked CRITICAL persists | P803, P805, P806 |
| **AC-5** structured errors only | P103, P1005 |
| **AC-6** scope set before query | P202, P203, P204, P205, **P206**, P301, P302 |
| **AC-7** credential separation | P104, P301, P302, P303, P304, P305 |
| **AC-8** score never without WHY | P502, P507, **P508**, P509 |
| **AC-9** download gating | P702, P706, P712, P713 |
| **AC-10** trigger idempotency | P901, P904 |
| **AC-11** no real-world action | P801, P807, P906, **P1004** |
| **AC-12** rate-limit shape | P1001, P1002 |
| INV-6 no computation in the API | P503, P601, P602, P603, P705 |
| Principle II append-only | P405, P1002 |
| Principle VI audit | P408, P714, P1006 |

Every AC has at least two independent tasks; **AC-2** and **AC-6** — the tenancy guarantees — have
the deepest coverage, and **P206** exists solely to prevent the one silent-failure regression the
plan identified.

## Dependency order

```
Phase 1 (foundation)
   └─► Phase 2 (TENANCY SEAM — blocks everything)
          └─► Phase 3 (auth)
                 ├─► Phase 4 (ingest)
                 ├─► Phase 5 (reads) ─► Phase 6 (analysis reads)
                 ├─► Phase 7 (report jobs)
                 ├─► Phase 8 (alerts)
                 └─► Phase 9 (triggers)
                        └─► Phase 10 (hardening + sweeps)
```

- **Phase 2 is a hard gate.** No endpoint is built before a query is structurally unable to run
  unscoped — building endpoints first would mean retro-fitting isolation, which is how tenancy leaks
  happen.
- Phases 4–9 are largely parallel once auth lands.
- Phase 10's sweeps (P1003, P1004, P1005) must run **last** — they assert properties across the
  whole surface and are meaningless before it exists.

## Deferred verification (honest status)

- **[DB-DEP]** — real RLS filtering, FK enforcement, and trigger behaviour need a **live Neon
  instance** (none locally). Verified against in-memory fakes mirroring the 0016 predicate; **P1003
  is fake-verified until an instance exists** and must be re-run live before any production claim.
- **[INFRA-DEP]** — Arq/Redis and R2 need real infrastructure; verified against a fake queue and
  fake storage client. P703/P704/P708/P710/P711 are honestly deferred for live confirmation.
- **[AUTH-DEP]** — real token issuance belongs to the separate auth spec; verified here with
  locally-minted test tokens.

**Nothing marked deferred is counted as passing.**

## Open items carried into implementation (config — do not guess)

1. Ingestion rate limit per Pi key (steady rate, burst, max batch size) — needs expected
   readings/min per device.
2. Per-JWT rate limits for read endpoints.
3. Report status poll interval + max wait recommended to the dashboard.
4. Pagination defaults and hard maximums per list endpoint (P506 enforces *that* a cap exists; the
   values are config).
5. **R2 bucket layout + retention** — object key scheme (must not leak tenant identity in a
   guessable path) and artifact retention policy. Provider and TTL are settled; bucket policy is not.
6. Gauge position/layout source for the heatmap (P604 fallback already settled).
7. n8n callback routing for delivery receipts / ACK webhooks — if it becomes an API surface it needs
   a credential class and must **not** become a second dispatch path.
8. Redis deployment posture for Arq (managed vs self-hosted).
9. ~~`device_credentials` (0017) and report-job (0018) migration numbers — confirm no collision if the
   DB layer appends further migrations first.~~ **CLOSED 2026-07-31.** `db/migrations/` holds
   0001–0016 with no gaps; `0016_rls_policies.sql` is the highest. **0017 and 0018 are free.** If a
   future layer claims them first, renumber P201/P701 rather than reusing a slot.
