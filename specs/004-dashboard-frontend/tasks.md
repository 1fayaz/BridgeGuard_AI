# Tasks: Dashboard / Frontend

**Feature:** `004-dashboard-frontend`
**Created:** 2026-06-20
**Status:** Draft — awaiting review before implementation
**Plan:** `specs/004-dashboard-frontend/plan.md`
**Spec:** `specs/004-dashboard-frontend/spec.md`
**Constitution:** v2.1.0

## Conventions

- **[P]** = parallelizable once its phase's prerequisites are met.
- Each task < 1 hour, one clear **Done** condition.
- Everything builds against the **typed mock API** (mirrors Spec 003 contract), so
  tasks are verifiable **now** without a live backend.
- **[API-DEP]** = wired to a Spec 003 endpoint that is planned but **not implemented**;
  verified against the mock, re-verified against live API later.
- **[API-GAP]** = depends on an endpoint absent from Spec 003. *(Update 2026-07-27:
  **alert-ack** and **muni-wide alerts** are now specified in `specs/api/spec.md`; **FFT
  data** and **heatmap data** remain genuine gaps.)* Built against a mock + a documented
  assumed contract; **blocked from live** until the API provides it.
- Constitution rules enforced throughout: every data view has loading/empty/error
  (Principle IV); risk score never renders without its reasoning_text (Principle I);
  alert-ack is an audited API write (Principle VI).

---

## Phase 1 — Project Scaffolding

- **T001 — Vite + React + TS app.**
  `frontend/` via Vite react-ts template; app builds and serves.
  **Done:** `npm run dev` serves a placeholder; `npm run build` succeeds; `tsc` clean.

- **T002 — [P] Tailwind + design tokens.**
  Install Tailwind; add `design/` tokens: risk-band palette (Safe/Watch/Warning/
  Critical from math-analysis), typography, spacing (plan §7, Q-1).
  **Done:** a token swatch page renders the 4 band colors; Tailwind classes apply.

- **T003 — [P] shadcn/ui + base layout shell.**
  Init shadcn/ui (Q-10); app shell with nav placeholder.
  **Done:** a shadcn Button + Card render styled; shell visible.

- **T004 — Routing skeleton (React Router).**
  Routes per plan §2: `/login /, /bridges/:id /reports /alerts /settings *`.
  Each renders a named placeholder.
  **Done:** navigating each path shows the right placeholder; unknown → NotFound.

- **T005 — Typed mock API layer.**
  `api/types.ts` (BridgeOverviewItem, RiskScoreView, SensorSeries, ReportJobView,
  AlertItem), `api/client.ts` (auth header, structured-error → typed result),
  `api/mock/` returning realistic fixtures; one flag swaps mock↔live.
  **Done:** unit test — each typed endpoint fn returns correctly-shaped fixture data.

---

## Phase 2 — Auth Flow

- **T101 — Auth state + token handling.**
  Token in memory; refresh per plan §5; 401 → refresh once → else logout. (Storage per
  Q-8.)
  **Done:** unit test — 401 triggers one refresh then redirect; token attaches to
  requests.

- **T102 — Login page. [API-DEP: auth spec]**
  `/login` form → auth endpoint (mocked) → stores token → redirects to intended route.
  **Done:** valid creds → redirect to `/`; invalid → clean inline error (no blank).

- **T103 — ProtectedRoute.**
  Wrap all non-login routes; unauthenticated → redirect to `/login` preserving target.
  **Done:** component test — unauth access redirects; authed renders child.

---

## Phase 3 — Overview Page (US-1, AC-1)

- **T201 — BridgeCard component. [API-DEP /overview]**
  Name, score, band color (from §7 tokens) + label + icon (color never sole signal).
  Whole card links to detail.
  **Done:** FT-1 — each score maps to correct band token + label + icon.

- **T202 — OverviewGrid + data hook.**
  `useOverview` (React Query, staleTime ~60s); responsive grid 1→2→3→4 cols.
  **Done:** grid renders mock bridges; manual refresh works.

