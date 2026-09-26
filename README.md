# BridgeGuard AI

BridgeGuard AI is a hackathon prototype for AI-assisted bridge structural-health
monitoring. It has a live Next.js dashboard, a deployed Python read/ingest API, a
PostgreSQL (Neon) schema with row-level tenant isolation, five standalone
deterministic Python agent modules with a 2184-test suite, n8n workflow exports,
and a synthetic sensor simulator.

> **Safety notice:** This is not an operational structural-safety system. No
> hardware bill of materials, sensor calibration procedure, or certified
> engineering threshold exists here. All readings shown today come from a
> software simulator, not a physical sensor. Any real deployment requires
> qualified civil/IoT engineering sign-off before a single sensor is mounted.

## 1. What actually runs today

**Live site:** https://bridge-guard-ai.vercel.app

**Deployed backend** (`frontend/api/index.py`, a self-contained FastAPI app —
see §6 on why this differs from `src/api/`):
- `GET /v1/health` — DB connectivity check
- `GET /v1/bridges` — bearer-token auth (`Authorization: Bearer <DEMO_TOKEN>`)
- `GET /v1/bridges/{bridge_id}/risk` — live risk score computed on the fly from
  the newest raw accelerometer readings (not from an audited agent run — see §3)
- `GET /v1/bridges/{bridge_id}/sensors/{sensor_id}/readings` — chart data
- `POST /v1/ingest` — device-key-authenticated sensor ingestion, batch-capped at
  1000 readings

**Dashboard pages** (`frontend/app/`): `/` (overview + map), `/bridges/[id]`
(detail), `/bridges/[id]/alerts`, `/agents` (pipeline explainer), `/reports`
(TXT/PDF export). The homepage renders built-in demo bridge data immediately,
then silently upgrades to live API data (bridge list + live risk score) in the
background if `/v1/bridges` responds — so what you see may briefly be static
before becoming live. The alerts page calls `fetchAlerts()`, but **no
`/v1/bridges/{id}/alerts` endpoint exists on the deployed backend** — that call
404s and the page falls back to its own data, not a live feed.

**Database:** Neon/Postgres, 19 migrations, row-level security enforced (though
the pooled connection the app currently uses is the owner role, which bypasses
RLS by Postgres design — tenant isolation today is enforced by the application's
own scoping, not yet by RLS in practice). One tenant exists: `municipality-sindh`
("Sindh Province"), four bridges: Sukkur Barrage, Guddu Barrage, Indus Highway,
Kotri Barrage.

**Tests:** 2184 passed, 4 skipped, via `pytest` — all backend (`src/api/`,
`src/agents/`, `src/db/`). **The frontend has zero automated tests** (no `*.test.*`
files, no test script in `package.json`); frontend correctness is verified by
`npm run build` (type-checks) and manual/browser verification only.

## 2. What is simulated

- **All sensor data is synthetic.** `simulator/bridge_simulator.py` generates a
  scalar RMS value from a synthetic 100-sample vibration block every 5 seconds
  and POSTs it to the live `/v1/ingest` endpoint with a real device-key header —
  the ingestion mechanics are real, the "vibration" behind them is
  `random.gauss()`, not a physical accelerometer. Typing `d` at its prompt
  switches to a synthetic "danger" profile to demonstrate the CRITICAL band.
- **The live risk score is a simplified live formula, not an agent verdict.**
  `GET /v1/bridges/{id}/risk` computes `score = f(avg_rms)` directly in the API
  layer from the last 10 raw readings. `src/agents/risk_reasoning/` is a fully
  built, independently tested agent module — but nothing in either API
  implementation imports or invokes it. The PDF report's "AI explanation" text
  is similarly the API's own inline formula output labeled as Agent 3's output,
  not a real call into that module.
- **The PDF/TXT reports are generated entirely in the browser.** `frontend/app/reports/page.tsx`
  builds the TXT via a `Blob` and the PDF via `window.open()` + browser print —
  no server-side report-generation call, no persisted artifact, no R2 upload,
  despite `src/agents/report_generation/` existing as a separate, tested module.

## 3. What is planned / not yet built

- **Agent 2 (Structural Analysis)** exists only as configuration scaffolding
  (`src/agents/structural_analysis/config/`) with one implemented task (S101)
  and one test file. The calculation logic itself is not built. (A full
  task-by-task status of S101–S1202 is a separate, more detailed audit item.)
