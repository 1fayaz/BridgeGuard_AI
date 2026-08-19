-- Migration 0013 — bridges (D102)
-- Database Layer (Spec 002): the second link of the ownership chain
-- municipalities -> bridges -> sensors -> readings. One row per bridge; a bridge belongs to EXACTLY
-- one municipality (spec FR-1). This is the table the bridge-keyed judgment rows (risk_assessments
-- 0006, report_artifacts 0008, alert_dispatches 0010) resolve their tenant through (bridge_id ->
-- bridges.municipality_id, hard FKs wired in 0015).
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB. A bridge is reference/config data (onboarded, never churned), so no time-series
-- access pattern applies here; the (municipality_id) index below serves tenant listing + the RLS
-- predicate, not a time range.
--
-- Key type: TEXT natural key (confirmed decision), matching the existing bridge_id TEXT columns on
-- the judgment tables so their hard tenancy FKs (0015) wire in with NO column-type change.
--
-- FK discipline (plan §5): municipality_id is a HARD foreign key — isolation is a safety/privacy
-- guarantee (Principle III) that must be structurally impossible to violate, so an orphan bridge
-- (one whose municipality does not exist) is rejected by the database, not just by convention. The
-- parent (a municipality) is long-lived and never deleted, so there is no cascade-delete hazard.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live constraint
-- enforcement is verified when an instance exists. The in-memory FakeTenantStore
-- (src/db/tenant_store.py) mirrors the hard FK for the logic tests.

CREATE TABLE IF NOT EXISTS bridges (
    -- The bridge identity. TEXT natural key (e.g. 'BRIDGE_A1'); referenced by sensors.bridge_id and
    -- by the bridge-keyed judgment tables' denormalized bridge_id.
    id              TEXT        PRIMARY KEY,

    -- The owning municipality (ownership-chain link). HARD FK: a bridge under a non-existent
    -- municipality is rejected. NOT NULL — every bridge has a tenant.
    municipality_id TEXT        NOT NULL REFERENCES municipalities(id),

    -- Human-readable name + physical location. Name required; location free text (address / river /
    -- coordinates as onboarded).
    name            TEXT        NOT NULL,
    location        TEXT,

    -- When this bridge was onboarded (audit).
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A name must be meaningful, not blank whitespace.
    CONSTRAINT bridge_name_not_blank
        CHECK (length(btrim(name)) > 0)
);

-- Tenant listing + RLS predicate performance (plan §4): list a municipality's bridges, and back the
-- (municipality_id) equality the row-level-security policy uses. Standard B-tree; no TimescaleDB.
CREATE INDEX IF NOT EXISTS idx_bridges_municipality
    ON bridges (municipality_id);
