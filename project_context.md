# BridgeGuard AI — Project Context
Last updated: 2026-09-02

## Deployment Stack
| Layer      | Platform | URL                                      | Cost         |
|------------|----------|------------------------------------------|--------------|
| Backend    | Vercel   | https://bridgeguard.vercel.app/api       | Free forever |
| Database   | Neon     | [your neon project URL]                  | Free forever |
| Frontend   | Vercel   | https://bridge-guard-ai.vercel.app       | Free forever |
| Uptime     | UptimeRobot | pings /v1/health every 5 min          | Free forever |

## NO Railway, NO Render — Vercel-only stack (2026-08-24)

## Project Status
- Agents 1-5:        COMPLETE (1480+ tests, 0 failures)
- Database layer:    COMPLETE (migrations 0001-0018, RLS policies active)
- API layer:         IN PROGRESS (715 tests, phases 1-5 done)
- Frontend:          COMPLETE — rebuilt from scratch 2026-09-02
  - Overview, bridge detail, alerts, agents, and reports pages
  - Mock Sindh bridge data with Recharts time-series visualization
  - Client-side report generation (TXT + HTML/PDF)
  - Dynamic bridge routes converted to SSG via generateStaticParams
  - Latest commit: `3ae793e4`
- Deployment:        LIVE on Vercel at https://bridge-guard-ai.vercel.app with Root Directory = `frontend`. All pages verified 200.

## Environment Variables Required
### Vercel (frontend only — Root Directory: frontend)
- No runtime environment variables required for the mock-data demo build.

### Vercel (backend via api/index.py at repo root)
- DATABASE_URL            → Neon connection string
- SECRET_KEY              → random 32-char hex string
- APP_ENV                 → production
- NEXT_PUBLIC_API_URL     → "" (relative URLs on Vercel)
- NEXT_PUBLIC_DEMO_TOKEN  → demo JWT (hackathon only)

## Seed Data
Municipality: City of Lahore (id: municipality-lahore)
Bridges:
  - bridge-ravi-01    Ravi River Bridge
  - bridge-data-01    Data Darbar Underpass
  - bridge-mall-01    Mall Road Overpass
  - bridge-thokar-01  Thokar Niaz Baig Bridge
Sensors: one accelerometer per bridge

## Hackathon Demo Flow
1. Open deployed frontend overview page.
2. Click Thokar Niaz Baig Bridge (CRITICAL) or Mall Road Overpass (WARNING).
3. Show risk score, AI explanation, and vibration chart.
4. Click "View Alerts" to see severity-sorted alerts.
5. Go to Reports → select bridge → download TXT/HTML report.
6. Go to AI Agents to explain the 5-agent pipeline.
7. Total demo time: 60-90 seconds.

## Key Files
- frontend/vercel.json      → Vercel framework config for Root Directory = frontend
- frontend/lib/data.ts      → shared mock data and severity config
- frontend/app/page.tsx     → bridge overview
- frontend/app/bridges/[id]/page.tsx → bridge detail with Recharts chart
- frontend/app/bridges/[id]/alerts/page.tsx → severity-sorted alerts
- frontend/app/agents/page.tsx → 5-agent pipeline explanation
- frontend/app/reports/page.tsx → client-side report generator
- render.yaml              → Render deployment config
- scripts/run_migrations.py → runs all 16 migrations on Neon
- scripts/seed_data.py      → inserts demo bridges and sensors
- simulator/bridge_simulator.py → fake sensor data for demo
- frontend/                → Next.js dashboard

## Constitution
CLAUDE.md is the supreme governing document.
Constitution v2.1.0 is active.
Stack: Python + FastAPI + OpenAI Agents SDK + Next.js +
       Neon/Postgres + n8n + LoRaWAN + Raspberry Pi 5

## Post-Hackathon TODO
- Complete API phases 6-10
- Wire full Arq+R2 report job system
- Replace demo JWT with real auth flow
- Connect real MPU-6050 hardware
- Migrate to full Supabase (database + storage + auth)
- Wire n8n end-to-end workflow
