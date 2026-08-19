# Feature Specification: Dashboard / Frontend

**Feature Branch:** `004-dashboard-frontend`
**Created:** 2026-06-20
**Status:** Draft — awaiting clarifications
**Constitution:** v2.1.0 (`.specify/memory/constitution.md`)
**Skills ref:** `skills/bridgeguard-skills-README.md` → `visual-output`, `math-analysis`, `pdf-report`

## Summary

A React + Tailwind web dashboard — the only part of BridgeGuard most users ever
see, and the product's primary sales-demo surface. Government engineers and
municipality staff use it to (a) see all their bridges color-coded by risk status,
(b) drill into a bridge for per-sensor interactive time-series charts, heatmaps,
and the current risk score *with its written explanation*, (c) request and download
PDF reports, and (d) view and acknowledge alerts. It consumes the Backend API
(Spec 003) for data and renders the `visual-output` skill's chart types.

It must look professional and trustworthy — this is a safety-critical government
tool, not a hobby project.

## Skill Grounding (from README)

The dashboard is the live consumer of the **`visual-output`** skill, which the
README defines as producing **"dashboard-ready React components"** (Recharts/Plotly/
D3) — explicitly distinct from **"static chart images for PDF embedding."** That
single distinction anchors AC-3 (interactive on the dashboard; static only in PDF).

`visual-output` chart inventory the dashboard renders:

| Visual | Source data | Tool (per README) | Where it appears |
|--------|-------------|-------------------|------------------|
| Time-series LineChart | any sensor over time | Recharts | bridge detail, per sensor |
| FFT spectrum | accelerometer/vibration | Plotly | bridge detail (vibration sensors) |
| Risk gauge (0–100) | risk score | Recharts RadialBar | bridge detail + overview cards |
| Deck heatmap | strain-gauge array | D3.js | bridge detail |
| Comparison bar chart | multi-sensor/period | Recharts | bridge detail (optional) |
| Trend forecast | regression output | Recharts + trendline | bridge detail |
| Alert timeline | event log | Recharts ComposedChart | alerts view |

Risk **status bands** come from `math-analysis` (authoritative): `Safe 0–30` 🟢,
`Watch 31–60` 🟡, `Warning 61–80` 🟠, `Critical 81–100` 🔴. The overview color
coding MUST use exactly these bands and breakpoints.

## Constitution Alignment

| Principle | How this feature complies |
|-----------|---------------------------|
| I. Safety First | The risk score is **always shown with its WHY** (US-3, reasoning text from the Risk agent). The UI presents recommendations, never triggers a physical action. |
| III. Modularity | Pure presentation layer; talks only to the Backend API contract (Spec 003), never to agents/DB directly. |
| IV. Reliability over Cleverness | Deterministic rendering; graceful empty/error/loading states — a failed API call shows a clean message, never a blank or a crash. |
| VI. Auditability | Acknowledging an alert is a write → goes through the API's audited endpoint (so who-ack'd-when is recorded server-side). |
| VII. Tech Stack | React.js + Tailwind CSS, Recharts/Plotly/D3 per the README stack table. |

## Dependencies

| Dependency | Status | Affects |
|------------|--------|---------|
| **Spec 003 Backend API** — overview, timeseries, risk-score, reports, alerts endpoints | spec+plan+tasks exist; **not implemented**. Superseded/extended by `specs/api/spec.md` | every screen |
| **Spec 002 Database Layer** | **BUILT** (Neon/Postgres, standard B-tree only, no TimescaleDB) | indirectly (API needs it) |
| `visual-output` skill — actual chart component contracts | README defines types; component-level props TBD | chart rendering |
| Risk Reasoning Agent — produces the explanation text | not yet specced | US-3 |
| **Alert acknowledge endpoint** | **RESOLVED** — absent from Spec 003 (read-only), now specified in `specs/api/spec.md` as an audited write | US-5, AC-5 |
| Auth/login flow | separate spec | all screens (gated behind login) |

## User Scenarios & Testing

### User Stories