- **T203 — Sort/filter by risk band.**
  Critical/Warning surfaced first; filter control.
  **Done:** sorting puts highest band first; filter narrows list.

- **T204 — Overview states (loading/empty/error).**
  Via `<StateBoundary>` (built in T1201 — dep).
  **Done:** FT-2 — all four states render; never blank.

---

## Phase 4 — Bridge Detail (US-2, US-3, AC-2)

- **T301 — Bridge Detail layout.**
  Header (bridge name/zone), gauge slot, explanation slot, sensors section, Request
  Report button slot.
  **Done:** layout renders for a mock bridge id; responsive scaffold present.

- **T302 — RiskGauge component. [API-DEP /risk-score]**
  Recharts RadialBar 0–100 + band label; color from §7 tokens.
  **Done:** FT-3a — gauge shows correct value + band for sample scores.

- **T303 — RiskExplanation component (Principle I).**
  Renders `reasoning_text` beside the gauge; if missing → explicit "explanation
  unavailable" notice (never a silent bare number).
  **Done:** FT-3b — reasoning_text always present with the score; missing → notice.

- **T304 — SensorChart component. [API-DEP /sensors/:sid/readings]**
  Recharts interactive time-series; **30/90/365** range selector + zoom (AC-3).
  **Done:** FT-4a — range switch refetches window; zoom works.

- **T305 — Data-quality marking in SensorChart (FR-8, Principle II).**
  Mark interpolated points + NO_DATA gaps distinctly (not silently smoothed).
  **Done:** FT-4b — interpolated/gap points visually distinct from raw.

- **T306 — [P] FftSpectrum component. [API-GAP — Q-2]**
  Plotly frequency plot for vibration sensors.
  **Done (mock):** renders against assumed FFT fixture. **Blocked from live** until
  Spec 003 exposes FFT data — flagged, not counted as live-done.

---

## Phase 5 — DeckHeatmap

- **T401 — DeckHeatmap component. [API-GAP — Q-2]**
  D3 heatmap across deck zones from the strain-gauge array.
  **Done (mock):** renders a colored grid from assumed heatmap fixture; band-consistent
  colors. **Blocked from live** until Spec 003 exposes heatmap data — flagged.

---

## Phase 6 — Reports (AC-4)

- **T501 — ReportRequestModal. [API-DEP POST /reports]**
  Date-range picker → create job → pending state with job_id.
  **Done:** FT-5 — submit → pending UI with returned job_id.

- **T502 — Report status polling hook. [API-DEP /reports/:job/status]**
  React Query polling at the chosen interval (Q-3) until done/failed.
  **Done:** FT-6a — polls until done; stops on done/failed.

- **T503 — Download + failure UX. [API-DEP /reports/:job/download]**
  On done → download action; on failed → clean error (no blank, Principle IV).
  **Done:** FT-6b — done → download enabled; failed → structured error message.

- **T504 — [P] Reports list page.**
  `/reports` lists requested jobs + status + download.
  **Done:** list renders mock jobs with correct status badges.

---

## Phase 7 — Alerts (US-5, AC-5)

- **T601 — AlertList component. [API-GAP GET /v1/alerts — Q-7]**
  Muni-wide list; sortable by severity and bridge.
  **Done (mock):** FT-7a — sortable by severity/bridge. **Blocked from live** until
  Spec 003 adds muni-wide alerts — flagged.

- **T602 — Acknowledge action. [API-GAP POST /v1/alerts/:id/ack — Q-4]**
  Ack triggers an **audited API write**; optimistic update + invalidate.
  **Done (mock):** FT-7b — ack updates state optimistically; calls the (mock) audited
  endpoint. **Blocked from live** until Spec 003 adds the ack write — flagged.

- **T603 — [P] AlertTimeline (optional, visual-output).**
  Recharts ComposedChart of the event log.
  **Done:** renders from mock event fixture.

