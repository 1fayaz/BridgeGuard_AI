-- Migration 0014 — sensors (D103)
-- Database Layer (Spec 002): the third link of the ownership chain
-- municipalities -> bridges -> sensors -> readings. One row per physical sensor; a sensor belongs to
-- EXACTLY one bridge (spec FR-1). This is the join that makes the sensor-keyed tables tenant-
-- attributable: raw_readings / validated_readings / analysis_results carry a sensor_id, and this
-- table resolves that sensor_id -> bridge_id -> municipality_id (spec FR-2; hard FKs on the
-- reading tables wired in 0015).
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB. A sensor is reference/config data (onboarded, never churned), so no time-series
-- access pattern applies here; the (bridge_id) index below serves the bridge-detail sensor listing,
-- not a time range. (The time-series indexes live on the READING tables, keyed (sensor_id,
-- sensor_time) — migrations 0001/0002.)
--
-- Key type: TEXT natural key (confirmed decision), matching the existing sensor_id TEXT columns on
-- the reading tables so their hard tenancy FKs (0015) wire in with NO column-type change.
--
-- FK discipline (plan §5): bridge_id is a HARD foreign key — isolation is a safety/privacy guarantee
-- (Principle III) that must be structurally impossible to violate, so an orphan sensor (one whose
-- bridge does not exist) is rejected by the database, not just by convention. The parent (a bridge)
-- is long-lived and never deleted, so there is no cascade-delete hazard.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live constraint
-- enforcement is verified when an instance exists. The in-memory FakeTenantStore
-- (src/db/tenant_store.py) mirrors the hard FK for the logic tests.

CREATE TABLE IF NOT EXISTS sensors (
    -- The sensor identity. TEXT natural key (e.g. 'SENSOR_1'); this is the sensor_id the reading
    -- tables (raw_readings 0001, validated_readings 0002, analysis_results 0005) key on.
    id           TEXT        PRIMARY KEY,

    -- The owning bridge (ownership-chain link). HARD FK: a sensor under a non-existent bridge is
    -- rejected. NOT NULL — every sensor has a bridge (and thus, transitively, a municipality).
    bridge_id    TEXT        NOT NULL REFERENCES bridges(id),

    -- The sensor kind (accelerometer, strain_gauge, crack, load_cell, temperature, tiltmeter,
    -- displacement/LVDT — the SA/DCA type catalogue). Free TEXT here; the calc-to-type mapping lives
    -- in the shared sensor registry/profiles (SA §111), not as a DB enum, so onboarding a new type
    -- is config, not a migration.
    sensor_type  TEXT        NOT NULL,

    -- Per-sensor configuration (thresholds, sample rate, reference-zero, etc.), as a JSONB blob so
    -- the shape can evolve with the registry without a schema change. The exact contents are a
    -- design decision deferred to the DCA/SA registry (plan Open Item); the column holds it.
    config       JSONB       NOT NULL DEFAULT '{}',

    -- When this sensor was onboarded (audit).
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A sensor_type must be meaningful, not blank whitespace.
    CONSTRAINT sensor_type_not_blank
        CHECK (length(btrim(sensor_type)) > 0)
);

-- Bridge-detail sensor listing (plan §4): list a bridge's sensors. Standard B-tree; no TimescaleDB.
CREATE INDEX IF NOT EXISTS idx_sensors_bridge
    ON sensors (bridge_id);