1. **As an engineer,** I want all my bridges on one overview screen, color-coded
   (green/yellow/orange/red) by risk status, so I instantly know where to focus.
2. **As an engineer,** I want to click into a bridge and see time-series charts per
   sensor over 30/90/365 days, so I can spot trends myself, not blindly trust the AI.
3. **As an engineer,** I want a written explanation beside the numeric risk score, so
   I understand WHY a bridge is flagged.
4. **As an engineer,** I want to request a PDF report for a bridge + date range with
   one click and get notified when it's ready to download.
5. **As an admin,** I want a list of active alerts across all bridges and to mark them
   acknowledged/resolved.
6. **As a prospective customer,** I want the dashboard to look professional during a
   sales demo, building trust that this is enterprise-grade software.

### Acceptance Criteria

- **AC-1 (Fast overview):** The overview loads and color-codes all bridges within **2
  seconds** for a municipality with up to **100 bridges**. [Depends on API `GET
  /v1/bridges/overview` meeting its own <500ms AC.]
- **AC-2 (Bridge detail content):** Each bridge detail page shows: live risk score +
  band + **explanation text**, per-sensor interactive time-series charts, and a
  "Request Report" button.
- **AC-3 (Interactive charts):** Dashboard charts are interactive (zoom + time-range
  select), NOT static images. Static charts are only for the PDF (per `visual-output`).
- **AC-4 (Report flow with notify):** Requesting a report shows a clear loading/pending
  state and notifies the user when the download is ready, by **polling the API job
  status endpoint** (`GET /v1/reports/{job_id}/status`).
- **AC-5 (Alerts):** The alerts list is sortable by severity and bridge, with an
  acknowledge action. [Requires an ack write endpoint — see Dependencies gap.]
- **AC-6 (Responsive/tablet):** All screens are responsive and usable on tablets
  (engineers use tablets on-site).
