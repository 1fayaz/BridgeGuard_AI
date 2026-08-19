#!/usr/bin/env python3
import asyncpg
import asyncio
import os
import sys

async def run_migrations():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print(f'Using DATABASE_URL: {DATABASE_URL[:50]}...')

    conn = await asyncpg.connect(DATABASE_URL)

    # Ensure bridgeguard_service role exists for RLS policies (migrations 0016+)
    try:
        await conn.execute("CREATE ROLE bridgeguard_service")
        print("✓ Created role bridgeguard_service")
    except Exception as e:
        if "already exists" in str(e):
            print("✓ Role bridgeguard_service already exists")
        else:
            print(f"⚠ Role creation: {e}")

    migrations = [
        '0001_raw_readings.sql',
        '0002_validated_readings.sql',
        '0003_sensor_status.sql',
        '0004_decision_log.sql',
        '0005_analysis_results.sql',
        '0006_risk_assessments.sql',
        '0007_decision_log_risk_kinds.sql',
        '0008_report_artifacts.sql',
        '0009_decision_log_report_kinds.sql',
        '0010_alert_dispatches.sql',
        '0011_decision_log_alert_kinds.sql',
        '0012_municipalities.sql',
        '0013_bridges.sql',
        '0014_sensors.sql',
        '0015_tenant_columns_and_fks.sql',
        '0016_rls_policies.sql',
        '0017_device_credentials.sql',
        '0018_device_credential_key_immutable.sql',
    ]

    for migration in migrations:
        try:
            with open(f'db/migrations/{migration}', 'r') as f:
                sql = f.read()
            await conn.execute(sql)
            print(f'✓ {migration}')
        except Exception as e:
            error_msg = str(e)
            # Skip "already exists" errors for idempotent re-runs
            if "already exists" in error_msg or "duplicate key" in error_msg:
                print(f'⊘ {migration}: already applied (skipped)')
            else:
                print(f'✗ {migration}: {e}')

    await conn.close()

asyncio.run(run_migrations())
print('Migrations complete')