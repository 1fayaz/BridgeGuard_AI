-- Seed: seed_dev.sql (D701) — dev / test tenancy fixture.
-- Database Layer (Spec 002). This is DATA, not schema: it lives OUTSIDE db/migrations/ (plan §6) and
-- is never part of a numbered migration sequence. Load it into a dev/test database AFTER the
-- migrations 0001-0016 have created the schema, to give the isolation, provenance, and overview
-- tests a real two-tenant ownership chain to exercise.
--
-- [DB-DEP] No Neon instance locally, so this file is not executed by the test suite; the D701 test
-- parses it structurally and replays its chain through FakeTenantStore (which enforces the same hard
-- FKs the live DB does). On a live instance, run this once against an empty (or truncated dev) schema.
--
-- What it establishes (plan §6, spec §Testability / AC-1):
--   * TWO municipalities — MUNI_A, MUNI_B — because isolation (AC-4) is only provable with two tenants.
--   * MUNI_A owns TWO bridges (BRIDGE_A1, BRIDGE_A2); MUNI_B owns one (BRIDGE_B1). This gives both an
--     intra-tenant multi-bridge overview and a cross-tenant pair for the A-can't-see-B proof (D601).
--   * Under BRIDGE_A1, ONE sensor of EACH sensor_type the SA/DCA catalogue handles
--     (accelerometer, strain_gauge, crack_sensor, load_cell, temperature, tiltmeter,
--     displacement_lvdt — see src/agents/data_collection/config/sensor_profiles.py), so every
--     SA-handled type has a real sensor_id that resolves up the chain to MUNI_A.
--
-- Idempotent: ON CONFLICT DO NOTHING so a re-run on an already-seeded dev DB is a no-op.

-- --- municipalities (tenant roots) ------------------------------------------------------------
INSERT INTO municipalities (id, name) VALUES
    ('MUNI_A', 'Alpha City'),
    ('MUNI_B', 'Beta Town')
ON CONFLICT (id) DO NOTHING;

-- --- bridges (ownership-chain link 2) ---------------------------------------------------------
INSERT INTO bridges (id, municipality_id, name, location) VALUES
    ('BRIDGE_A1', 'MUNI_A', 'North Span',  'Alpha River crossing, north'),
    ('BRIDGE_A2', 'MUNI_A', 'South Span',  'Alpha River crossing, south'),
    ('BRIDGE_B1', 'MUNI_B', 'East Span',   'Beta Creek crossing, east')
ON CONFLICT (id) DO NOTHING;

-- --- sensors (ownership-chain link 3) — full type catalogue under BRIDGE_A1 --------------------
INSERT INTO sensors (id, bridge_id, sensor_type, config) VALUES
    ('SENSOR_A1_ACC',  'BRIDGE_A1', 'accelerometer',     '{}'),
    ('SENSOR_A1_STR',  'BRIDGE_A1', 'strain_gauge',      '{}'),
    ('SENSOR_A1_CRK',  'BRIDGE_A1', 'crack_sensor',      '{}'),
    ('SENSOR_A1_LOAD', 'BRIDGE_A1', 'load_cell',         '{}'),
    ('SENSOR_A1_TEMP', 'BRIDGE_A1', 'temperature',       '{}'),
    ('SENSOR_A1_TILT', 'BRIDGE_A1', 'tiltmeter',         '{}'),
    ('SENSOR_A1_LVDT', 'BRIDGE_A1', 'displacement_lvdt', '{}'),
    -- a couple of sensors on the other bridges so downstream seed (D702) has cross-tenant data.
    ('SENSOR_A2_ACC',  'BRIDGE_A2', 'accelerometer',     '{}'),
    ('SENSOR_B1_ACC',  'BRIDGE_B1', 'accelerometer',     '{}')
ON CONFLICT (id) DO NOTHING;

-- ==============================================================================================
-- D702 — shallow DOWNSTREAM seed: a minimal end-to-end provenance chain + one current risk row
-- per bridge, so the provenance-walk (D801/AC-5) and overview (D504/AC-11) tests have real rows.
--
-- The chain, one slice per bridge's primary sensor:
--   raw_readings  --source_raw_ids-->  validated_readings  --source_validated_ids-->
--   analysis_results  --source_analysis_ids-->  risk_assessments
--
-- Ids are pinned with OVERRIDING SYSTEM VALUE so the provenance arrays reference DETERMINISTIC ids
-- (the tables use GENERATED ALWAYS AS IDENTITY). Every data row carries the denormalized
-- (bridge_id, municipality_id) its sensor's chain yields — the 0015 consistency guard would reject
-- any drift, so the seed is written to satisfy it. Minimal by design; agents' harnesses make richer
-- data. Idempotent via ON CONFLICT on the pinned id.
-- ==============================================================================================

