-- Migration 0019 — rename tenant municipality-lahore to municipality-sindh
--
-- API Layer (CLAUDE.md audit, 2026-09-24): the demo scope was hardcoded in three places
-- (db/seed_sindh.py, frontend/api/index.py, src/api/db/scope.py) to the id
-- `municipality-lahore` / name 'City of Lahore', a leftover from before the project's demo
-- bridges (Sukkur / Guddu / Indus Highway / Kotri) were repointed at Sindh Province. Code was
-- updated to `municipality-sindh` / 'Sindh Province'; this migration brings the live tenant row
-- and every row that references it into agreement, so the rename does not turn into a silent
-- "no data" failure (INV-1 / P204 territory: an unresolvable scope must be loud, not empty).
--
-- Slot: 0019 is the next free number — 0001-0018 exist with no gaps, nothing appended after 0018.
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB. This migration adds no index and no extension — only data movement.
--
-- ---------------------------------------------------------------------------------------------
-- WHY THIS IS A ROW RETARGET, NOT AN UPDATE OF municipalities.id IN PLACE
--
-- Every tenant-scoped table's `municipality_id` FK is declared `NO ACTION` on UPDATE (0013,
-- 0015, 0017), so `UPDATE municipalities SET id = 'municipality-sindh' WHERE id =
-- 'municipality-lahore'` would fail immediately with a foreign-key violation while eight other
-- tables still point at the old id. The only order that respects every constraint is: insert the
-- new parent row first, retarget every child row to it, and only then delete the now-unreferenced
-- old parent row — all inside one transaction, so a failure partway through leaves the database
-- exactly as it was, never half-migrated.
--
-- Tables retargeted (every table with a municipality_id FK into municipalities.id, confirmed via
-- information_schema against the live instance): bridges, raw_readings, validated_readings,
-- analysis_results, sensor_status, decision_log, risk_assessments, report_artifacts,
-- alert_dispatches, sensors, device_credentials.
--
-- device_credentials is special: 0018's trg_device_credentials_guard_update fires BEFORE UPDATE
-- and explicitly rejects a changed municipality_id (by design — re-pointing a live credential's
-- tenant is the isolation hole that trigger exists to close), so a plain UPDATE here would abort
-- the whole transaction. The trigger only fires on UPDATE, not DELETE/INSERT, so this migration
-- deletes each lahore-scoped row and re-inserts it under the new tenant in a single
-- data-modifying CTE — one statement, atomic, and it never leaves both the old and new row
-- present at once (key_hash is UNIQUE table-wide, not per tenant, so a transient duplicate would
-- fail). Every column survives the move unchanged except municipality_id, including created_at,
-- so the issuance audit trail 0018 protects is preserved, not reset.
--
-- Four bridges (bridge-ravi-01, bridge-data-01, bridge-mall-01, bridge-thokar-01) and their
-- sensors are stray rows from the now-deleted scripts/seed_data.py — a second, Punjab-named seed
-- that was never the demo dataset (seed_sindh.py's four bridges are Sukkur/Guddu/Indus
-- Highway/Kotri). Confirmed via information_schema against the live instance: zero rows in any
-- of the other nine tenant tables reference these four bridge ids or their sensor ids, and
-- neither table has a delete-blocking trigger (unlike the SOR tables), so they are deleted first
-- rather than renamed into a tenant they were never part of.
-- ---------------------------------------------------------------------------------------------

BEGIN;

DELETE FROM sensors WHERE bridge_id IN
    ('bridge-ravi-01', 'bridge-data-01', 'bridge-mall-01', 'bridge-thokar-01');
DELETE FROM bridges WHERE id IN
    ('bridge-ravi-01', 'bridge-data-01', 'bridge-mall-01', 'bridge-thokar-01');

INSERT INTO municipalities (id, name)
VALUES ('municipality-sindh', 'Sindh Province')
ON CONFLICT (id) DO NOTHING;

UPDATE bridges             SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE raw_readings        SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE validated_readings  SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE analysis_results    SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE sensor_status       SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE decision_log        SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE risk_assessments    SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE report_artifacts    SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE alert_dispatches    SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';
UPDATE sensors             SET municipality_id = 'municipality-sindh' WHERE municipality_id = 'municipality-lahore';

WITH moved AS (
    DELETE FROM device_credentials
    WHERE municipality_id = 'municipality-lahore'
    RETURNING key_hash, bridge_id, device_label, status, created_at, last_used_at, revoked_at
)
INSERT INTO device_credentials
    (key_hash, bridge_id, municipality_id, device_label, status, created_at, last_used_at, revoked_at)
SELECT key_hash, bridge_id, 'municipality-sindh', device_label, status, created_at, last_used_at, revoked_at
FROM moved;

DELETE FROM municipalities WHERE id = 'municipality-lahore';

COMMIT;