- **ESP32 firmware / real hardware deployment.** There is no firmware directory,
  no bill of materials, no wiring/mounting documentation, and no calibration
  procedure anywhere in this repository. `simulator/bridge_simulator.py` is the
  only thing that has ever sent data to the ingest endpoint.
- **`frontend/api/index.py` vs. `src/api/` consolidation.** Two independent
  implementations of the same five endpoints exist — the deployed
  self-contained one, and a more complete "reference" one (`src/api/`, run only
  by the test suite, never deployed) with a fuller ingest pipeline, JWT-based
  auth scaffolding that isn't actually wired into its own routes, and RLS-based
  tenant scoping. Consolidating them into one implementation is planned
  post-hackathon; see the code comments at the top of `frontend/api/index.py`
  for the current rationale.
- **`n8n/` workflow exports** (`data_collection_ingestion`, `risk_reasoning`,
  `report_generation`, `alert_escalation`) are reference JSON exports describing
  the intended agent-to-agent orchestration. They are not imported into a
  running n8n instance as part of this deployment.

## 4. Architecture

Intended end-to-end pipeline:

```text
Accelerometer -> edge gateway / MQTT -> n8n ingestion workflow
  -> data collection -> structural analysis -> risk reasoning
  -> alerts and reports -> Postgres / dashboard
```

What is actually wired right now:

```text
simulator/bridge_simulator.py -> POST /v1/ingest -> raw_readings table
dashboard -> GET /v1/bridges, /v1/bridges/{id}/risk, /v1/bridges/{id}/sensors/{id}/readings
reports page -> browser Blob (TXT) / window.print() (PDF) -- no server round-trip
```

The five agent modules under `src/agents/` (data collection is the most
complete; structural analysis is the least) are built and tested in isolation
but are not triggered by anything in the live request path today.

## 5. Repository map

```text
frontend/                 Next.js dashboard (deployed to Vercel; Root Directory = frontend/)
frontend/api/index.py     The deployed backend -- self-contained, no imports from src/api/
frontend/requirements.txt Vercel's Python builder reads THIS file for the deployed
                           function, because the project's Root Directory is frontend/ --
                           NOT the root requirements.txt below, which only serves
                           src/api/ + the pytest suite. Silent-gotcha risk if confused.
src/api/                  FastAPI reference implementation, exercised only by pytest
src/agents/               Data collection, structural analysis, risk, report, alert modules
db/migrations/            Ordered Postgres schema migrations (0001-0019)
db/seed_sindh.py          The one current seed script (Sindh Province, 4 bridges)
n8n/                      Reference workflow JSON exports (not live-imported)
simulator/                Synthetic accelerometer sender
tests/                    Python test suite (2184 passed, 4 skipped)
```

## Prerequisites

- Python 3.11+ and pip
- Node.js and npm
- A Neon (or any Postgres) database

## Local setup

### 1. Backend dependencies

```bash
python -m venv .venv
# activate it, then:
python -m pip install -r requirements.txt
```

### 2. Configure the database

Copy `.env.example` to `.env` and fill in real values — it documents the
`BRIDGEGUARD_*` variables `src/api/settings.py` actually reads. Note: the
*deployed* backend (`frontend/api/index.py`) reads different, **unprefixed**
variables instead (`DATABASE_URL`, `DEMO_TOKEN`, `SIMULATOR_KEY`) — `.env.example`
documents both.

### 3. Apply the schema and seed data

```bash
DATABASE_URL="postgresql://..." python scripts/run_migrations.py
DATABASE_URL="postgresql://..." python db/seed_sindh.py
```

This creates the `municipality-sindh` tenant, its 4 bridges and sensors, and one
device credential — the raw simulator key is printed once; save it.

### 4. Run the backend locally

```bash
cd frontend
DATABASE_URL="postgresql://..." DEMO_TOKEN="your-local-token" \
  python -m uvicorn api.index:app --reload --port 8000
```

### 5. Run the dashboard

```bash
cd frontend
npm install
npm run dev
```

### 6. Run the simulator

Edit `simulator/bridge_simulator.py`'s `API_URL`/`API_KEY` to point at your
local server and the device credential printed in step 3, then:

```bash
python simulator/bridge_simulator.py
```

## Tests and build

```bash
python -m pytest          # 2184 passed, 4 skipped
cd frontend && npm run build
```

## Contributing safely

Do not commit secrets, database URLs, device keys, or `project_context.md`
(intentionally gitignored). Run the tests and frontend build before proposing
changes.
