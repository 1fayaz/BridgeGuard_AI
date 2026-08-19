-- Migration 0018 — device_credentials key immutability (P306)
--
-- API Layer (specs/api): 0017 created the table and blocked DELETE. This migration closes the
-- remaining hole in the same discipline: 0017 permits UPDATE (for revocation and `last_used_at`),
-- and nothing stops that UPDATE from rewriting `key_hash`.
--
-- Slot: 0018 is the next free number — verified 2026-08-03 that 0001-0017 exist with no gaps and
-- nothing was appended after 0017.
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB. This migration adds no index and no extension — only a trigger.
--
-- ---------------------------------------------------------------------------------------------
-- WHY AN IN-PLACE KEY OVERWRITE IS WORSE THAN IT LOOKS
--
-- Rotation done wrong is `UPDATE device_credentials SET key_hash = <new> WHERE credential_id = N`.
-- One statement, no error, the Pi works afterwards. What it destroys is the answer to the only
-- question a regulator asks about a credential: *was the device that sent this reading authorised
-- at the time?* After the overwrite there is one row claiming it always held the new key. Every
-- reading the old key authorised now traces to a credential that did not exist when those readings
-- arrived. The readings are intact; the audit trail is wrong. Nothing appears broken, which is
-- precisely why this must be blocked in-engine rather than left to code review.
--
-- Rotation done right (plan §2a) is two statements: INSERT a new active row for the device, then
-- later UPDATE the old row's status to 'revoked'. Two keys briefly coexist so a Pi can be re-flashed
-- without a data gap, and both rows survive as evidence of their own window.
--
-- WHAT THIS GUARD BLOCKS, AND WHAT IT DELIBERATELY DOES NOT
--
-- Blocked (identity — the row IS this credential, for this device, in this tenant):
--   key_hash, salt-equivalent material, credential_id, bridge_id, municipality_id, created_at.
--   Re-pointing a live credential at another bridge or another municipality is not a rotation; it is
--   a tenancy hole, since the denormalized municipality_id is what the RLS predicate keys on.
--
-- NOT blocked (lifecycle — the two legitimate updates 0017 names):
--   status + revoked_at (revocation), and last_used_at (operational visibility).
--   Freezing the whole row would break revocation, which is the mechanism that replaces DELETE.
--
-- This is the `<table>_guard_update` pattern the correct-by-supersede SOR tables use (0002, 0005,
-- 0006, 0008), applied to an API-layer config table for the same auditability reason (Principle VI).
--
-- [DB-DEP] Written and reviewable now; NOT executable locally (no Neon instance). Live trigger
-- enforcement is verified when an instance exists. The in-memory FakeCredentialStore
-- (src/db/credential_store.py) mirrors this by holding key material on a frozen
-- `CredentialIdentity`, so an in-place assignment raises there too.
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION device_credentials_guard_update()
RETURNS TRIGGER AS $$
BEGIN
    -- Key material. The whole point of this migration.
    IF NEW.key_hash IS DISTINCT FROM OLD.key_hash THEN
        RAISE EXCEPTION
            'device_credentials.key_hash is immutable: a key is rotated by INSERTing a new '
            'active row for the device and then revoking the old one, never by overwriting '
            'the hash in place. An overwrite would make every reading the old key authorised '
            'trace to a credential that did not exist at the time (P306, plan 2a).';
    END IF;

    -- Credential identity. A row must not become a different credential.
    IF NEW.credential_id IS DISTINCT FROM OLD.credential_id THEN
        RAISE EXCEPTION
            'device_credentials.credential_id is immutable: operators revoke and rotate BY '
            'this id, so it must mean the same thing forever.';
    END IF;

    -- Device and tenant binding. Re-pointing a live credential is an isolation failure, not
    -- a rotation: municipality_id is the column the 0016 RLS predicate keys on.
    IF NEW.bridge_id IS DISTINCT FROM OLD.bridge_id THEN
        RAISE EXCEPTION
            'device_credentials.bridge_id is immutable: a credential pins exactly one bridge '
            '(0017 discipline 3). Re-provision the device with a new credential instead.';
    END IF;

    IF NEW.municipality_id IS DISTINCT FROM OLD.municipality_id THEN
        RAISE EXCEPTION
            'device_credentials.municipality_id is immutable: changing it would move a live '
            'credential into another tenant''s RLS visibility.';
    END IF;

    -- Issuance audit.
    IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION
            'device_credentials.created_at is immutable: it is the start of the window this '
            'credential was valid for.';
    END IF;

    -- Revocation is one-way. Un-revoking would make a retired Pi live again without any
    -- record that it had been retired.
    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION
            'device_credentials: revocation is final. Re-provision the device with a new '
            'credential (INSERT); do not reactivate a revoked row.';
    END IF;

    -- Everything still permitted, stated positively for the reader: status (active ->
    -- revoked), revoked_at, last_used_at, device_label.
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_device_credentials_guard_update
    BEFORE UPDATE ON device_credentials
    FOR EACH ROW EXECUTE FUNCTION device_credentials_guard_update();
