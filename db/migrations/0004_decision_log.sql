-- Migration 0004 — decision_log (T204)
-- Data Collection Agent: the append-only AUDIT TRAIL. Every decision the agent makes
-- about a reading or a sensor lands here with the input that caused it and a
-- human-readable reason. Constitution VI (auditability): a human can reconstruct WHY
-- any value was shown, suppressed, corrected, or flagged — from this table alone.
--
-- This is the permanent history. sensor_status (0003) holds only CURRENT device state;
-- the LIVE<->OFFLINE transitions that produced it are LIVENESS rows here. Likewise a
-- corrected verdict in validated_readings (0002) has a CORRECTION row here recording
-- old_status -> new_status.
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes
-- only — NO TimescaleDB.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance).
-- Live enforcement verified when an instance exists; the FakeStore (T903) mirrors it.

-- The decision types the agent logs. One per kind of judgement in the pipeline:
--   LIVENESS           sensor went OFFLINE / came back LIVE (T301)
--   RANGE              value rejected as out-of-bounds -> CORRUPT (T401)
--   SPIKE              spike candidate raised / finalised (T502/T503)
--   GAP                gap interpolated (INTERPOLATED) or too large (NO_DATA) (T601)
--   PENDING            a spike/late candidate written PENDING, or resolved (T701)
--   CORRECTION         a prior verdict superseded by a late-arrival recompute (T801)
--   PARSE              a malformed payload coerced to CORRUPT (T902)
--   CLOCK_DRIFT        sensor/ingest gap exceeded tolerance; reading flagged (T905)
--   DUPLICATE_CONFLICT same sensor+ts, different value; first-received kept (T904)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'decision_kind') THEN
        CREATE TYPE decision_kind AS ENUM (
            'LIVENESS',
            'RANGE',
            'SPIKE',
            'GAP',
            'PENDING',
            'CORRECTION',
            'PARSE',
            'CLOCK_DRIFT',
            'DUPLICATE_CONFLICT'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS decision_log (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- When the DECISION was made (audit clock). The reading's own sensor timestamp,
    -- when relevant, is carried in raw_payload / referenced via raw_value below.
    decided_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),

    sensor_id     TEXT          NOT NULL,

    decision      decision_kind NOT NULL,

    -- Status transition, when the decision changed one. For a CORRECTION this is the
    -- whole point: old_status -> new_status (e.g. 'SPIKE' -> 'OK'). For a LIVENESS flip
    -- it is 'LIVE' -> 'OFFLINE'. NULL when the decision sets an initial status with no
    -- prior. Kept as free TEXT (not the enum) so it can hold EITHER a reading_status OR
    -- a sensor_health value — the two axes share this one audit column.
    old_status    TEXT,
    new_status    TEXT,

    -- The causing input, for traceability (Const. II/VI). raw_value is the parsed number
    -- when there was one; raw_payload is the verbatim original message. For a
    -- DUPLICATE_CONFLICT both the kept and discarded values live in raw_payload (see below).
    raw_value     DOUBLE PRECISION,
    raw_payload   JSONB,

    -- The raw_readings row(s) this decision concerns, so the audit entry links back to
    -- immutable source (every number traceable — Const. II).
    source_raw_ids BIGINT[]     NOT NULL DEFAULT '{}',

    -- The human-readable explanation. REQUIRED — an audit entry with no reason explains
    -- nothing (Const. VI). For DUPLICATE_CONFLICT this records BOTH values + the exact
    -- string "duplicate timestamp, conflicting value, first-received kept" (G4 dup rule).
    -- For CLOCK_DRIFT it records the measured gap and the tolerance (G4).
    -- For CORRECTION it records "late-arrival recompute".
    reason        TEXT          NOT NULL,

    CONSTRAINT reason_not_blank CHECK (length(btrim(reason)) > 0)
);

-- Reconstruct a sensor's decision history in order (forensics / audit view).
CREATE INDEX IF NOT EXISTS idx_decision_log_sensor_time
    ON decision_log (sensor_id, decided_at DESC);

-- Filter the log by decision type (e.g. "show all CORRECTIONs", "all CLOCK_DRIFTs").
CREATE INDEX IF NOT EXISTS idx_decision_log_decision
    ON decision_log (decision);

-- ---------------------------------------------------------------------------
-- Append-only audit trail (Constitution VI). Like raw_readings, the log is written
-- once and never edited or deleted: an audit trail you can rewrite is not an audit
-- trail. REVOKE UPDATE/DELETE/TRUNCATE + a hard-blocking trigger.
-- ---------------------------------------------------------------------------
REVOKE UPDATE, DELETE, TRUNCATE ON decision_log FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bridgeguard_service') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON decision_log FROM bridgeguard_service;
        GRANT  INSERT, SELECT              ON decision_log TO   bridgeguard_service;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION decision_log_block_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'decision_log is append-only (Constitution VI): % blocked', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_decision_log_no_mutation ON decision_log;
CREATE TRIGGER trg_decision_log_no_mutation
    BEFORE UPDATE OR DELETE ON decision_log
    FOR EACH ROW EXECUTE FUNCTION decision_log_block_mutation();
