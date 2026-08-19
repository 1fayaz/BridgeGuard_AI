#!/usr/bin/env python3
import asyncpg
import asyncio
import os
import sys

async def seed_data():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print(f'Using DATABASE_URL: {DATABASE_URL[:50]}...')

    conn = await asyncpg.connect(DATABASE_URL)

    # Seed municipality
    try:
        await conn.execute("""
            INSERT INTO municipalities (id, name)
            VALUES ('municipality-lahore', 'City of Lahore')
            ON CONFLICT (id) DO NOTHING
        """)
        print("✓ Municipality seeded")
    except Exception as e:
        error_msg = str(e)
        if "already exists" in error_msg or "duplicate key" in error_msg:
            print("⊘ Municipality: already exists")
        else:
            print(f"✗ Municipality: {e}")

    # Seed bridges
    bridges = [
        ('bridge-ravi-01', 'Ravi River Bridge', 'Lahore, Punjab'),
        ('bridge-data-01', 'Data Darbar Underpass', 'Lahore, Punjab'),
        ('bridge-mall-01', 'Mall Road Overpass', 'Lahore, Punjab'),
    ]

    for bridge_id, name, location in bridges:
        try:
            await conn.execute("""
                INSERT INTO bridges (id, municipality_id, name, location)
                VALUES ($1, 'municipality-lahore', $2, $3)
                ON CONFLICT (id) DO NOTHING
            """, bridge_id, name, location)
            print(f"✓ Bridge {bridge_id} seeded")
        except Exception as e:
            error_msg = str(e)
            if "already exists" in error_msg or "duplicate key" in error_msg:
                print(f"⊘ Bridge {bridge_id}: already exists")
            else:
                print(f"✗ Bridge {bridge_id}: {e}")

    # Seed sensors (one accelerometer per bridge)
    for bridge_id in ['bridge-ravi-01', 'bridge-data-01', 'bridge-mall-01']:
        sensor_id = f'acc-{bridge_id}'
        try:
            await conn.execute("""
                INSERT INTO sensors (id, bridge_id, sensor_type, config)
                VALUES ($1, $2, 'accelerometer', '{}')
                ON CONFLICT (id) DO NOTHING
            """, sensor_id, bridge_id)
            print(f"✓ Sensor {sensor_id} seeded")
        except Exception as e:
            error_msg = str(e)
            if "already exists" in error_msg or "duplicate key" in error_msg:
                print(f"⊘ Sensor {sensor_id}: already exists")
            else:
                print(f"✗ Sensor {sensor_id}: {e}")

    await conn.close()

asyncio.run(seed_data())
print('Seed complete')