-- Migration 0015 — tenant_columns_and_fks (D301 / D302 / D304)
-- Database Layer (Spec 002): the WIRING migration that makes every tenant-scoped table
-- tenant-attributable, connecting the built tables (0001-0011) + the new analysis_results (0005) to
-- the tenancy foundation (municipalities 0012, bridges 0013, sensors 0014). This is where the
-- ownership chain municipalities -> bridges -> sensors -> readings becomes enforceable on the data
-- tables, so row-level security (0016) can key on a single denormalized municipality_id per row.
--
-- Built in three parts across three tasks, so each is independently reviewable:
--   PART A (D301, this section): ADD the denormalized municipality_id to every tenant-scoped table,
--          and ADD bridge_id to the sensor-keyed tables that only had sensor_id. Columns are added
--          NULLABLE here (no data to backfill on an empty DB; see the backfill note).
--   PART B (D302): add the HARD tenancy FKs (sensor_id -> sensors, bridge_id -> bridges,
--          municipality_id -> municipalities) and tighten the columns to NOT NULL.
--   PART C (D304): add the (municipality_id) B-tree index on each table (RLS predicate perf +
--          the <500ms overview read model).
--
-- Why denormalize municipality_id onto every table (plan §2): the RLS predicate is then a single
-- indexed equality `municipality_id = current_setting('app.current_municipality_id')`, not a
-- per-row join up the sensor -> bridge -> municipality chain. The value is set ONCE at insert (the
-- writing agent knows the sensor's bridge/municipality) and never changes — consistent with the
-- append-only / correct-by-supersede immutability. A consistency guard (D303) keeps it from drifting
-- from the FK chain.
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live enforcement
-- verified when an instance exists. The in-memory fakes mirror these guarantees for the logic tests.
--
-- BACKFILL NOTE (plan Open Item #4): on today's empty DB the ADD COLUMNs need no data backfill. When
-- a live instance first holds data, PART B's NOT NULL + FK validation must be preceded by a backfill
-- that populates municipality_id (and bridge_id) from the sensor -> bridge -> municipality chain.
-- That backfill step is a live-migration concern, not a code path exercised on the empty schema.

-- ===========================================================================
-- PART A (D301) — denormalized tenant columns, added NULLABLE.
-- ===========================================================================

-- --- sensor-keyed tables: only had sensor_id, so they gain BOTH bridge_id and municipality_id ---
-- (bridge_id is resolvable via sensor_id -> sensors.bridge_id; both are denormalized here so RLS +
--  bridge-scoped reads need no join.)

ALTER TABLE raw_readings        ADD COLUMN IF NOT EXISTS bridge_id       TEXT;
ALTER TABLE raw_readings        ADD COLUMN IF NOT EXISTS municipality_id TEXT;

ALTER TABLE validated_readings  ADD COLUMN IF NOT EXISTS bridge_id       TEXT;
ALTER TABLE validated_readings  ADD COLUMN IF NOT EXISTS municipality_id TEXT;

ALTER TABLE analysis_results    ADD COLUMN IF NOT EXISTS bridge_id       TEXT;
ALTER TABLE analysis_results    ADD COLUMN IF NOT EXISTS municipality_id TEXT;

ALTER TABLE sensor_status       ADD COLUMN IF NOT EXISTS bridge_id       TEXT;
ALTER TABLE sensor_status       ADD COLUMN IF NOT EXISTS municipality_id TEXT;

ALTER TABLE decision_log        ADD COLUMN IF NOT EXISTS bridge_id       TEXT;
ALTER TABLE decision_log        ADD COLUMN IF NOT EXISTS municipality_id TEXT;

-- --- judgment tables: ALREADY carry bridge_id (0006/0008/0010), so they gain ONLY municipality_id ---
-- (bridge_id is NOT re-added — an ADD COLUMN of an existing column would be a no-op with IF NOT
--  EXISTS, but we deliberately omit it to keep the intent explicit: these already have it.)

ALTER TABLE risk_assessments    ADD COLUMN IF NOT EXISTS municipality_id TEXT;

ALTER TABLE report_artifacts    ADD COLUMN IF NOT EXISTS municipality_id TEXT;

ALTER TABLE alert_dispatches    ADD COLUMN IF NOT EXISTS municipality_id TEXT;

-- ===========================================================================
-- PART B (D302) — the HARD tenancy foreign keys + NOT NULL tightening.
--
-- These are the FKs that make an orphan row structurally impossible (plan §5): isolation is a
-- safety/privacy guarantee (Principle III), so a reading whose sensor isn't onboarded, or any row
-- whose municipality is unknown, is rejected by the database. The parents (municipality/bridge/
-- sensor) are long-lived and never deleted, so there is no cascade-delete hazard — no ON DELETE
-- clause is added (the append-only/DELETE-blocked discipline means a cascade could never fire).
--
-- The SOFT provenance arrays (source_raw_ids / source_validated_ids / source_analysis_ids) are
-- DELIBERATELY untouched here — they stay plain BIGINT[] with no FK (agent independence; arrays
-- can't be FKs; must survive supersession — plan §5). Only the TENANCY columns get hard FKs.
--
-- BACKFILL ORDER (plan Open Item #4): on a live instance with data, each municipality_id/bridge_id
-- must be backfilled from the sensor -> bridge -> municipality chain BEFORE the SET NOT NULL and the
-- FK VALIDATE below. On today's empty schema there is nothing to backfill; the statements are a
-- no-op against zero rows.
-- ===========================================================================

-- One FK per statement (atomic + individually named, so each is separately reviewable/rollback-able).

-- --- sensor-keyed tables: sensor_id -> sensors, bridge_id -> bridges, municipality_id -> municipalities ---

ALTER TABLE raw_readings ADD CONSTRAINT fk_raw_readings_sensor       FOREIGN KEY (sensor_id)       REFERENCES sensors(id);
ALTER TABLE raw_readings ADD CONSTRAINT fk_raw_readings_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE raw_readings ADD CONSTRAINT fk_raw_readings_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE raw_readings ALTER COLUMN bridge_id       SET NOT NULL;
ALTER TABLE raw_readings ALTER COLUMN municipality_id SET NOT NULL;

ALTER TABLE validated_readings ADD CONSTRAINT fk_validated_sensor       FOREIGN KEY (sensor_id)       REFERENCES sensors(id);
ALTER TABLE validated_readings ADD CONSTRAINT fk_validated_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE validated_readings ADD CONSTRAINT fk_validated_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE validated_readings ALTER COLUMN bridge_id       SET NOT NULL;
ALTER TABLE validated_readings ALTER COLUMN municipality_id SET NOT NULL;

ALTER TABLE analysis_results ADD CONSTRAINT fk_analysis_sensor       FOREIGN KEY (sensor_id)       REFERENCES sensors(id);
ALTER TABLE analysis_results ADD CONSTRAINT fk_analysis_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE analysis_results ADD CONSTRAINT fk_analysis_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE analysis_results ALTER COLUMN bridge_id       SET NOT NULL;
ALTER TABLE analysis_results ALTER COLUMN municipality_id SET NOT NULL;

ALTER TABLE sensor_status ADD CONSTRAINT fk_sensor_status_sensor       FOREIGN KEY (sensor_id)       REFERENCES sensors(id);
ALTER TABLE sensor_status ADD CONSTRAINT fk_sensor_status_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE sensor_status ADD CONSTRAINT fk_sensor_status_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE sensor_status ALTER COLUMN bridge_id       SET NOT NULL;
ALTER TABLE sensor_status ALTER COLUMN municipality_id SET NOT NULL;

ALTER TABLE decision_log ADD CONSTRAINT fk_decision_log_sensor       FOREIGN KEY (sensor_id)       REFERENCES sensors(id);
ALTER TABLE decision_log ADD CONSTRAINT fk_decision_log_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE decision_log ADD CONSTRAINT fk_decision_log_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE decision_log ALTER COLUMN bridge_id       SET NOT NULL;
ALTER TABLE decision_log ALTER COLUMN municipality_id SET NOT NULL;

-- --- judgment tables: bridge_id already existed (0006/0008/0010) — add its FK + municipality_id FK ---

ALTER TABLE risk_assessments ADD CONSTRAINT fk_risk_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE risk_assessments ADD CONSTRAINT fk_risk_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE risk_assessments ALTER COLUMN municipality_id SET NOT NULL;

ALTER TABLE report_artifacts ADD CONSTRAINT fk_report_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE report_artifacts ADD CONSTRAINT fk_report_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE report_artifacts ALTER COLUMN municipality_id SET NOT NULL;

ALTER TABLE alert_dispatches ADD CONSTRAINT fk_alert_bridge       FOREIGN KEY (bridge_id)       REFERENCES bridges(id);
ALTER TABLE alert_dispatches ADD CONSTRAINT fk_alert_municipality FOREIGN KEY (municipality_id) REFERENCES municipalities(id);
ALTER TABLE alert_dispatches ALTER COLUMN municipality_id SET NOT NULL;

-- ===========================================================================
-- PART B (D303) — the denormalized-tenant CONSISTENCY GUARD.
--
-- The hard FKs above prove each of sensor_id / bridge_id / municipality_id points at a REAL parent —
-- but not that the denormalized copies AGREE with each other. Without this guard a writer could
-- insert a raw_reading for sensor S1 (which belongs to bridge A1 / municipality A) while stamping
-- bridge_id = B1 or municipality_id = B — every FK is individually satisfied, yet the row is
-- mis-attributed and RLS (which keys on the denormalized municipality_id) would file it under the
-- wrong tenant. That is the exact hazard denormalization introduces (plan §2), so the copy must be
-- provably the one the chain yields.
--
-- A column CHECK cannot do this (it cannot subquery the parent tables), so it is a trigger. The
-- denormalized columns are set once at insert and never change (append-only / correct-by-supersede),
-- so BEFORE INSERT OR UPDATE covers every write; the UPDATE branch simply never fires on the
-- append-only tables.
-- ===========================================================================

-- Sensor-keyed guard: both hops must agree — bridge_id = sensors.bridge_id for sensor_id, and
-- municipality_id = bridges.municipality_id for that bridge.
CREATE OR REPLACE FUNCTION tenant_consistency_sensor_keyed()
RETURNS TRIGGER AS $$
DECLARE
    chain_bridge_id       TEXT;
    chain_municipality_id TEXT;
BEGIN
    SELECT s.bridge_id INTO chain_bridge_id
        FROM sensors s WHERE s.id = NEW.sensor_id;
    IF NEW.bridge_id IS DISTINCT FROM chain_bridge_id THEN
        RAISE EXCEPTION
            'tenant drift: bridge_id % does not match sensor %''s bridge % (denormalized copy must match the sensor -> bridge chain)',
            NEW.bridge_id, NEW.sensor_id, chain_bridge_id;
    END IF;

    SELECT b.municipality_id INTO chain_municipality_id
        FROM bridges b WHERE b.id = NEW.bridge_id;
    IF NEW.municipality_id IS DISTINCT FROM chain_municipality_id THEN
        RAISE EXCEPTION
            'tenant drift: municipality_id % does not match bridge %''s municipality % (denormalized copy must match the bridge -> municipality chain)',
            NEW.municipality_id, NEW.bridge_id, chain_municipality_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Bridge-keyed (judgment) guard: municipality_id = bridges.municipality_id for bridge_id.
CREATE OR REPLACE FUNCTION tenant_consistency_bridge_keyed()
RETURNS TRIGGER AS $$
DECLARE
    chain_municipality_id TEXT;
BEGIN
    SELECT b.municipality_id INTO chain_municipality_id
        FROM bridges b WHERE b.id = NEW.bridge_id;
    IF NEW.municipality_id IS DISTINCT FROM chain_municipality_id THEN
        RAISE EXCEPTION
            'tenant drift: municipality_id % does not match bridge %''s municipality % (denormalized copy must match the bridge -> municipality chain)',
            NEW.municipality_id, NEW.bridge_id, chain_municipality_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach the sensor-keyed guard.
DROP TRIGGER IF EXISTS trg_tenant_consistency ON raw_readings;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON raw_readings
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_sensor_keyed();

DROP TRIGGER IF EXISTS trg_tenant_consistency ON validated_readings;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON validated_readings
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_sensor_keyed();

DROP TRIGGER IF EXISTS trg_tenant_consistency ON analysis_results;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON analysis_results
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_sensor_keyed();

DROP TRIGGER IF EXISTS trg_tenant_consistency ON sensor_status;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON sensor_status
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_sensor_keyed();

DROP TRIGGER IF EXISTS trg_tenant_consistency ON decision_log;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON decision_log
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_sensor_keyed();

-- Attach the bridge-keyed guard.
DROP TRIGGER IF EXISTS trg_tenant_consistency ON risk_assessments;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON risk_assessments
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_bridge_keyed();

DROP TRIGGER IF EXISTS trg_tenant_consistency ON report_artifacts;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON report_artifacts
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_bridge_keyed();

DROP TRIGGER IF EXISTS trg_tenant_consistency ON alert_dispatches;
CREATE TRIGGER trg_tenant_consistency
    BEFORE INSERT OR UPDATE ON alert_dispatches
    FOR EACH ROW EXECUTE FUNCTION tenant_consistency_bridge_keyed();

-- ===========================================================================
-- PART C (D304) — index the denormalized municipality_id (the RLS predicate).
--
-- RLS keys every tenant read on `municipality_id = current_setting('app.current_municipality_id')`
-- (plan §2), and the municipality overview read model filters the same way. That is why the tenant
-- column is denormalized down onto every table in the first place: so the predicate is a single
-- indexed equality, not a per-row join up the ownership chain. A B-tree on (municipality_id) makes
-- that predicate index-backed instead of a sequential scan on every RLS-filtered query.
--
-- Only the eight tables that GAINED municipality_id in part A are indexed here. bridges already
-- carries idx_bridges_municipality (0013); municipalities is filtered on its own PRIMARY KEY id;
-- sensors is bridge-keyed (reached via its bridge). Standard B-tree only — no TimescaleDB (v2.1.0).
-- ===========================================================================
CREATE INDEX IF NOT EXISTS idx_raw_readings_municipality       ON raw_readings (municipality_id);
CREATE INDEX IF NOT EXISTS idx_validated_readings_municipality ON validated_readings (municipality_id);
CREATE INDEX IF NOT EXISTS idx_analysis_results_municipality   ON analysis_results (municipality_id);
CREATE INDEX IF NOT EXISTS idx_sensor_status_municipality      ON sensor_status (municipality_id);
CREATE INDEX IF NOT EXISTS idx_decision_log_municipality       ON decision_log (municipality_id);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_municipality   ON risk_assessments (municipality_id);
CREATE INDEX IF NOT EXISTS idx_report_artifacts_municipality   ON report_artifacts (municipality_id);
CREATE INDEX IF NOT EXISTS idx_alert_dispatches_municipality   ON alert_dispatches (municipality_id);