---

## Phase 8 — Cross-cutting (Responsive + States)

- **T701 — StateBoundary component (built early-needed). [PRIORITY]**
  Shared loading(skeleton)/empty/error(+retry, shows correlation_id)/success wrapper.
  *Note: this is a dependency of T204 etc.; implement first in practice.*
  **Done:** FT-8 — all four states render correctly; error surfaces correlation_id.

- **T702 — Responsive/tablet pass (AC-6).**
  Audit every page at `md`/`lg`; grid reflow; chart min-heights; touch targets ≥44px.
  **Done:** FT-10 — pages usable at tablet breakpoints; no horizontal overflow of
  controls; targets ≥44px.

- **T703 — Error-message mapping.**
  Map API structured error `{error,code,correlation_id}` → friendly copy across views.
  **Done:** forced mock error → friendly message + small correlation_id; no raw codes
  leaked as primary text.

---

## Phase 9 — Tests

- **T801 — Component test suite (Vitest + RTL).**
  FT-1…FT-10 from plan §9 as runnable tests against the mock API.
  **Done:** suite green; covers band colors, 4 states, gauge+explanation, chart
  interactivity, report flow, alert sort/ack, protected route, responsive smoke.

- **T802 — E2E: view bridge → request report → download (Playwright).**
  Full happy path against the mock API incl. poll→ready→download (E2E-1).
  **Done:** E2E-1 green end to end.

- **T803 — [P] E2E: overview → drill-in (E2E-2).**
  Click card → detail shows gauge + explanation + charts.
  **Done:** E2E-2 green.

---

## Dependency Order

```
Phase 1 (scaffold + mock API + StateBoundary[T701 pulled early])
   └─► Phase 2 (auth) ─► Phase 3 (overview)
                     ├─► Phase 4 (detail) ─► Phase 6 (reports)
                     ├─► Phase 5 (heatmap)        [API-GAP]
                     └─► Phase 7 (alerts)         [API-GAP]
                                   └─► Phase 8 (responsive/states) ─► Phase 9 (tests)
```
- **T701 (StateBoundary) is logically Phase 8 but is a prerequisite of T204 and every
  state test — build it right after Phase 1.**
- Phases 4/5/6/7 are largely parallel after auth + the mock API land.

## Coverage Check (tasks ↔ acceptance criteria)

| AC | Task(s) |
|----|---------|
| AC-1 fast color-coded overview | T201–T204 (perf re-verified vs live API later) |
| AC-2 detail: score+explanation+charts+report btn | T301–T305, T501 |
| AC-3 interactive charts | T304 |
| AC-4 report flow + notify (poll) | T501–T503 |
| AC-5 alerts sort + ack | T601, T602 **[API-GAP]** |
| AC-6 responsive/tablet | T702 |
| AC-7 professional design | T002 (tokens), T003, overall |
| Principle I (WHY with score) | T303 |
| Principle IV (no blank/silent) | T701, T204, T503, T703 |
| Principle VI (ack audited) | T602 **[API-GAP]** |

## Blockers & Open Items

- **Live integration gated on Spec 003 → Spec 002 being implemented.** All [API-DEP]
  tasks are mock-verified now; live-verified later.
- **[API-GAP] endpoints don't exist in Spec 003 yet** — FftSpectrum (T306), DeckHeatmap
  (T401), AlertList muni-wide (T601), Alert ack (T602). These are built against assumed
  mock contracts and **cannot go live** until Spec 003 is amended (Q-2/Q-4/Q-7). If you
  defer them, they drop cleanly from v1.
- Carried: Q-1 design tokens (defined in plan), Q-3 poll cadence, Q-8 token storage,
  Q-9 chart-reuse boundary, Q-10 shadcn/ui.
- **No Node/npm verified in this environment yet** — frontend tooling (Vite, npm)
  availability must be checked before implementation, same honesty as the Python/DB
  side.
```
