"""POST /v1/ingest — the gateway's append path (P401-P408 wired to the live pool).

Auth: an `X-API-Key` header resolves against `device_credentials` (0017) to exactly one
bridge + municipality, and becomes a bridge-pinned DEVICE_KEY `Principal`. The
credential read runs before any scope exists — the lookup is what *determines* the
scope (the bootstrap path 0017's header documents). On this deployment the pool role
bypasses RLS, so the read is unconstrained; the ownership check in
`api.ingest.ownership` is the boundary's own refusal and still applies.

Everything after authentication reuses the tested P401-P408 pipeline unchanged:
`parse_batch` enforces the envelope + cap, `process_batch` shape- and ownership-checks
every reading positionally, appends the accepted ones, and audits the call. The only
new code here is thin DB plumbing: a roster that resolves keys from real rows, a
collector for the rows `process_batch` appends, and the INSERTs that persist them.

The stored `key_hash` is `"<salt>$<sha256(salt:key)>"` — the same salted-SHA-256
scheme as `src/db/credential_store.py` (the fake the auth tests run against), so the
provisioning script and this resolver agree by construction. 0017 has no salt column,
so the salt travels inside the hashed value; a dumped database still yields no usable
credentials.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from secrets import compare_digest
from types import SimpleNamespace
from typing import Any, Final

from fastapi import APIRouter, Body, Depends, Header
from typing import Annotated

from ..auth.principal import CredentialClass, Principal, resolve_principal
from ..db.scope import run_scoped
from ..ingest.batch import parse_batch
from ..ingest.ownership import SensorRegistry
from ..ingest.processor import IngestOutcome, process_batch
from ..settings import get_settings
from ..status_policy import ApiError, Failure


router = APIRouter(prefix="/v1", tags=["ingest"])
logger = logging.getLogger("bridgeguard.api.ingest")

# Mirrors P303 (api.auth.device_key): same prefix rule, same minimum length, and one
# generic detail for every rejection so a caller cannot learn a key was ever issued.
_API_KEY_PREFIX: Final = "apikey"
_MIN_KEY_LENGTH: Final = 16
_GENERIC_DETAIL: Final = (
    "The supplied device credential is not valid. Contact the operator who provisioned "
    "this gateway."
)

CREDENTIALS_SQL: Final = """
SELECT credential_id, key_hash, bridge_id, municipality_id, status
FROM device_credentials
"""

SENSORS_SQL: Final = """
SELECT id, bridge_id, sensor_type, config
FROM sensors
WHERE bridge_id = $1
"""

INSERT_READING_SQL: Final = """
INSERT INTO raw_readings
    (sensor_time, sensor_id, sensor_type, value, unit, bridge_id, municipality_id, raw_payload)
VALUES ($1::timestamptz, $2, $3, $4, $5, $6, $7, $8::jsonb)
"""

STAMP_LAST_USED_SQL: Final = """
UPDATE device_credentials SET last_used_at = now() WHERE credential_id = $1
"""


class UnknownKeyError(Exception):
    """No credential row matches the presented key."""


class RevokedKeyError(Exception):
    """The matching credential row is revoked."""


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    """What a presented key resolved to: one bridge in one tenant, by credential id."""

    credential_id: int
    bridge_id: str
    municipality_id: str


def _hash_key(raw_key: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{raw_key}".encode()).hexdigest()


class DbCredentialRoster:
    """Resolves a presented raw key against device_credentials rows from the pool."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def resolve(self, key: str) -> ResolvedCredential:
        for row in self._rows:
            salt, _, digest = str(row["key_hash"]).partition("$")
            if not salt or not digest:
                continue
            if compare_digest(_hash_key(key, salt), digest):
                if str(row["status"]) != "active":
                    raise RevokedKeyError(f"credential {row['credential_id']} is revoked")
                return ResolvedCredential(
                    credential_id=int(row["credential_id"]),
                    bridge_id=str(row["bridge_id"]),
                    municipality_id=str(row["municipality_id"]),
                )
        raise UnknownKeyError("no credential matches the presented key")


