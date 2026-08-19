# P101 — Scaffolding Audit: `src/api/` vs `specs/api/spec.md`

**Task:** P101 (Phase 1). **Date:** 2026-07-31.
**Verdict scope:** **7 modules** audited (plus 2 empty package markers, nothing to reconcile).
**This task makes no behaviour change** — it records decisions only. Every fix below is assigned to
a later task.

`src/api/` was scaffolded under Spec 003 (T001–T003) before `specs/api/spec.md` existed. The
question this note answers is not "does it work" (11 tests pass) but "does it still say the right
thing." Phase 1 extends it; it does not rebuild it.

---

## Module-by-module verdict

| # | Module | Verdict | Reason |
|---|---|---|---|
| 1 | `src/api/__init__.py` | **KEEP** | Docstring already states the boundary role and the two invariants that survived into the spec (structured errors, audited writes). Accurate as written. |
| 2 | `src/api/main.py` | **MODIFY** | App factory is sound and import-light. Needs: the scope middleware seam (Phase 2), auth dependencies (Phase 3), and 12 more routers. Its docstring already anticipates "middleware in later tasks." No rewrite. |
| 3 | `src/api/errors.py` | **MODIFY** | Two gaps — see **Finding 1** and **Finding 2**. The no-leak behaviour is correct and must not regress. → **P103** |
| 4 | `src/api/schemas/errors.py` | **MODIFY** | `ErrorResponse` is `{error, code, correlation_id}`; the spec's envelope is `{error, code, detail, correlation_id}`. The **`detail` field is missing.** → **P103** |
| 5 | `src/api/schemas/common.py` | **MODIFY** | `PageParams` / `Page` are reusable as-is, but the page caps are hardcoded — see **Finding 3**. → **P506** |
| 6 | `src/api/settings.py` | **MODIFY** | Loads cleanly and is env-overridable, but ships an insecure secret default — see **Finding 4**. Missing all confirmed-stack config (Arq/Redis, R2, TTL, rate limits). → **P102** |
| 7 | `src/api/routers/health.py` | **KEEP** | Correct as a DB-independent liveness probe. One documentation tension — see **Finding 5**. |

Empty package markers (`routers/__init__.py`, `schemas/__init__.py`): **KEEP**, no content.

---

## Findings

**Finding 1 — the envelope omits `detail` (the gap P101 was asked to identify).**
Spec §Error responses requires `{error, code, detail, correlation_id}`. The built envelope has three
of four fields. Without `detail`, a 422 cannot say *which* field failed and a `FAILED` report job
cannot carry its structured reason — both are spec requirements (AC-5, §Async job model).
**Assigned: P103.** Not fixed here.

**Finding 2 — `error` and `code` are inverted relative to the spec.**
The spec reads `error: <short machine code>`, `code: <http status>`. The built code does the
opposite: `error` gets the human message (`"I'm a teapot"`), `code` gets a machine string
(`"http_418"`). Both are self-consistent, but they disagree, and the dashboard will branch on
whichever ships. P103 must pick one and state it — this is a contract decision, not a rename.
*Recommendation:* keep the built shape (`error` = message, `code` = stable machine code) and correct
the **spec** text, because a machine code is more useful to a client than an HTTP status already
present in the status line. **Needs your call at P103.**

**Finding 3 — page caps are duplicated.**
`PageParams` hardcodes `default=50` / `le=500`; `settings.py` independently declares
`default_page_size = 50` / `max_page_size = 500`. Two sources of truth that will silently diverge
the first time one is tuned. P506 (pagination cap) should make the schema read the settings.

**Finding 4 — an insecure secret has a usable default.**
`settings.py:20` — `jwt_secret: str = "dev-insecure-change-me"`. This is exactly the
silent-insecure-fallback P102 forbids: deploy with the env var unset and the app boots and validates
tokens against a public string. **Assigned: P102** (missing secret = startup error).

