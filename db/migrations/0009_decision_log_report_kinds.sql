-- Migration 0009 — decision_log report-generation kinds (G204)
-- Report Generation Agent (Agent 004): extend the SHARED decision_kind enum (migration 0004) with
-- the three audit kinds this agent logs. One reconstructable audit story across all four agents
-- (DCA, SA, Risk, Report) — a human can replay WHY any report was rendered, withheld, or failed,
-- from the one decision_log table (Constitution VI; plan §5).
--
--   REPORT_RENDERED   a document was assembled from a finalized assessment and persisted
--                     (records assessment id+version + the sign-off marks the document carries)
--   REPORT_WITHHELD   no document produced on purpose; the row names the reason
--                     (ASSESSMENT_NOT_FOUND, or a PROVENANCE_MISMATCH where a printed value did
--                     not trace to a source — FR-5)
--   REPORT_ERROR      an unexpected render failure, captured as a structured status, never a
--                     crash (FR-12)
--
-- We EXTEND the existing enum (never recreate it — that would drop the DCA's, SA's, and Risk's
-- kinds). Each ADD VALUE is IF NOT EXISTS so re-running the migration is safe.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live enforcement
-- verified when an instance exists; the FakeReportStore (G801) mirrors the audit append.
--
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction block in PostgreSQL, so this
-- migration must be applied outside an explicit BEGIN/COMMIT (the migration runner handles this).

ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'REPORT_RENDERED';
ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'REPORT_WITHHELD';
ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'REPORT_ERROR';
