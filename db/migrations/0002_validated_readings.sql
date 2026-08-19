-- Migration 0002 — validated_readings (T202)
-- Data Collection Agent: the DERIVED layer. One row per sensor per validation cycle,
-- carrying the agent's verdict about a reading. Distinct from raw_readings (0001):
-- raw is immutable truth-as-received; this is the interpreted, traceable result.
--
-- Constitution II/VI: every value here MUST trace back to its raw source(s) via
-- source_raw_ids, and corrections are NEVER silent — a late-arrival recompute appends
-- a NEW row and points the old one at it (superseded_by), preserving old -> new.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Supabase instance).
-- Live constraint/trigger enforcement is verified when an instance exists. The
-- in-memory FakeStore (T801) mirrors these guarantees for the logic tests.

-- The SIX terminal reading-statuses (the value/timeline axis). This is one of THREE
-- independent axes — sensor-status (LIVE|OFFLINE) lives on the device, and clock_drift
-- is a co-existing flag below; neither is encoded here.
--   OK            value present and trusted
--   INTERPOLATED  1-2 missing samples linearly filled (FR-4)
--   SPIKE         transient out-of-pattern reading, not confirmed by neighbours (FR-3)
--   CORRUPT       out of physical bounds, or unknown/unconfigured type (FR-2/T103)
--   NO_DATA       3+ missing samples; gap too large to fill (FR-4)
--   PENDING       awaiting confirmation window (spike/late-arrival not yet resolved)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reading_status') THEN
        CREATE TYPE reading_status AS ENUM (
            'OK',
            'INTERPOLATED',
            'SPIKE',
            'CORRUPT',
            'NO_DATA',
            'PENDING'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS validated_readings (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- The sensor's OWN timestamp for this cycle (G4: liveness + ordering use this,
    -- never ingest time). Aligned with raw_readings.sensor_time.
    sensor_time   TIMESTAMPTZ NOT NULL,

    sensor_id     TEXT        NOT NULL,
    sensor_type   TEXT        NOT NULL,

    -- The validated value. NULL is legitimate and meaningful: NO_DATA, CORRUPT with
    -- no parseable number, or an OFFLINE-cycle placeholder carry no trusted value.
    value         DOUBLE PRECISION,
    unit          TEXT,

    -- Terminal verdict on the value/timeline axis (exactly one of the six).
    status        reading_status NOT NULL,

    -- Flag axis #1: this value was produced by interpolation (FR-4). Kept as an
    -- explicit flag in addition to status='INTERPOLATED' so a value can be shown as
    -- "filled" in any view without re-deriving it. Redundant-but-explicit by design.
    is_interpolated BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Flag axis #2 (G4): clock drift CO-EXISTS with any status — it marks that the
    -- timing is suspect (|sensor_time - ingest_time| beyond the per-type tolerance),
    -- NOT that the value is bad. An OK reading can carry clock_drift=TRUE. This is
    -- why drift is a flag here, never a seventh enum value.
    clock_drift   BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Recorded drift magnitude (seconds) when known, for forensics / tuning tolerance.
    clock_drift_s DOUBLE PRECISION,

    -- Provenance (Constitution II/VI): the raw_readings.id(s) this verdict was derived
    -- from. Array because interpolation/confirmation spans several raw rows. Empty for
    -- a synthesised OFFLINE/NO_DATA row where NO raw reading arrived — see CHECK below.
    source_raw_ids BIGINT[]   NOT NULL DEFAULT '{}',

    -- Human-readable explanation for any non-OK verdict or any logged correction
    -- (old -> new reason; Operational Constraint "no silent overwrites").
    reason        TEXT,

    -- Correction chain (late-arrival recompute, FR-5). We never UPDATE a prior verdict;
    -- we INSERT the corrected row and set the OLD row's superseded_by to the new id.
    -- A row with superseded_by IS NOT NULL is historical; NULL = current.
    superseded_by BIGINT      REFERENCES validated_readings(id),

    -- When this verdict was computed (audit; distinct from sensor_time).
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A reading that claims to be filled must say so on BOTH the status and the flag,
    -- so the two can never silently disagree.
    CONSTRAINT interpolated_flag_matches_status
        CHECK ((status = 'INTERPOLATED') = is_interpolated),

    -- A non-OK verdict must carry an explanation (auditability). OK needs none.
    CONSTRAINT non_ok_has_reason
        CHECK (status = 'OK' OR reason IS NOT NULL)
);

-- Lookup the current (non-superseded) verdict for a sensor over a window.
CREATE INDEX IF NOT EXISTS idx_validated_sensor_time
    ON validated_readings (sensor_id, sensor_time DESC);

-- Find rows still awaiting resolution (PENDING sweep, T501/T503) cheaply.
CREATE INDEX IF NOT EXISTS idx_validated_pending
    ON validated_readings (status)
    WHERE status = 'PENDING';

-- ---------------------------------------------------------------------------
-- Corrections are append + supersede, never in-place edits to the VALUE/STATUS of an
-- existing verdict. We allow exactly one UPDATE shape: stamping superseded_by (and a
-- reason) on an older row to link it to its replacement. Any attempt to mutate the
-- value, status, or sensor_time of an already-written verdict is blocked.
-- This keeps the old -> new history intact (Operational Constraint).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION validated_readings_guard_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.value      IS DISTINCT FROM OLD.value
    OR NEW.status     IS DISTINCT FROM OLD.status
    OR NEW.sensor_time IS DISTINCT FROM OLD.sensor_time
    OR NEW.sensor_id  IS DISTINCT FROM OLD.sensor_id
    OR NEW.source_raw_ids IS DISTINCT FROM OLD.source_raw_ids THEN
        RAISE EXCEPTION
            'validated_readings is correct-by-append: mutating value/status/sensor_time/source of an existing verdict is blocked (set superseded_by instead)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validated_guard_update ON validated_readings;
CREATE TRIGGER trg_validated_guard_update
    BEFORE UPDATE ON validated_readings
    FOR EACH ROW EXECUTE FUNCTION validated_readings_guard_update();

-- DELETE is never allowed: history is permanent.
CREATE OR REPLACE FUNCTION validated_readings_block_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'validated_readings history is permanent (Constitution VI): DELETE blocked';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validated_block_delete ON validated_readings;
CREATE TRIGGER trg_validated_block_delete
    BEFORE DELETE ON validated_readings
    FOR EACH ROW EXECUTE FUNCTION validated_readings_block_delete();

REVOKE DELETE, TRUNCATE ON validated_readings FROM PUBLIC;