- **AC-7 (Professional design):** Visual design is distinctive and professional — not a
  generic admin-template look. [NEEDS CLARIFICATION: the prompt references a
  "frontend-design skill" that is NOT in the README's 7 skills — see Open Q-1.]

## Functional Requirements

### Overview screen

- **FR-1:** Render every in-scope bridge as a card/row with name, current risk score,
  and a color matching its band (Safe/Watch/Warning/Critical), within 2s for 100
  bridges (AC-1). Source: `GET /v1/bridges/overview`.
- **FR-2:** Provide sort/filter by risk band so engineers see Critical/Warning first.
- **FR-3:** Clicking a bridge navigates to its detail page.
- **FR-4:** Empty state (no bridges) and error state (API down) are explicit, not blank.

### Bridge detail screen

- **FR-5:** Show the live risk **gauge** (0–100, Recharts RadialBar), the band label,
  and the **reasoning_text** explanation prominently (US-3, Principle I). Source: `GET
  /v1/bridges/{id}/risk-score`.
- **FR-6:** For each sensor, render an interactive time-series LineChart with a
  **30/90/365-day** range selector and zoom (AC-3). Source: `GET
  /v1/bridges/{id}/sensors/{sid}/readings?window=`.
- **FR-7:** Render the FFT spectrum (Plotly) for vibration/accelerometer sensors, and
  the deck heatmap (D3) for the strain-gauge array, per `visual-output`. [NEEDS
  CLARIFICATION Q-2: does the API expose FFT/heatmap-ready data, or only raw
  timeseries? The README's chart→data mapping implies math-analysis output is needed.]
- **FR-8:** Distinguish data quality visually — interpolated points and gaps (`status`,
  `is_interpolated` from the API) should be marked, not silently smoothed (Principle II
  transparency).
- **FR-9:** A "Request Report" button initiates the report flow (FR-10).

### Report flow

- **FR-10:** "Request Report" opens a date-range picker → `POST
  /v1/bridges/{id}/reports` → shows a pending state with the returned `job_id`.
- **FR-11:** Poll `GET /v1/reports/{job_id}/status` until done/failed; on done, surface
  a download action (`GET /v1/reports/{job_id}/download`); on failed, a clean error
  (AC-4). [NEEDS CLARIFICATION Q-3: poll interval + timeout; is there a notifications
  area or just inline status?]

### Alerts screen

- **FR-12:** List active alerts across in-scope bridges, sortable by severity and by
  bridge (AC-5). Source: `GET /v1/bridges/{id}/alerts` (or a municipality-wide alerts
  list — see gap).
- **FR-13:** Acknowledge/resolve action per alert → an **audited write** to the API.
  [GAP: Spec 003 has no ack endpoint; needs adding. Q-4.]
- **FR-14:** Optionally render the alert timeline (Recharts ComposedChart) per
  `visual-output`.

### Cross-cutting

- **FR-15:** All screens responsive; verified usable at tablet breakpoints (AC-6).
- **FR-16:** Every data view has explicit loading, empty, and error states (Principle IV).
- **FR-17:** All screens are behind authentication; the UI only ever shows the logged-in
  municipality's data (the API enforces isolation; the UI must not assume otherwise).
- **FR-18:** Professional, distinctive visual design (AC-7) — see Open Q-1 on the
  design-skill reference.

## Key Entities (view models, fed by the API)

- **BridgeOverviewItem** — id, name, score, band, last_updated. (from `/overview`)
- **RiskScoreView** — score, band, reasoning_text, scored_at. (from `/risk-score`)
- **SensorSeries** — sensor id/type, points[{ts, value, status, is_interpolated}], window.
- **ReportJobView** — job_id, status, download ref.
- **AlertItem** — id, bridge, sensor?, severity, state, raised_at, ack state.

## Out of Scope

- Native mobile app (future).
- Public marketing site (separate project).
- The auth/login mechanism (separate spec) — the dashboard consumes it.
- Producing the chart *data* (that's `math-analysis`/`visual-output` server-side); the
  dashboard renders, it does not compute risk/FFT itself.

## Open Questions (resolve before `/sp.plan`)

- **Q-1 (design skill):** AC-7/FR-18 and the prompt reference a **"frontend-design
  skill"** — this is **not one of the 7 skills** in the README (which has no design
  skill). Is there a separate design-system/skill doc I should follow, or should I
  define a BridgeGuard design language (color tokens for the 4 risk bands, typography,
  spacing) as part of this spec? Without it, "not a generic admin template" is
  subjective.
- **Q-2 (FFT/heatmap data):** Does the Backend API expose FFT-spectrum and
  heatmap-ready datasets (math-analysis output), or only raw/clean timeseries? If only
  timeseries, either the API needs new endpoints or the dashboard drops FFT/heatmap to
  a later iteration. This changes Spec 003's surface.
- **Q-3 (report notify):** Poll interval + max wait for AC-4; a dedicated notifications
  panel vs. inline status on the bridge page?
- **Q-4 (alert ack endpoint):** Spec 003 exposes alerts **read-only**; acknowledging is
  a write that doesn't exist yet. Add `POST /v1/alerts/{id}/ack` (audited) to Spec 003,
  or defer alert-ack to a later iteration?
- **Q-5 (build tooling):** Vite + React + TS assumed (README says React.js + Tailwind,
  deploy Vercel). Confirm TypeScript, and a component lib (or Tailwind-only +
  headless)?
- **Q-6 (data fetching/state):** React Query (TanStack) for server-state +
  polling/caching is the natural fit for AC-1/AC-4. Confirm, vs. plain fetch/SWR?
- **Q-7 (municipality-wide alerts):** US-5 says "across all bridges," but the API alert
  endpoint is per-bridge. Need a `GET /v1/alerts` municipality-wide list (another Spec
  003 addition) or aggregate client-side?

## Review Checklist

- [ ] Q-1 design-skill source resolved (or design language defined here).
- [ ] Q-2 FFT/heatmap data availability confirmed (may expand Spec 003).
- [ ] Q-4 + Q-7 alert endpoints reconciled with Spec 003 (ack write + muni-wide list).
- [ ] Q-5/Q-6 tooling confirmed.
- [ ] Note: full integration is gated on Spec 003 (and thus 002) being implemented; the
      frontend can be built against a mocked API in the meantime.
```
