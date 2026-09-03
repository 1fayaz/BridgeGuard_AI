# BridgeGuard AI

BridgeGuard AI is a prototype for bridge-health monitoring. It contains a Next.js dashboard, a FastAPI read API, PostgreSQL migration scripts, deterministic agent modules, n8n workflow exports, and a sensor simulator.

> **Safety notice:** This repository is not an operational structural-safety system. Hardware installation, calibration, engineering thresholds, and all maintenance decisions must be performed and approved by qualified teams. The current dashboard uses mock data, and the live sensor-to-report pipeline is not yet connected end to end.

## What runs today

- Next.js dashboard pages for bridge summaries, alerts, agent stages, and client-generated reports.
- FastAPI endpoints:
  - `GET /v1/health`
  - `GET /v1/bridges?page_size=50&page=1`
- PostgreSQL schema migrations and development seed scripts.
- Python modules that implement data-collection, risk, report, and alert workflow logic with test/fake adapters.
- A browser-generated TXT report and a print-to-PDF report flow.

## Architecture

The intended monitoring path is:

```text
Accelerometer sensor -> edge gateway / MQTT -> n8n ingestion workflow
  -> data collection -> structural analysis -> risk reasoning
  -> alerts and reports -> PostgreSQL / dashboard
```

The currently wired paths are smaller:

```text
Next.js dashboard -> frontend/lib/data.ts mock data -> browser report export
FastAPI -> PostgreSQL pool -> GET /v1/health and GET /v1/bridges
```

The n8n exports, simulator, and agent services define the intended integration, but they are not mounted as a production sensor-ingestion or report-download API.

## Repository map

```text
api/                 Vercel adapter for the FastAPI application
src/api/             FastAPI app, routes, settings, and database pool
src/agents/          Data collection, risk, report, and alert modules
db/migrations/       Ordered PostgreSQL schema migrations
db/seed.py           Development municipality, bridge, and sensor seed data
frontend/            Next.js dashboard
n8n/                 Workflow exports and integration notes
simulator/           Synthetic accelerometer sender
tests/               Python test suite
```

## Prerequisites

- Python and pip
- Node.js and npm
- A reachable PostgreSQL database
- Database credentials with permission to create the `bridgeguard_service` role and apply the schema migrations

## Local setup

### 1. Install backend dependencies

```bash
python -m venv .venv
python -m pip install -r requirements.txt
```

Activate the virtual environment using the command appropriate for your shell before running the Python commands below.

### 2. Configure the database

The migration and seed scripts read `DATABASE_URL`. The FastAPI settings read the prefixed `BRIDGEGUARD_DATABASE_URL` variable. Set both to the same database connection string for local development:

```bash
export DATABASE_URL="postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require"
export BRIDGEGUARD_DATABASE_URL="$DATABASE_URL"
export BRIDGEGUARD_APP_ENV="development"
```

On PowerShell, use:

```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require"
$env:BRIDGEGUARD_DATABASE_URL = $env:DATABASE_URL
$env:BRIDGEGUARD_APP_ENV = "development"
```

`src/api/settings.py` requires additional `BRIDGEGUARD_*` secrets and R2 settings in production mode. Do not set `BRIDGEGUARD_APP_ENV=production` until those real values have been supplied. The existing `.env.example` uses older unprefixed names; treat the runtime settings file as the source of truth.

### 3. Apply the schema and seed development data

```bash
python db/migrate.py
python db/seed.py
```

The migration script applies migrations `0001` through `0018` and attempts to create the service role needed by later RLS policies. Review every migration result: the current runner logs individual failures and continues rather than failing immediately.

The development seed creates the Lahore municipality, three bridges, and accelerometer records including `acc-bridge-ravi-01`.

### 4. Run the backend

```bash
uvicorn src.api.main:app --reload
```

Verify the exposed endpoints from another terminal:

```bash
curl http://127.0.0.1:8000/v1/health
curl "http://127.0.0.1:8000/v1/bridges?page_size=50&page=1"
```

FastAPI also exposes its generated API documentation at `/docs` while the server is running.

### 5. Run the dashboard

```bash
cd frontend
npm install
npm run dev
```

Open the local address printed by Next.js. The dashboard currently reads the static records in `frontend/lib/data.ts`; it does not fetch the FastAPI bridge list.

## Sensor and gateway setup

### Hardware installation

This repository does not include a hardware bill of materials, mounting instructions, sensor calibration procedure, or certified structural thresholds. Before connecting any device:

1. Have qualified civil and IoT teams approve sensor placement, mounting, power, enclosure, communications, calibration, and maintenance procedures.
2. Create a stable sensor identifier and register a matching sensor record in the database. For the development seed, sensor IDs follow `acc-bridge-<bridge-id>`.
3. Record the unit, sampling rate, timestamp source, and ownership information required by the receiving integration.
4. Keep production secrets and device credentials outside version control.

### MQTT and n8n integration target

`n8n/data_collection_ingestion.workflow.json` is the reference ingestion workflow. It listens on MQTT topics matching:

```text
bridgeguard/+/sensors/#
```

The workflow batches messages and expects a data-collection service at the configured `DCA_SERVICE_URL/run-cycle` address. Import the workflow into n8n only after providing your broker credentials and implementing/deploying that service.

### Sensor simulator

The simulator generates 100 accelerometer samples every five seconds:

```bash
python simulator/bridge_simulator.py
```

It currently posts to a hard-coded `/v1/ingest` address with an `X-API-Key` header. The FastAPI application does **not** expose `/v1/ingest`, and the simulator ID (`acc-ravi-01`) differs from the development seed ID (`acc-bridge-ravi-01`). Use it only to inspect the prototype payload and interaction modes until an authenticated ingestion route and compatible adapter are implemented.

## Reports: download and read

1. Start the dashboard and open the **Reports** page.
2. Select a bridge from the dropdown.
3. Select **Download TXT** to save a text report created in the browser. Open the downloaded file in any text editor.
4. Select **Download PDF**. Allow the pop-up, then choose **Save as PDF** in the browser print dialog.
5. Open the saved PDF with a local PDF reader. It contains the selected bridge’s mock risk score, status, explanation, readings, alerts, and recommendation.

The current report page is client-side only. It creates TXT content with a browser `Blob`; its PDF option opens formatted HTML and invokes the print dialog. It does not call the report-generation agent, persist an artifact, upload to R2, or download an API-generated PDF.

## Tests and build

Run the Python tests from the repository root:

```bash
python -m pytest
```

Build the dashboard from the frontend directory:

```bash
npm run build
```

## Current integration limits

- `POST /v1/ingest` is not mounted by `src/api/main.py`.
- The simulator sends a block of samples, while the present ingestion parsing logic expects scalar numeric values.
- The FastAPI application exposes only health and bridge-list routes.
- The frontend uses mock data and does not call the API.
- The agent services rely on fake/test adapters; structural analysis, report artifact storage, and alert delivery are not wired to a live service.
- The report UI does not retrieve persisted PDF artifacts.
- Deployment configuration and environment-variable documentation need consolidation before a production deployment guide can be published.

## Contributing safely

Do not commit secrets, database URLs, device keys, generated caches, or local status notes. Keep `project_context.md` local; it is intentionally ignored. Run the tests and frontend build before proposing changes to the application or documentation.