**Finding 5 — `/v1/health` vs "no endpoint is unauthenticated."**
Spec §Authentication ends: "**No endpoint is unauthenticated.** There is no anonymous surface."
`/v1/health` is anonymous. A liveness probe legitimately must be — but the spec currently forbids it
by implication. Resolve by naming health as an explicit, documented carve-out that exposes **no
tenant data and no system state beyond "the process is up"** (the current implementation already
satisfies that: it returns a literal `{"status": "ok"}` and touches nothing). Note it in P1007's
OpenAPI check so it can never quietly grow a DB touch or a version/build disclosure.

**Finding 6 — an existing test will break when P103 lands (expected, not a defect).**
`tests/api/test_t002_errors.py:44,66` assert `set(body.keys()) == {"error", "code",
"correlation_id"}` — an exact-set assertion. Adding `detail` turns both green tests red. That is the
assertion doing its job. P103 must update these two lines *deliberately* and keep the exact-set form
(a loose `>=` check would stop catching accidental field leakage into the envelope).

---

## What is reusable, unchanged

- The **no-leak discipline** in `handle_unexpected_error`: full traceback to `logger.exception`, only
  a correlation id to the client. This is INV-4 already built and tested (`test_no_internal_detail_leaks`
  asserts the secret, the exception class name, and "Traceback" are all absent). Must not regress.
- **Three handlers registered globally** (`HTTPException`, `RequestValidationError`, bare
  `Exception`) — the bare-`Exception` catch-all is what makes "no stack trace ever" structural
  rather than per-handler diligence.
- The **`httpx.ASGITransport`** test fixture in `tests/api/conftest.py`, including its
  `raise_app_exceptions=False` variant — required to test 500s at all. Reuse for every phase.
- `PageParams.offset` / `Page.has_next` arithmetic.

---

## Missing surface (absent, not broken)

Nothing below exists yet; all are later phases. Listed so "reusable" is not misread as "sufficient."

| Area | State | Phase |
|---|---|---|
| **Auth** — JWT verification, Pi API-key resolution, n8n shared secret, credential-class separation | **absent**. `settings.py` has `jwt_secret` / `gateway_key_store` placeholders and nothing reads them. | 3 |
| **Tenant scope seam** — `SET LOCAL app.current_municipality_id` before any query | **absent**. No DB connection layer exists at all. The highest-risk mechanism in the layer is entirely unbuilt. | **2 (hard gate)** |
| **`device_credentials`** table (migration 0017) | **absent**. Slot confirmed free 2026-07-31. | 2 |
| Endpoints 1–13 | **absent**. Only `/v1/health` exists — 0 of 13. | 4–9 |
| Status-code policy (404-not-403 cross-tenant; 403 = wrong credential class) | **absent**. `handle_http_exception` passes through whatever status a handler raises. | 1 (P104) |
| Arq queue + worker, report job row (0018), R2 signed URLs | **absent**. `queue_url` is declared and unused. | 7 |
| Rate limiting, `Retry-After` | **absent**. | 10 |
| Audit-on-write | **absent**. | 10 |

---

## Carried into later tasks

| Finding | Task | Status |
|---|---|---|
| 1 — envelope missing `detail` | **P103** | **DONE** — added to `ErrorResponse`; populated safe-by-construction. |
| 2 — `error`/`code` inversion | **P103** | **DONE** — built shape kept, **spec text corrected** (approved 2026-07-31). |
| 3 — duplicated page caps | **P506** | open |
| 4 — insecure `jwt_secret` default | **P102** | **DONE** — all secrets `SecretStr \| None`; production mode raises. |
| 5 — health carve-out from "no anonymous surface" | **P1007** (+ spec note) | spec note **DONE**; structural guard open at P1007. |
| 6 — `test_t002` exact-set assertions | **P103** | **DONE** — both lines updated, exact-set form kept. |

**Baseline:** `tests/api` = 11 passed before this task and 11 passed after (this note adds checks,
not behaviour). No production module was edited in P101.
