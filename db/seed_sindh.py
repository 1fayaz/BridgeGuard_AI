"""Seed Sindh bridges, sensors, and a simulator device credential into Neon.

The demo dashboard's four bridges (Sukkur / Guddu / Indus Highway / Kotri) live in the
same municipality as the Lahore set, because the pool role (`neondb_owner`) bypasses RLS
and `scope.py` hardcodes `municipality-lahore` for the demo GUC — the API's tenancy
boundary is therefore the one credential's `municipality_id`. A multi-tenant deployment
needs the simulator's credential pinned to the tenant it serves, which is exactly what
this script does.

The script is idempotent: every INSERT uses ON CONFLICT DO NOTHING, and the credential
hash is UNIQUE — running twice does nothing the second time. The raw simulator key is
printed once (the only time it ever exists outside the database) and is NOT stored
anywhere else.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import sys

import asyncpg


BRIDGES = [
    ("bridge-sukkur-01", "Sukkur Barrage Bridge", "Sukkur, Sindh"),
    ("bridge-guddu-01", "Guddu Barrage Bridge", "Guddu, Sindh"),
    ("bridge-indus-hwy-01", "Indus Highway (Hyd-Khi) Bridge", "Near Hyderabad, Sindh"),
    ("bridge-kotri-01", "Kotri Barrage Bridge", "Kotri, Sindh"),
]

MUNICIPALITY_ID = "municipality-lahore"
MUNICIPALITY_NAME = "City of Lahore"


def _hash_key(raw_key: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{raw_key}".encode()).hexdigest()


def _normalize_database_url(raw: str) -> str:
    """Strip `psql '...'` wrappers that copy-paste from provider dashboards introduce."""
    value = raw.strip()
    if value.startswith("psql "):
        value = value[len("psql "):]
    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value


async def seed() -> None:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        sys.exit("DATABASE_URL not set")
    dsn = _normalize_database_url(raw_url)

    conn = await asyncpg.connect(dsn)

    await conn.execute(
        "INSERT INTO municipalities (id, name) VALUES ($1, $2) "
        "ON CONFLICT (id) DO NOTHING",
        MUNICIPALITY_ID, MUNICIPALITY_NAME,
    )
    print(f"[seed] municipality {MUNICIPALITY_ID}")

    for bridge_id, name, location in BRIDGES:
        await conn.execute(
            "INSERT INTO bridges (id, municipality_id, name, location) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING",
            bridge_id, MUNICIPALITY_ID, name, location,
        )
        print(f"[seed] bridge   {bridge_id}")

        sensor_id = f"acc-{bridge_id[len('bridge-'):]}"
        await conn.execute(
            "INSERT INTO sensors (id, bridge_id, sensor_type, config, municipality_id) "
            "VALUES ($1, $2, 'accelerometer', '{}'::jsonb, $3) "
            "ON CONFLICT (id) DO NOTHING",
            sensor_id, bridge_id, MUNICIPALITY_ID,
        )
        print(f"[seed] sensor  {sensor_id} -> {bridge_id}")

    simulator_bridge = "bridge-indus-hwy-01"
    simulator_key = os.environ.get("SIMULATOR_KEY")
    salt = secrets.token_hex(16)
    if not simulator_key:
        simulator_key = secrets.token_hex(24)
        print(f"[seed] generated simulator key (save it!): {simulator_key}")

    key_hash = f"{salt}${_hash_key(simulator_key, salt)}"
    row = await conn.fetchrow(
        "INSERT INTO device_credentials "
        "  (key_hash, bridge_id, municipality_id, device_label, status) "
        "VALUES ($1, $2, $3, $4, 'active') "
        "ON CONFLICT (key_hash) DO NOTHING "
        "RETURNING credential_id",
        key_hash, simulator_bridge, MUNICIPALITY_ID, "pi-simulator-indus",
    )
    if row:
        print(
            f"[seed] credential {row['credential_id']} for {simulator_bridge}: "
            f"key_hash={key_hash[:16]}..."
        )
    else:
        print(f"[seed] credential for key_hash {key_hash[:16]}... already exists")

    print(f"\n[seed] simulator key to set as API_KEY:\n  {simulator_key}")
    print(f"[seed] simulator bridge_id:\n  {simulator_bridge}")
    print(f"[seed] simulator sensor_id:\n  acc-indus-hwy-01")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
