# BridgeGuard AI — Project Context
Last updated: 2026-08-19

## Deployment Stack
| Layer      | Platform | URL                                      | Cost         |
|------------|----------|------------------------------------------|--------------|
| Backend    | Vercel   | https://bridgeguard.vercel.app/api       | Free forever |
| Database   | Neon     | [your neon project URL]                  | Free forever |
| Frontend   | Vercel   | https://bridgeguard.vercel.app           | Free forever |
| Uptime     | UptimeRobot | pings /v1/health every 5 min          | Free forever |

## NO Railway, NO Render — Vercel-only stack (2026-08-24)

## Project Status
- Agents 1-5:        COMPLETE (1480+ tests, 0 failures)
- Database layer:    COMPLETE (migrations 0001-0018, RLS policies active)
- API layer:         IN PROGRESS (715 tests, phases 1-5 done)
- Frontend:          IN PROGRESS (Screen 1 - Bridge Overview complete)
- Deployment:        VERCEL-READY (Neon DB seeded, migrations done)

## Environment Variables Required
### Vercel (both frontend + backend via api/index.py)
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
1. Start simulator:  python simulator/bridge_simulator.py
2. Press n = normal mode (green dashboard)
3. Press d = danger mode (risk score jumps to red)
4. Show alert fires automatically
5. Click Generate Report → PDF downloads
6. Total demo time: 60-90 seconds

## Key Files
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