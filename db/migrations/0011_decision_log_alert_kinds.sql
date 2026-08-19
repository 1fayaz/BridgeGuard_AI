-- Migration 0011 — decision_log alert-escalation kinds (A204)
-- Alert & Escalation Agent (Agent 005): extend the SHARED decision_kind enum (migration 0004) with
-- the four audit kinds this agent logs. One reconstructable audit story across all five agents
-- (DCA, SA, Risk, Report, Alert) — a human can replay WHY any alert was dispatched, escalated,
-- withheld, or failed, from the one decision_log table (Constitution VI; plan §3b / Open Item 11).
--
--   ALERT_DISPATCHED  a notification was dispatched from a finalized verdict and persisted
--                     (records assessment id+version + channel + approval state)
--   ALERT_ESCALATED   an alert advanced up the escalation ladder — no timely delivery/ack, so the
--                     next contact / on-call was notified (FR-6/FR-8)
--   ALERT_WITHHELD    no dispatch on purpose; the row names the reason (ASSESSMENT_NOT_FOUND, or a
--                     CONSISTENCY_MISMATCH where the alert message contradicts the verdict — FR-9)
--   ALERT_ERROR       an unexpected dispatch failure, captured as a structured status, never a
--                     crash (FR-12)
--
-- We EXTEND the existing enum (never recreate it — that would drop the DCA's, SA's, Risk's, and
-- Report's kinds). Each ADD VALUE is IF NOT EXISTS so re-running the migration is safe.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live enforcement
-- verified when an instance exists; the FakeAlertStore (A801) mirrors the audit append.
--
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction block in PostgreSQL, so this
-- migration must be applied outside an explicit BEGIN/COMMIT (the migration runner handles this).

ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'ALERT_DISPATCHED';
ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'ALERT_ESCALATED';
ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'ALERT_WITHHELD';
ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'ALERT_ERROR';
