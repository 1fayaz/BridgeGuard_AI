-- Migration 0012 — municipalities (D101)
-- Database Layer (Spec 002): the TENANT ROOT. One row per municipality — the top of the ownership
-- chain municipalities -> bridges -> sensors -> readings. Every tenant-scoped row in the system must
-- be attributable, by following foreign keys, up to exactly one row here (spec FR-1). This is the
-- table the row-level-security predicate ultimately keys on (spec FR-4; RLS wired in 0016).
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB. A municipality is reference/config data (onboarded, never churned), so no
-- time-series access pattern applies here.
--
-- Key type: TEXT natural key (confirmed decision). The existing sensor/judgment tables key on TEXT
-- (sensor_id, bridge_id); a TEXT municipality id lets the hard tenancy FKs (0013/0015) wire in with
-- NO column-type change to any built table.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live constraint
-- enforcement is verified when an instance exists. The in-memory FakeTenantStore (src/db/tenant_store.py)
-- mirrors these guarantees for the logic tests, exactly as the DCA/SA/Risk/Report/Alert fakes do.

CREATE TABLE IF NOT EXISTS municipalities (
    -- The tenant identity. TEXT natural key (e.g. 'MUNI_A'); referenced by bridges.municipality_id
    -- and by the denormalized municipality_id the RLS predicate reads on every tenant table.
    id          TEXT        PRIMARY KEY,

    -- Human-readable name. Required — a tenant with no name is a data-entry error.
    name        TEXT        NOT NULL,

    -- When this municipality was onboarded (audit).
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A name must be meaningful, not blank whitespace.
    CONSTRAINT municipality_name_not_blank
        CHECK (length(btrim(name)) > 0)
);
