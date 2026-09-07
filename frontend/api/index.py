"""Vercel Python function: the demo API endpoints, self-contained.

This file is deployed as `/api/index` by Vercel's zero-config Python runtime (the
project's Root Directory is `frontend/`, and `api/index.py` is the sole entry point).
Next.js rewrites in the sibling `next.config.mjs` forward `/v1/*` requests here, so the
live dashboard and the simulator both hit `https://bridge-guard-ai.vercel.app/v1/...`.

Self-contained by design: no imports from `src/api/`, which lives outside the project
root the Vercel runtime bundles. The tested reference implementation is in `src/api/`;
this file is the demo projection that runs in production.

Auth:
- Read endpoints accept a `Bearer <DEMO_TOKEN>` header. `DEMO_TOKEN` MUST be set
  via env var — if missing, the server returns 500 "Server misconfigured" rather
  than silently falling back to a guessable default (CWE-798 / CWE-1188).
- POST /v1/ingest authenticates by `X-API-Key` against device_credentials rows (same
  salted-SHA-256 hash as the reference implementation).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from secrets import compare_digest

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

DEMO_MUNICIPALITY_ID = "municipality-lahore"

LIST_BRIDGES_SQL = """
SELECT b.id AS bridge_id, b.name, b.location,
       s.id AS sensor_id
FROM bridges AS b
LEFT JOIN sensors AS s ON s.bridge_id = b.id AND s.sensor_type = 'accelerometer'
WHERE b.municipality_id = $1
ORDER BY b.id
"""

RISK_READINGS_SQL = """
SELECT r.value, r.sensor_time
FROM sensors AS s
JOIN raw_readings AS r ON r.sensor_id = s.id
WHERE s.bridge_id = $1
  AND s.sensor_type = 'accelerometer'
  AND r.value IS NOT NULL
  AND s.municipality_id = $2
ORDER BY r.sensor_time DESC
LIMIT $3
"""

SENSOR_READINGS_SQL = """
SELECT r.sensor_time, r.value
FROM raw_readings AS r
JOIN sensors AS s ON s.id = r.sensor_id
WHERE r.bridge_id = $1
  AND r.sensor_id = $2
  AND r.value IS NOT NULL
  AND s.municipality_id = $3
ORDER BY r.sensor_time DESC
LIMIT $4
"""

CREDENTIALS_SQL = """
SELECT credential_id, key_hash, bridge_id, municipality_id, status
FROM device_credentials
"""

SENSORS_FOR_BRIDGE_SQL = """
SELECT id FROM sensors WHERE bridge_id = $1 AND municipality_id = $2
"""

INSERT_READING_SQL = """
INSERT INTO raw_readings
    (sensor_time, sensor_id, sensor_type, value, unit, bridge_id,
     municipality_id, raw_payload)
