-- Migration 0003 — sensor_status (T203)
-- Data Collection Agent: the DEVICE-HEALTH axis. One CURRENT row per sensor recording
-- whether the device itself is reporting (LIVE) or has gone silent (OFFLINE). This is
-- the second of the three independent axes:
--   * sensor_status (this table) — is the DEVICE alive?           LIVE | OFFLINE
--   * validated_readings.status (0002) — is the VALUE trustworthy? six terminal values
--   * validated_readings.clock_drift (0002) — is the TIMING trustworthy? a flag
-- They co-exist: a sensor can be OFFLINE here AND have a NO_DATA reading row in 0002 for
-- the same cycle (Q4 / AC-4). One does not replace the other.
--
-- G2 (single owner): OFFLINE/LIVE is written ONLY by the liveness path (T301). No other
-- check may set it. This table is the system of record for that one decision.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Supabase instance).
-- Live enforcement verified when an instance exists; the FakeStore (T801/T903) mirrors it.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sensor_health') THEN
        CREATE TYPE sensor_health AS ENUM ('LIVE', 'OFFLINE');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS sensor_status (
    -- One current row per sensor: the sensor_id IS the key. The full LIVE/OFFLINE
    -- transition history lives in decision_log (0004, LIVENESS entries), so this table
    -- holds only the latest state — distinct from the append-only audit trail.
    sensor_id     TEXT          PRIMARY KEY,

    status        sensor_health NOT NULL,

    -- Consecutive missed reports counted against the per-type cadence (T301). When this
    -- reaches the profile's offline_after_n (=3), status flips to OFFLINE.
    missed_count  INTEGER       NOT NULL DEFAULT 0,

    -- The sensor's OWN timestamp of its last received reading (G4 — sensor time, never
    -- ingest time). Liveness measures silence from this, not from the wall clock.
    last_seen     TIMESTAMPTZ,

    -- When this status row was last written (audit; distinct from last_seen).
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT missed_count_non_negative CHECK (missed_count >= 0)
);

-- Find all currently-offline sensors quickly (dashboards / alerting reads).
CREATE INDEX IF NOT EXISTS idx_sensor_status_offline
    ON sensor_status (status)
    WHERE status = 'OFFLINE';

-- This table is mutable by design: it is current-state, not history. The permanent
-- record of every transition is decision_log (0004). DELETE/TRUNCATE are still revoked
-- so a sensor's state cannot be made to silently vanish (silence != safety).
REVOKE DELETE, TRUNCATE ON sensor_status FROM PUBLIC;
