-- Migration 0001 — raw_readings (T201)
-- Data Collection Agent: the append-only system of record for every received
-- sensor payload. Constitution II: raw data is NEVER overwritten or deleted, only
-- appended; every downstream value must trace back to a row here.
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes
-- only — NO TimescaleDB. The composite index on (sensor_id, sensor_time) below covers
-- the time-series query patterns without a time-series extension.
--
-- [DB-DEP] This file is written and reviewable now. It cannot be executed/enforced
-- locally (no Neon instance); live append-only enforcement is verified when an
-- instance exists. The in-memory FakeStore (T801) mirrors these guarantees for tests.

CREATE TABLE IF NOT EXISTS raw_readings (
    -- Surface identity. BIGINT identity so derived rows can reference a stable id.
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- The sensor's OWN timestamp. This drives liveness + ordering (decision G4),
    -- NOT ingest_time. Stored separately from ingest_time so clock-drift is
    -- computable (|sensor_time - ingest_time| vs the per-type tolerance, T905).
    sensor_time   TIMESTAMPTZ NOT NULL,

    -- When WE received the payload. Used only for the clock-drift comparison and
    -- forensics — never for liveness/ordering.
    ingest_time   TIMESTAMPTZ NOT NULL DEFAULT now(),

    sensor_id     TEXT        NOT NULL,
    sensor_type   TEXT        NOT NULL,

    -- Nullable: a malformed/garbled payload still gets a raw row (it must never
    -- silently vanish — FR-6/AC-7); value may be absent or unparseable.
    value         DOUBLE PRECISION,
    unit          TEXT,

    -- The exact original payload, verbatim, for forensic replay and provenance.
    raw_payload   JSONB       NOT NULL
);

-- Most frequent access pattern: a sensor's readings over a recent window, in
-- sensor-time order (baseline window, gap detection, late-arrival lookback).
CREATE INDEX IF NOT EXISTS idx_raw_readings_sensor_time
    ON raw_readings (sensor_id, sensor_time DESC);

-- ---------------------------------------------------------------------------
-- Append-only enforcement (Constitution II / Operational Constraints).
-- Make immutability a DATABASE guarantee, not a code convention: the service
-- role may INSERT and SELECT, but UPDATE and DELETE are revoked. A bug that
-- tries to mutate raw data fails at the DB boundary.
--
-- NOTE: 'bridgeguard_service' is the application role. Adjust to the actual
-- Supabase role name at deploy time. Revoking from PUBLIC closes the default-grant
-- path; the explicit grant re-adds only the two safe verbs.
-- ---------------------------------------------------------------------------
REVOKE UPDATE, DELETE, TRUNCATE ON raw_readings FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bridgeguard_service') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON raw_readings FROM bridgeguard_service;
        GRANT  INSERT, SELECT             ON raw_readings TO   bridgeguard_service;
    END IF;
END $$;

-- Belt-and-braces: a trigger that hard-blocks UPDATE/DELETE even for roles that
-- might otherwise hold the privilege (e.g. the table owner / a superuser path),
-- so append-only holds regardless of grant drift.
CREATE OR REPLACE FUNCTION raw_readings_block_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'raw_readings is append-only (Constitution II): % blocked', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_raw_readings_no_update ON raw_readings;
CREATE TRIGGER trg_raw_readings_no_update
    BEFORE UPDATE OR DELETE ON raw_readings
    FOR EACH ROW EXECUTE FUNCTION raw_readings_block_mutation();

-- ---------------------------------------------------------------------------
-- No TimescaleDB (CLAUDE.md / constitution v2.1.0): Neon/Postgres with standard
-- B-tree indexes only. The composite (sensor_id, sensor_time DESC) index above is
-- the sanctioned covering index for the time-series access patterns; there is no
-- hypertable conversion. Time-series query patterns are served by that index.
-- ---------------------------------------------------------------------------