def resolve_device_principal(
    api_key: str | None, roster: DbCredentialRoster
) -> tuple[Principal, ResolvedCredential]:
    """Turn the X-API-Key header into a bridge-pinned Principal (P303's contract)."""
    if not api_key or not api_key.strip():
        raise ApiError(Failure.MISSING_CREDENTIAL)
    value = api_key.strip()
    if value.lower().startswith(_API_KEY_PREFIX):
        value = value[len(_API_KEY_PREFIX):].strip()
    if not value:
        raise ApiError(Failure.MISSING_CREDENTIAL)
    if len(value) < _MIN_KEY_LENGTH:
        raise ApiError(Failure.INVALID_CREDENTIAL, _GENERIC_DETAIL)

    try:
        credential = roster.resolve(value)
    except RevokedKeyError:
        raise ApiError(Failure.EXPIRED_CREDENTIAL, _GENERIC_DETAIL) from None
    except UnknownKeyError:
        raise ApiError(Failure.INVALID_CREDENTIAL, _GENERIC_DETAIL) from None

    principal = resolve_principal(
        CredentialClass.DEVICE_KEY,
        municipality_ids=[credential.municipality_id],
        bridge_id=credential.bridge_id,
    )
    return principal, credential


class BridgeSensorRoster:
    """The sensor-roster surface `SensorRegistry` needs, materialized for one bridge."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._sensors = {str(row["id"]): row for row in rows}

    def has_sensor(self, sensor_id: str) -> bool:
        return sensor_id in self._sensors

    def bridge_of_sensor(self, sensor_id: str) -> str:
        return str(self._sensors[sensor_id]["bridge_id"])

    def get_sensor(self, sensor_id: str) -> SimpleNamespace:
        row = self._sensors[sensor_id]
        return SimpleNamespace(config=row["config"] or {})


class CollectingRawStore:
    """Gathers the rows `process_batch` appends so the router can persist them."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(dict(row))


class LoggerAuditSink:
    """Audits each ingest call to the structured log.

    [DB-DEP] The durable audit home is decision_log, whose decision_kind enum has no
    ingest kind; until a migration adds one, the boundary's audit lands in the function
    log — visible in deployment logs, not fabricated as a wrong-kind row.
    """

    def record(self, record: Any) -> None:
        logger.info(
            "ingest_audit batch_id=%s municipality=%s bridge=%s accepted=%d rejected=%d",
            record.batch_id,
            record.municipality_id,
            record.bridge_id,
            record.accepted_count,
            record.rejected_count,
        )


class IngestGateway:
    """Every DB touchpoint of the ingest endpoint, behind one overridable dependency."""

    async def ingest(self, api_key: str | None, payload: Any) -> IngestOutcome:
        rows = await run_scoped(CREDENTIALS_SQL)
        principal, credential = resolve_device_principal(api_key, DbCredentialRoster(rows))

        batch = parse_batch(payload, max_readings=get_settings().max_ingest_batch_size)

        sensor_rows = await run_scoped(SENSORS_SQL, principal.bridge_id)
        registry = SensorRegistry(BridgeSensorRoster(sensor_rows))

        store = CollectingRawStore()
        outcome = process_batch(
            batch,
            store=store,
            principal=principal,
            registry=registry,
            audit=LoggerAuditSink(),
        )

        accepted_indexes = [r.index for r in outcome.results if r.accepted]
        for row, index in zip(store.rows, accepted_indexes):
            original = batch.readings[index].model_dump()
            sensor_time_str = str(row["sensor_time"])
            if sensor_time_str.endswith("Z"):
                sensor_time_str = sensor_time_str[:-1] + "+00:00"
            sensor_time = datetime.fromisoformat(sensor_time_str)
            await run_scoped(
                INSERT_READING_SQL,
                sensor_time,
                row["sensor_id"],
                row["sensor_type"],
                row["value"],
                row["unit"],
                row["bridge_id"],
                row["municipality_id"],
                json.dumps(original),
            )

        await run_scoped(STAMP_LAST_USED_SQL, credential.credential_id)

        return outcome


async def get_ingest_gateway() -> IngestGateway:
    return IngestGateway()


@router.post("/ingest", response_model=IngestOutcome, name="ingest_readings")
async def ingest_readings(
    payload: Annotated[dict[str, Any], Body()],
    gateway: Annotated[IngestGateway, Depends(get_ingest_gateway)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> IngestOutcome:
    """Append raw readings from a gateway device: shape-check, append, ack. Never validate.

    The ack carries one positional result per submitted reading; a rejected reading is
    data in that array, not an error response.
    """
    return await gateway.ingest(x_api_key, payload)