-- --- raw_readings (immutable source) : ids 1..3, one per bridge's accelerometer -----------------
INSERT INTO raw_readings
    (id, sensor_time, sensor_id, bridge_id, municipality_id, sensor_type, value, unit, raw_payload)
OVERRIDING SYSTEM VALUE VALUES
    (1, '2026-07-15T12:00:00Z', 'SENSOR_A1_ACC', 'BRIDGE_A1', 'MUNI_A', 'accelerometer', 0.40, 'm/s^2', '{"v":0.40}'),
    (2, '2026-07-15T12:00:00Z', 'SENSOR_A2_ACC', 'BRIDGE_A2', 'MUNI_A', 'accelerometer', 0.55, 'm/s^2', '{"v":0.55}'),
    (3, '2026-07-15T12:00:00Z', 'SENSOR_B1_ACC', 'BRIDGE_B1', 'MUNI_B', 'accelerometer', 0.90, 'm/s^2', '{"v":0.90}')
ON CONFLICT (id) DO NOTHING;

-- --- validated_readings : ids 1..3, each tracing to its raw row ---------------------------------
INSERT INTO validated_readings
    (id, sensor_time, sensor_id, bridge_id, municipality_id, sensor_type, value, unit, status, source_raw_ids, input_version)
OVERRIDING SYSTEM VALUE VALUES
    (1, '2026-07-15T12:00:00Z', 'SENSOR_A1_ACC', 'BRIDGE_A1', 'MUNI_A', 'accelerometer', 0.40, 'm/s^2', 'OK', '{1}', 'v1'),
    (2, '2026-07-15T12:00:00Z', 'SENSOR_A2_ACC', 'BRIDGE_A2', 'MUNI_A', 'accelerometer', 0.55, 'm/s^2', 'OK', '{2}', 'v1'),
    (3, '2026-07-15T12:00:00Z', 'SENSOR_B1_ACC', 'BRIDGE_B1', 'MUNI_B', 'accelerometer', 0.90, 'm/s^2', 'OK', '{3}', 'v1')
ON CONFLICT (id) DO NOTHING;

-- --- analysis_results : ids 1..3, each a RAN RMS result tracing to its validated row ------------
INSERT INTO analysis_results
    (id, sensor_id, bridge_id, municipality_id, calculation, block_id, outcome, value, passed,
     source_validated_ids, input_version, config_version)
OVERRIDING SYSTEM VALUE VALUES
    (1, 'SENSOR_A1_ACC', 'BRIDGE_A1', 'MUNI_A', 'RMS', 'blk-A1-1', 'RAN', 0.40, TRUE, '{1}', 'v1', 'cfg-1'),
    (2, 'SENSOR_A2_ACC', 'BRIDGE_A2', 'MUNI_A', 'RMS', 'blk-A2-1', 'RAN', 0.55, TRUE, '{2}', 'v1', 'cfg-1'),
    (3, 'SENSOR_B1_ACC', 'BRIDGE_B1', 'MUNI_B', 'RMS', 'blk-B1-1', 'RAN', 0.90, TRUE, '{3}', 'v1', 'cfg-1')
ON CONFLICT (id) DO NOTHING;

-- --- risk_assessments : one CURRENT row per bridge, tracing to its analysis row -----------------
INSERT INTO risk_assessments
    (id, bridge_id, municipality_id, cycle_id, risk_score, severity, recommendation, explanation,
     review_status, source_analysis_ids, standard_code, standard_version, score_weights_version,
     model_id, model_version, trace_id)
OVERRIDING SYSTEM VALUE VALUES
    (1, 'BRIDGE_A1', 'MUNI_A', 'cycle-1', 35, 'WATCH',
     'Increase inspection frequency.', 'RMS within band, monitoring.',
     'FINAL', '{1}', 'IRC:6', '2017', 'w1', 'seed-model', '1', 'trace-seed-A1'),
    (2, 'BRIDGE_A2', 'MUNI_A', 'cycle-1', 45, 'WATCH',
     'Increase inspection frequency.', 'RMS within band, monitoring.',
     'FINAL', '{2}', 'IRC:6', '2017', 'w1', 'seed-model', '1', 'trace-seed-A2'),
    (3, 'BRIDGE_B1', 'MUNI_B', 'cycle-1', 80, 'WARNING',
     'Schedule detailed inspection.', 'RMS elevated, review advised.',
     'FINAL', '{3}', 'IRC:6', '2017', 'w1', 'seed-model', '1', 'trace-seed-B1')
ON CONFLICT (id) DO NOTHING;
