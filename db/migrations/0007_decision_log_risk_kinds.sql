-- Migration 0007 — decision_log risk-reasoning kinds (R204)
-- Risk Reasoning Agent (Agent 003): extend the SHARED decision_kind enum (migration 0004) with
-- the three audit kinds this agent logs. One reconstructable audit story across all three agents
-- (DCA, SA, Risk) — a human can replay WHY any verdict was emitted, withheld, or failed closed,
-- from the one decision_log table (Constitution VI; plan §3b recommendation).
--
--   RISK_ASSESSMENT      a scored whole-bridge assessment was emitted (records bridge/cycle +
--                        score + severity + review_status)
--   RISK_WITHHELD        coverage below the floor -> score withheld, routed to human review;
--                        the row names the gap (FR-6)
--   RISK_GUARDRAIL_FAIL  the numeric-provenance guardrail tripped and, after one regenerate,
--                        failed closed to PENDING_HUMAN_REVIEW; the row names the untraceable
--                        number (FR-7, mandate #2)
--
-- We EXTEND the existing enum (never recreate it — that would drop the DCA's nine kinds). Each
-- ADD VALUE is IF NOT EXISTS so re-running the migration is safe.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Supabase instance). Live
-- enforcement verified when an instance exists; the FakeRiskStore (R901) mirrors the audit append.
--
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction block in PostgreSQL, so this
-- migration must be applied outside an explicit BEGIN/COMMIT (the migration runner handles this).

ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'RISK_ASSESSMENT';
ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'RISK_WITHHELD';
ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'RISK_GUARDRAIL_FAIL';
