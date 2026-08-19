# Implementation Plan: Dashboard / Frontend

**Feature:** `004-dashboard-frontend`
**Created:** 2026-06-20
**Status:** Draft — awaiting confirmation before task breakdown
**Spec:** `specs/004-dashboard-frontend/spec.md`
**Constitution:** v2.1.0
**Skills ref:** `skills/bridgeguard-skills-README.md` → `visual-output`, `math-analysis`

> Architecture only — no implementation code here.
>
> **Honest dependency status (your prompt says "already-planned backend API
> endpoints" — correct, *planned*, not built):** Spec 003 is specced+planned but
> **not implemented**. *(Update 2026-07-27: Spec 002 is now **built** — Neon/Postgres,
> standard B-tree only — so the API is no longer DB-gated; see `specs/api/spec.md`.)* Therefore this
> frontend is designed against a **typed mock API layer** that mirrors the Spec 003
> contract exactly, so the UI is fully buildable/demoable now and swaps to the live
> API by changing one base client. Endpoints below are marked **[API-DEP]** where
> they rely on a 003 endpoint not yet live, and **[API-GAP]** where the endpoint
> doesn't exist in Spec 003 yet (alert-ack, muni-wide alerts, FFT/heatmap data).

## 1. Framework & Stack

| Concern | Choice | Source / rationale |
|---------|--------|--------------------|
| Framework | **React + TypeScript** via **Vite** | README stack (React.js); TS for safety-critical UI correctness; Vite for Vercel deploy |
| Styling | **Tailwind CSS** | README stack table |
| Components | **shadcn/ui** (Radix primitives + Tailwind) | Your prompt; gives accessible, non-generic building blocks. NOTE: not one of the 7 README skills — adopted as a reasonable lib choice, flag if you disagree |
| Charts | **Recharts** (primary), **Plotly** (FFT), **D3** (deck heatmap) | README `visual-output` chart→tool table is explicit per chart type |
| Server state | **TanStack Query (React Query)** | Caching for AC-1 overview, polling for AC-4 report status |
| Routing | **React Router** | standard SPA routing |
| Tests | **Vitest + React Testing Library** (component) + **Playwright** (E2E) | Vite-native unit; Playwright for the view→report→download flow |

Project layout:
```
frontend/
  src/
    api/
      client.ts          # base fetch wrapper (auth header, error → typed result)
      endpoints.ts       # typed fns mirroring Spec 003 contract
      mock/              # mock implementation of the same interface (build w/o live API)
      types.ts           # BridgeOverviewItem, RiskScoreView, SensorSeries, ...
    routes/              # page components (see §2)
    components/          # BridgeCard, RiskGauge, SensorChart, DeckHeatmap, ...
    charts/              # shared chart primitives (see §8 — reused logic w/ PDF)
    auth/                # token store, protected route, login
    hooks/               # useOverview, useRiskScore, useReportJob, ...
    design/              # tokens: risk-band colors, typography, spacing (§7, Q-1)
  tests/ e2e/
```

## 2. Page / Route Structure

| Route | Page | Primary endpoints |
|-------|------|-------------------|
| `/login` | Login | auth spec (separate) |
| `/` | **Overview** — bridge grid, color-coded | `GET /v1/bridges/overview` [API-DEP] |
| `/bridges/:id` | **Bridge Detail** — gauge + reasoning + per-sensor charts + Request Report | `/risk-score`, `/sensors/:sid/readings` [API-DEP] |
| `/reports` | **Reports** — list + status + download of requested reports | `/reports/:job/status`, `/download` [API-DEP] |
| `/alerts` | **Alerts** — muni-wide list, sort, acknowledge | `GET /v1/alerts` [API-GAP], `POST /v1/alerts/:id/ack` [API-GAP] |
| `/settings` | Settings/Profile | auth spec |
| `*` | NotFound | — |

All routes except `/login` are wrapped in `<ProtectedRoute>` (§5). The app shell
(nav, municipality context) renders only when authenticated.

## 3. State Management & Live Updates

**Decision: polling via React Query, NOT websockets (for v1).** Rationale:
- Risk scores update on the agent's **1–5 min cycle** (Spec 001), not sub-second —
  websockets would be engineering for a freshness the data doesn't have.
- Polling is simpler, survives reconnects trivially, and matches AC-4's required
  poll-the-job-status pattern, so we use one mechanism throughout (Principle IV:
  reliability over cleverness).

| Data | Strategy |
|------|----------|
| Overview | React Query, `staleTime` ~60s, background refetch; manual refresh button |
| Risk score / detail | React Query, refetch on focus + ~60s interval |
| Report job status | React Query polling at a fixed interval until `done`/`failed` (Q-3) |
| Alerts | React Query, ~60s; invalidate on acknowledge |

(If true real-time is later required, a websocket can replace the polling hooks
behind the same `useX` interface — isolated change.)

## 4. Component Breakdown → Endpoint Mapping

| Component | Responsibility | Endpoint(s) | Notes |
|-----------|----------------|-------------|-------|
| **BridgeCard** | one bridge: name, score, band color | (data from `/overview`) | band color from §7 tokens; whole-card link to detail |
| **OverviewGrid** | grid + sort/filter by band | `GET /v1/bridges/overview` [API-DEP] | AC-1 ≤2s for 100 bridges |
| **RiskGauge** | 0–100 RadialBar + band label | `GET /v1/bridges/:id/risk-score` [API-DEP] | Recharts RadialBar per README |
| **RiskExplanation** | renders `reasoning_text` (the WHY) | (same risk-score call) | **Principle I** — score never shown without WHY |
| **SensorChart** | interactive time-series, 30/90/365 + zoom | `GET /v1/bridges/:id/sensors/:sid/readings?window=` [API-DEP] | AC-3 interactive; marks interpolated/gap points (FR-8) |
| **FftSpectrum** | Plotly frequency plot (vibration sensors) | FFT data endpoint **[API-GAP]** (Q-2) | gated on API exposing math-analysis FFT output |
| **DeckHeatmap** | D3 strain heatmap across deck | heatmap data endpoint **[API-GAP]** (Q-2) | gated likewise |
| **ReportRequestModal** | date-range picker → create job → pending | `POST /v1/bridges/:id/reports` [API-DEP] | returns job_id; AC-4 |
| **ReportStatus** | poll + download when ready | `/reports/:job/status`, `/download` [API-DEP] | clean failed state |
| **AlertList** | sortable by severity/bridge + ack | `GET /v1/alerts` + `POST .../ack` **[API-GAP]** | Q-4/Q-7 — endpoints don't exist in 003 yet |
| **AlertTimeline** | Recharts ComposedChart (optional) | alerts data | from `visual-output` |
| **StateBoundary** | shared loading/empty/error wrapper | — | §6, used by every data component |

## 5. Authentication Flow

> Auth **mechanism** is a separate spec; this plan defines the **frontend** handling
> only, consuming whatever token the auth service issues.

- **Login** (`/login`): posts credentials to the auth endpoint, receives a JWT
  (access + refresh, per Spec 003 §2).
- **Token storage:** in-memory app state + refresh token in an **httpOnly cookie**
  if the backend supports it (preferred — XSS-safe); fall back to storing access
  token in memory only (never localStorage for the long-lived token) — confirm with
  auth spec. [NEEDS CLARIFICATION Q-8.]
- **Attachment:** `api/client.ts` injects `Authorization: Bearer` on every request;
  on 401 → attempt refresh once → else redirect to `/login`.
- **Protected routes:** `<ProtectedRoute>` checks auth state; unauthenticated →
  redirect to `/login` preserving intended destination.
- **Tenant scoping:** the UI shows only the token's municipality data; it **never
  assumes** isolation — the API enforces it server-side (defense in depth). The UI
  must not leak another tenant's ids even in URLs.

## 6. Loading / Error / Empty States (Constitution IV — no blank screens)

A single **`<StateBoundary>`** wraps every data-fetching view and renders:
- **loading** → skeleton matching the eventual layout (not a spinner-on-blank),
- **error** → a clean inline message + retry button; the API's structured error
  `{error, code, correlation_id}` is surfaced as a friendly message, with the
  correlation_id shown small for support (ties to Spec 003 AC-6),
- **empty** → an explicit "no bridges / no alerts / no data in range" message,
- **success** → the content.

No component is allowed to render a bare blank or swallow an error silently. This is
a testable rule (component tests assert all four states exist).

## 7. Responsive Design & Design Language

**Breakpoints (Tailwind):** mobile-first; primary targets **tablet (md/lg)** since
engineers use tablets on-site (AC-6), plus desktop.
- `sm` (≥640) phone landscape — read-only graceful degrade
- `md` (≥768) **tablet portrait — primary on-site target**
- `lg` (≥1024) **tablet landscape / small laptop — primary**
- `xl` (≥1280) desktop ops center
Overview grid reflows 1→2→3→4 columns across breakpoints; charts get min-heights and
horizontal scroll affordances on narrow widths; touch targets ≥44px.

**Design language (resolves Q-1 — the "frontend-design skill" is NOT in the README's
7 skills, so this plan DEFINES the design tokens):**
- **Risk band palette (authoritative, from `math-analysis`):**
  Safe 🟢 `0–30`, Watch 🟡 `31–60`, Warning 🟠 `61–80`, Critical 🔴 `81–100`.
  Tokens `--risk-safe / -watch / -warning / -critical` used everywhere a band shows
  (cards, gauge, badges) — **single source so color == band is consistent**.
  Color is **never the only signal** (accessibility): pair with label + icon.
- Typography: one professional sans (e.g. Inter); clear hierarchy; generous spacing
  to read "enterprise," not "admin template" (AC-7).
- A small set of tokens (color/space/radius/shadow) in `design/` consumed via
  Tailwind theme so the look is cohesive and demo-ready (US-6).
[CONFIRM Q-1: define here as above, or follow an external design doc if one exists.]

## 8. Chart Consistency (Dashboard ↔ PDF)

The README's `visual-output` skill explicitly distinguishes **"dashboard-ready React
components"** from **"static chart images for PDF embedding."** Plan to honor that
without divergence:

- **Shared chart core in `charts/`:** each chart type (timeseries, gauge, FFT,
  heatmap) has a single module owning its **visual logic** — color mapping (risk
  bands from §7 tokens), axis formatting, thresholds, legend, series styling.
- **Two thin render targets over the same core:**
  - *Interactive* (dashboard) — Recharts/Plotly/D3 with zoom + range select (AC-3).
  - *Static* (PDF) — same core config rendered headless to a static image for the
    `pdf-report` skill (ReportLab embeds images).
- Because both targets read the **same band tokens + formatting config**, a Warning
  bridge looks identical (same orange, same thresholds) on screen and in the PDF.
- [Boundary note: the PDF is generated **server-side** by the `pdf-report` skill
  (Python/ReportLab). "Reuse" here means a **shared visual spec** (tokens, thresholds,
  formatting rules) kept in sync — not literally importing React into Python. The
  shared artifact is a small design-token/threshold definition both sides consume.
  CONFIRM Q-9: is that shared spec acceptable, or do you expect the PDF charts to be
  rendered by the JS layer and handed to the PDF skill as images?]

## 9. Testing Plan

| # | Test | Type | Asserts | Maps to |
|---|------|------|---------|---------|
| FT-1 | BridgeCard band color | component | each score → correct band token + label + icon | US-1, §7 |
| FT-2 | OverviewGrid states | component | loading/empty/error/success all render (no blank) | AC-1, §6 |
| FT-3 | RiskGauge + RiskExplanation | component | gauge value + **reasoning_text always present** | US-3, Principle I |
| FT-4 | SensorChart interactivity | component | range 30/90/365 switch + zoom; interpolated/gap marked | AC-3, FR-8 |
| FT-5 | ReportRequestModal | component | submit → pending state with job_id | AC-4 |
| FT-6 | ReportStatus polling | component | polls until done → download enabled; failed → clean error | AC-4 |
| FT-7 | AlertList sort + ack | component | sortable by severity/bridge; ack triggers write + optimistic update | AC-5 [API-GAP] |
| FT-8 | StateBoundary | component | renders each of the 4 states correctly | §6, Principle IV |
| FT-9 | ProtectedRoute | component | unauth → redirect to /login | §5 |
| FT-10 | Responsive smoke | component | grid reflows at md/lg; touch targets ≥44px | AC-6 |
| **E2E-1** | **view bridge → request report → download** | Playwright | full happy path against the **mock API**, incl. poll→ready→download | AC-2/AC-4 |
| E2E-2 | overview → drill-in | Playwright | click card → detail shows gauge + explanation + charts | US-1/2/3 |

All tests run against the **typed mock API** (no live backend needed), so the suite
is green today. An optional later pass re-runs E2E against the real API once Spec
003 is implemented.

## Constitution Re-Check

| Principle | Status |
|-----------|--------|
| I. Safety First | PASS — risk score component always renders reasoning_text; no physical-action UI |
| III. Modularity | PASS — UI talks only to the API client contract; mock/live swappable |
| IV. Reliability | PASS — StateBoundary mandates loading/empty/error everywhere |
| VI. Auditability | PASS (frontend part) — alert ack goes through an audited API write [API-GAP to add] |
| VII. Tech Stack | PASS — React+TS+Tailwind, Recharts/Plotly/D3 per README |

## Open Questions To Confirm Before Tasks

- **Q-1 design tokens:** OK for this plan to **define** the BridgeGuard design language
  (risk-band palette + type + spacing), since no "frontend-design skill" exists in the
  README? Or is there an external design doc?
- **Q-2 [API-GAP] FFT/heatmap data:** Spec 003 returns only timeseries. Add FFT +
  heatmap data endpoints to 003, or **defer FftSpectrum + DeckHeatmap to a later
  iteration** and ship v1 with timeseries + gauge? (Affects FR-7, FT components.)
- **Q-3 polling cadence:** report-status poll interval + max wait; notifications panel
  vs inline status?
- **Q-4 [API-GAP] alert ack:** add `POST /v1/alerts/:id/ack` (audited) to Spec 003?
- **Q-7 [API-GAP] muni-wide alerts:** add `GET /v1/alerts` to Spec 003 (US-5 is
  "across all bridges"; current API is per-bridge)?
- **Q-8 token storage:** httpOnly refresh cookie (preferred) vs memory-only — depends
  on the auth spec; confirm direction.
- **Q-9 chart reuse boundary:** shared **visual-spec/tokens** between JS dashboard and
  Python PDF (my design), vs JS renders PDF chart images and hands them to pdf-report?
- **Q-10 component lib:** shadcn/ui confirmed (it's your suggestion, not a README
  skill)?

## Sequencing note

This frontend is **fully buildable now against the mock API** and will be real,
demo-ready UI (serves US-6 sales demos). **Live end-to-end requires Spec 003 → Spec
002 to be implemented.** Three components (FftSpectrum, DeckHeatmap, AlertList ack)
also need **new Spec 003 endpoints** that don't exist yet — see [API-GAP] / Q-2/Q-4/Q-7.
```