VALUES ($1::timestamptz, $2, $3, $4, $5, $6, $7, $8::jsonb)
"""

STAMP_LAST_USED_SQL = """
UPDATE device_credentials SET last_used_at = now() WHERE credential_id = $1
"""

READINGS_WINDOW = 10
SEVERITY_BANDS = ((81, "CRITICAL"), (61, "WARNING"), (31, "WATCH"))
DEFAULT_SEVERITY = "SAFE"
EXPLANATIONS = {
    "SAFE": (
        "Vibration RMS is stable and within safe limits. No structural anomalies "
        "detected in the most recent readings."
    ),
    "WATCH": (
        "Minor vibration elevation above the normal baseline. Pattern is being "
        "monitored; no immediate action required."
    ),
    "WARNING": (
        "Repeated peak vibration exceeds the warning threshold. Manual inspection "
        "within 48 hours is recommended."
    ),
    "CRITICAL": (
        "Sustained high-amplitude vibration detected. Immediate engineering review "
        "and potential load restriction advised."
    ),
}
NO_DATA_EXPLANATION = "No sensor data yet. Awaiting first reading from bridge."


# --------------------------------------------------------------------------- app wiring ---
app = FastAPI(title="BridgeGuard Demo API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://bridge-guard-ai.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def strip_api_prefix(request: Request, call_next):
    """Vercel may invoke this function at /api or /api/index instead of the original path.

    Strip either prefix so routes defined as /v1/* match regardless of whether Vercel
    forwards the rewrite's destination path or the original request path.
    """
    scope_path = request.scope.get("path", "")
    for prefix in ("/api/index", "/api"):
        if scope_path.startswith(prefix) and (
            len(scope_path) == len(prefix) or scope_path[len(prefix)] == "/"
        ):
            request.scope["path"] = scope_path[len(prefix):] or "/"
            break
    return await call_next(request)

bearer_scheme = HTTPBearer(auto_error=False)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ.get("DATABASE_URL", "")
        if dsn.startswith("psql "):
            dsn = dsn[len("psql "):]
        if (dsn.startswith("'") and dsn.endswith("'")) or (
            dsn.startswith('"') and dsn.endswith('"')
        ):
            dsn = dsn[1:-1]
        _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
    return _pool


# --------------------------------------------------------------------------- responses ---
class BridgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bridge_id: str
    name: str
    location: str
    sensor_id: str | None = None


class LiveRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bridge_id: str
    risk_score: int
    severity: str
    explanation: str
    review_status: str
    assessed_at: datetime
    last_reading_at: datetime | None
    sample_count: int
    avg_rms: float | None


class SensorReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_time: datetime
    value: float


class ReadingResult(BaseModel):
    index: int
    accepted: bool
    reason: str | None = None


class IngestOutcome(BaseModel):
    batch_id: str | None = None
    accepted_count: int
    rejected_count: int
    results: list[ReadingResult]


# --------------------------------------------------------------------------- auth ---
async def require_demo_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    expected = os.environ.get("DEMO_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="Server misconfigured: DEMO_TOKEN not set",
        )
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if not compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Invalid bearer token")


def _hash_key(raw_key: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{raw_key}".encode()).hexdigest()


def _resolve_device(api_key: str | None, rows: list[dict]) -> dict:
    if not api_key or not api_key.strip():
        raise HTTPException(status_code=401, detail="Missing device credential")
    value = api_key.strip()
    if value.lower().startswith("apikey"):
        value = value[6:].strip()
    if not value or len(value) < 16:
        raise HTTPException(
            status_code=401,
            detail="The supplied device credential is not valid. "
            "Contact the operator who provisioned this gateway.",
        )
    for row in rows:
        stored = str(row["key_hash"])
        salt, _, digest = stored.partition("$")
        if not salt or not digest:
            continue
        if compare_digest(_hash_key(value, salt), digest):
            if str(row["status"]) != "active":
                raise HTTPException(
                    status_code=401,
                    detail="The supplied device credential is not valid. "
                    "Contact the operator who provisioned this gateway.",
                )
            return dict(row)
    raise HTTPException(
        status_code=401,
        detail="The supplied device credential is not valid. "
        "Contact the operator who provisioned this gateway.",
    )


# --------------------------------------------------------------------------- scoring ---
def _score_for(avg_rms: float) -> int:
    return int(avg_rms * 40) if avg_rms < 0.5 else min(100, int(avg_rms * 30))


def _severity_for(score: int) -> str:
    for threshold, severity in SEVERITY_BANDS:
        if score >= threshold:
            return severity
    return DEFAULT_SEVERITY


def _compute_live_risk(bridge_id: str, rows: list[dict]) -> LiveRisk:
    values = [float(r["value"]) for r in rows if r.get("value") is not None]
    if not values:
        return LiveRisk(
            bridge_id=bridge_id,
            risk_score=0,
            severity=DEFAULT_SEVERITY,
            explanation=NO_DATA_EXPLANATION,
            review_status="FINAL",
            assessed_at=datetime.now(UTC),
            last_reading_at=None,
            sample_count=0,
            avg_rms=None,
        )
    avg_rms = sum(values) / len(values)
    score = _score_for(avg_rms)
    severity = _severity_for(score)
    times = [r["sensor_time"] for r in rows if r.get("sensor_time") is not None]
    return LiveRisk(
        bridge_id=bridge_id,
        risk_score=score,
        severity=severity,
        explanation=EXPLANATIONS[severity],
        review_status="FINAL",
        assessed_at=datetime.now(UTC),
        last_reading_at=max(times) if times else None,
        sample_count=len(values),
        avg_rms=round(avg_rms, 3),
    )


# --------------------------------------------------------------------------- endpoints ---
@app.get("/v1/health")
async def health() -> dict:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        return {"status": "degraded", "db": f"error: {type(exc).__name__}"}


@app.get("/v1/bridges", response_model=list[BridgeOut])
async def list_bridges(_token: None = Depends(require_demo_token)) -> list[BridgeOut]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(LIST_BRIDGES_SQL, DEMO_MUNICIPALITY_ID)
    return [
        BridgeOut(
            bridge_id=str(r["bridge_id"]),
            name=str(r["name"]),
            location=str(r["location"]),
            sensor_id=str(r["sensor_id"]) if r["sensor_id"] else None,
        )
        for r in rows
    ]


@app.get("/v1/bridges/{bridge_id}/risk", response_model=LiveRisk)
async def get_bridge_risk(
    bridge_id: str, _token: None = Depends(require_demo_token)
) -> LiveRisk:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            RISK_READINGS_SQL, bridge_id, DEMO_MUNICIPALITY_ID, READINGS_WINDOW
        )
    return _compute_live_risk(bridge_id, [dict(r) for r in rows])


@app.get(
    "/v1/bridges/{bridge_id}/sensors/{sensor_id}/readings",
    response_model=list[SensorReading],
)
async def list_readings(
    bridge_id: str,
    sensor_id: str,
    limit: int = Query(50, ge=1, le=200),
    _token: None = Depends(require_demo_token),
) -> list[SensorReading]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            SENSOR_READINGS_SQL, bridge_id, sensor_id, DEMO_MUNICIPALITY_ID, limit
        )
    return [
        SensorReading(sensor_time=r["sensor_time"], value=float(r["value"]))
        for r in reversed(rows)
    ]


@app.post("/v1/ingest", response_model=IngestOutcome)
async def ingest(
    payload: dict,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> IngestOutcome:
    pool = await get_pool()
    async with pool.acquire() as conn:
        cred_rows = await conn.fetch(CREDENTIALS_SQL)
        credential = _resolve_device(x_api_key, [dict(r) for r in cred_rows])
        bridge_id = str(credential["bridge_id"])
        muni_id = str(credential["municipality_id"])
        cred_id = int(credential["credential_id"])

        sensor_rows = await conn.fetch(SENSORS_FOR_BRIDGE_SQL, bridge_id, muni_id)
        known_sensors = {str(r["id"]) for r in sensor_rows}

        readings = payload.get("readings") or []
        if not isinstance(readings, list):
            raise HTTPException(status_code=422, detail="readings must be a list")

        results: list[ReadingResult] = []
        accepted_count = 0
        for index, reading in enumerate(readings):
            if not isinstance(reading, dict):
                results.append(
                    ReadingResult(index=index, accepted=False, reason="non_object")
                )
                continue
            sensor_id = str(reading.get("sensor_id", "") or "")
            if not sensor_id or sensor_id not in known_sensors:
                results.append(
                    ReadingResult(index=index, accepted=False, reason="unknown_sensor")
                )
                continue
            try:
                value = float(reading["value"])
            except (KeyError, TypeError, ValueError):
                results.append(
                    ReadingResult(index=index, accepted=False, reason="non_numeric_value")
                )
                continue
            sensor_time_raw = reading.get("sensor_time") or datetime.now(UTC).isoformat()
            sensor_time_str = str(sensor_time_raw)
            if sensor_time_str.endswith("Z"):
                sensor_time_str = sensor_time_str[:-1] + "+00:00"
            sensor_time = datetime.fromisoformat(sensor_time_str)
            await conn.execute(
                INSERT_READING_SQL,
                sensor_time,
                sensor_id,
                reading.get("sensor_type", "accelerometer"),
                value,
                reading.get("unit", "g"),
                bridge_id,
                muni_id,
                json.dumps(reading),
            )
            results.append(ReadingResult(index=index, accepted=True))
            accepted_count += 1

        await conn.execute(STAMP_LAST_USED_SQL, cred_id)

    return IngestOutcome(
        accepted_count=accepted_count,
        rejected_count=len(results) - accepted_count,
        results=results,
    )
