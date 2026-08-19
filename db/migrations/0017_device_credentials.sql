-- Migration 0017 — device_credentials (P201)
-- API Layer (specs/api): the Pi gateway's credential store. One row per physical Raspberry Pi
-- gateway. This is the table that makes the Pi's per-device API key take the SAME isolation path as
-- an engineer's municipality-scoped JWT: the presented key resolves here to EXACTLY ONE bridge_id +
-- municipality_id, and that municipality_id is what the request sets as
-- `app.current_municipality_id` before any query runs (spec INV-1, §Authentication B). Only the
-- credential SHAPE differs between a Pi and a dashboard user; the enforcement MECHANISM is identical.
--
-- Slot: 0017 is the next free number — the database layer (Spec 002) ended at 0016_rls_policies;
-- verified 2026-07-31 that 0001-0016 exist with no gaps and nothing was appended after 0016.
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB. A device credential is reference/config data (a Pi is onboarded once, then
-- long-lived), so no time-series access pattern applies; the indexes below serve credential LOOKUP
-- on presentation, not a time range.
--
-- Ownership (plan §2a): this table is owned by the API layer. No agent reads or writes it — a Pi
-- credential is a boundary concept, and the agents downstream of ingestion never see a credential,
-- only the raw rows it authorised.
--
-- ---------------------------------------------------------------------------------------------
-- THREE DISCIPLINES, each enforced structurally rather than by convention:
--
-- 1. NO PLAINTEXT KEY, EVER. Only `key_hash` is stored. A stolen database dump must not yield
--    working device credentials, so there is deliberately NO column that could hold the raw secret.
--    The raw key exists in exactly two places: the Pi's own `.env` file, and the operator's hands at
--    issuance. It is never committed, never logged, and never written here.
--
-- 2. REVOCATION IS A STATE CHANGE, NOT A DELETE. A regulator asking "which device sent this reading,
--    and was it authorised at the time?" needs the credential row to still exist long after the
--    device is decommissioned. So `status` flips to 'revoked' and `revoked_at` is stamped; the row
--    stays. DELETE is BLOCKED in-engine below — the same append-only discipline the SOR tables use
--    (0001 raw_readings, 0004 decision_log), for the same auditability reason (Principle VI).
--
-- 3. A CREDENTIAL RESOLVES TO EXACTLY ONE BRIDGE. `bridge_id` is a HARD foreign key, so a credential
--    naming a non-existent bridge is rejected by the database, not merely by application code
--    (plan §5 FK discipline). Because the key pins a bridge, a compromised Pi key cannot append
--    readings for any other bridge — the blast radius of one stolen key is one bridge.
-- ---------------------------------------------------------------------------------------------
--
-- Tenancy (0015 pattern): `municipality_id` is DENORMALIZED onto this table and hard-FK'd, exactly
-- like every other tenant-scoped table, so the RLS predicate stays a single indexed equality rather
-- than a join up the ownership chain. It is redundant with bridge_id -> bridges.municipality_id by
-- construction; the consistency guard below keeps the two honest (mirroring 0015's guard trigger).
--
-- [DB-DEP] Written and reviewable now; NOT executable locally (no Neon instance). Live constraint,
-- trigger, and RLS-policy enforcement is verified when an instance exists. The in-memory
-- FakeCredentialStore (src/db/credential_store.py) mirrors every guarantee for the logic tests.

CREATE TABLE IF NOT EXISTS device_credentials (
    -- Surrogate credential identity. Operators revoke and rotate BY this id, never by key material,
    -- so a credential can be discussed, logged, and audited without the secret being near it.
    credential_id   BIGSERIAL   PRIMARY KEY,

    -- The credential secret, HASHED. Never the raw key (discipline 1 above). UNIQUE so one physical
    -- key maps to at most one credential row: presenting a key resolves to exactly one device, and a
    -- second row claiming the same hash is rejected in-engine rather than causing an ambiguous
    -- lookup that silently picks a row.
    key_hash        TEXT        NOT NULL UNIQUE,

    -- The ONE bridge this device may append readings for. HARD FK (discipline 3).
    bridge_id       TEXT        NOT NULL REFERENCES bridges(id),

    -- The owning tenant, denormalized for the RLS predicate. HARD FK. Kept consistent with
    -- bridge_id's owner by the guard trigger below.
    municipality_id TEXT        NOT NULL REFERENCES municipalities(id),

    -- Operator-facing label: WHICH physical Pi this is ('Pi at north abutment'). For humans doing
    -- field work; carries no authorisation meaning.
    device_label    TEXT        NOT NULL,

    -- Lifecycle state. Closed set, CHECK-enforced (not free text): a typo'd status must not silently
    -- become a third, unhandled state.
    status          TEXT        NOT NULL DEFAULT 'active',

    -- Issuance audit.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Last successful authentication with this credential. Operational visibility: a Pi that has
    -- stopped presenting its key is either offline or replaced. NULL until first use.
    last_used_at    TIMESTAMPTZ,

    -- When revoked (discipline 2). NULL while active; stamped on revocation. The row is never removed.
    revoked_at      TIMESTAMPTZ,

    CONSTRAINT device_credentials_status_closed_set
        CHECK (status IN ('active', 'revoked')),

    -- A label must be meaningful, not blank whitespace (mirrors 0014's sensor_type guard).
    CONSTRAINT device_credentials_label_not_blank
        CHECK (length(btrim(device_label)) > 0),

    -- A hash must be substantial. Guards against an application bug storing '' or a truncated value,
    -- which would otherwise become a trivially-presentable credential.
    CONSTRAINT device_credentials_key_hash_substantial
        CHECK (length(btrim(key_hash)) >= 32),

    -- The two states must be internally consistent: revoked implies a revocation timestamp, and an
    -- active credential must NOT carry one. Without this, a half-applied revocation (status flipped,
    -- timestamp missing) would read as revoked to the app but be indistinguishable from a bug to an
    -- auditor.
    CONSTRAINT device_credentials_revocation_consistent
        CHECK (
            (status = 'revoked' AND revoked_at IS NOT NULL)
         OR (status = 'active'  AND revoked_at IS NULL)
        )
);

-- Credential lookup on presentation: the hot path (every ingest request hashes the presented key and
-- looks it up here). Standard B-tree; no TimescaleDB. The UNIQUE constraint above already creates a
-- unique index on key_hash, which serves this lookup — declared explicitly here for the reader.
CREATE INDEX IF NOT EXISTS idx_device_credentials_bridge
    ON device_credentials (bridge_id);

-- Operator query: "which credentials are live for this tenant?" Partial index — revoked rows are
-- retained for audit but are never the answer to that question, so they stay out of the index.
CREATE INDEX IF NOT EXISTS idx_device_credentials_active_by_muni
    ON device_credentials (municipality_id)
    WHERE status = 'active';

-- ---------------------------------------------------------------------------------------------
-- Tenant consistency guard (mirrors 0015's guard): the denormalized municipality_id must equal the
-- municipality that actually owns bridge_id. A row where the two disagree would be visible to the
-- WRONG tenant under the RLS predicate below (which keys on the denormalized column), so this is an
-- isolation control, not a tidiness check.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION device_credentials_tenant_guard()
RETURNS TRIGGER AS $$
DECLARE
    owner_muni TEXT;
BEGIN
    SELECT municipality_id INTO owner_muni FROM bridges WHERE id = NEW.bridge_id;
    IF owner_muni IS NULL THEN
        RAISE EXCEPTION
            'device_credentials: bridge % does not exist', NEW.bridge_id;
    END IF;
    IF NEW.municipality_id <> owner_muni THEN
        RAISE EXCEPTION
            'device_credentials: municipality_id % does not own bridge % (owner is %)',
            NEW.municipality_id, NEW.bridge_id, owner_muni;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_device_credentials_tenant_guard
    BEFORE INSERT OR UPDATE ON device_credentials
    FOR EACH ROW EXECUTE FUNCTION device_credentials_tenant_guard();

-- ---------------------------------------------------------------------------------------------
-- DELETE is BLOCKED (discipline 2). Revocation is `UPDATE ... SET status = 'revoked'`. There is no
-- supported path that removes a credential row, because the row is the evidence that a given device
-- was authorised during a given window. Blocking in-engine means an application bug, a stray script,
-- or a well-meaning operator with a psql prompt cannot destroy that evidence.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION device_credentials_block_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'device_credentials is append-only: DELETE is blocked. To retire a device, '
        'UPDATE ... SET status = ''revoked'', revoked_at = now() — the row is retained as '
        'evidence of what was authorised when (Principle VI).';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_device_credentials_block_delete
    BEFORE DELETE ON device_credentials
    FOR EACH ROW EXECUTE FUNCTION device_credentials_block_delete();

-- ---------------------------------------------------------------------------------------------
-- Row-level security (0016 pattern). A credential row is tenant-scoped like everything else: an
-- engineer scoped to municipality A must not enumerate B's devices. FORCE, not just ENABLE, because
-- bridgeguard_service OWNS this table and owners are exempt from policies by default (see 0016's
-- header for the full reasoning).
--
-- The predicate is the same single denormalized equality, keyed on the same GUC:
--     municipality_id = current_setting('app.current_municipality_id', true)
-- Fail-closed: missing_ok = true means an UNSET GUC yields NULL, and `<col> = NULL` is never true, so
-- an unscoped session sees ZERO credentials rather than all of them.
--
-- NOTE on the ingestion path: authenticating a Pi requires looking up a key_hash BEFORE any tenant
-- scope is known — that lookup is the very thing that DETERMINES the scope, so it cannot itself be
-- tenant-scoped. That bootstrap read is therefore performed by a separate, narrowly-privileged path
-- (P301) that may read ONLY (key_hash, bridge_id, municipality_id, status) and can neither write nor
-- read any other table. Everything after resolution runs inside the normal scoped transaction.
-- ---------------------------------------------------------------------------------------------
ALTER TABLE device_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_credentials FORCE  ROW LEVEL SECURITY;

CREATE POLICY device_credentials_select ON device_credentials
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));

CREATE POLICY device_credentials_insert ON device_credentials
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- UPDATE is permitted (revocation, last_used_at) but only within the caller's own tenant, and the
-- WITH CHECK prevents an update from re-attributing a row to a different municipality.
CREATE POLICY device_credentials_update ON device_credentials
    FOR UPDATE TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true))
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));
