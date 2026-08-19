-- Migration 0008 — report_artifacts (G203)
-- Report Generation Agent (Agent 004): the ASSEMBLY layer. One row per report render — the
-- system-of-record entry for a professional, government-ready document assembled from a finalized
-- risk assessment. This agent ASSEMBLES, it does not re-decide: every number and sentence in the
-- report is copied from an upstream row (risk_assessments 0006 -> analysis_results 0005 ->
-- validated_readings 0002), never recomputed. This table records WHAT was rendered, from WHICH
-- pinned assessment version, and WHERE the artifact lives — so a report is reproducible and
-- auditable long after its inputs are superseded.
--
-- Distinct from risk_assessments (0006): that table holds the danger JUDGMENT; THIS table holds
-- the rendered DOCUMENT built from it. No model is involved in producing these rows.
--
-- Constitution I/II/VI:
--   * FR-9  — append-only artifacts: a re-render appends a new row and supersedes the old; a
--     rendered document is never overwritten in place.
--   * FR-5  — a value that does not trace to a source is never published: the WITHHELD outcome
--     (PROVENANCE_MISMATCH) is a first-class row with NULL artifact_ref and a reason.
--   * FR-11 — reproducible from exactly the pinned inputs (assessment id+version + source ids +
--     standard version + template version).
--   * FR-13 — this table records rendering only; publication/dispatch is a downstream gated
--     (needs_approval) action owned by a separate Publish/Alert agent, not modelled here.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live
-- constraint/trigger enforcement is verified when an instance exists. The in-memory
-- FakeReportStore (G801) mirrors these guarantees for the logic tests.
--
-- Constitution v2.1.0: Neon/Postgres, standard B-tree indexes only (no time-series extension). A
-- partial unique index over current rows covers the idempotency pattern.
--
-- NOTE (cross-agent): assessment_id references risk_assessments(id) (migration 0006);
-- source_analysis_ids references analysis_results(id) (migration 0005). We keep source_analysis_ids
-- as a BIGINT[] provenance array (same shape as risk_assessments.source_analysis_ids) rather than a
-- hard FK — a deliberate, documented decoupling (Principle III).

-- What happened to a render (FR-12). Closed set. Mirrors
-- agents.report_generation.report_statuses.ReportOutcome.
--   RENDERED  a document was produced (possibly carrying marks)
--   WITHHELD  no document produced, on purpose (carries a withheld reason)
--   ERROR     an unexpected failure — structured, never a crash
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_outcome') THEN
        CREATE TYPE report_outcome AS ENUM (
            'RENDERED',
            'WITHHELD',
            'ERROR'
        );
    END IF;
END $$;

-- Sign-off marks a RENDERED document may carry (zero or more; empty ⇒ clean FINAL). Mirrors
-- agents.report_generation.report_statuses.DocumentMark.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_mark') THEN
        CREATE TYPE document_mark AS ENUM (
            'NOT_FINAL',
            'SCORE_WITHHELD',
            'HISTORICAL',
            'SECTION_UNAVAILABLE'
        );
    END IF;
END $$;

-- The two (and only two) cases where producing NO document beats an untraceable one. Mirrors
-- agents.report_generation.report_statuses.WithheldReason.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_withheld_reason') THEN
        CREATE TYPE report_withheld_reason AS ENUM (
            'ASSESSMENT_NOT_FOUND',
            'PROVENANCE_MISMATCH'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS report_artifacts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Scope (for lookup/trend): the bridge + SA cycle the rendered assessment belongs to.
    bridge_id     TEXT        NOT NULL,
    cycle_id      TEXT        NOT NULL,

    -- WHICH finalized assessment this report renders (identity + version, FR-4/FR-11). The
    -- version pins the exact verdict rendered so the document is reproducible even after the
    -- assessment is superseded.
    assessment_id      BIGINT   NOT NULL,
    assessment_version INTEGER  NOT NULL,

    -- When this report was rendered (audit clock).
    rendered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- What happened (FR-12). The CHECKs below keep the rendered/withheld/error shapes coherent.
    outcome         report_outcome NOT NULL,

    -- Sign-off marks on a RENDERED document (FR-6/7/8). Empty array ⇒ a clean FINAL report.
    marks           document_mark[] NOT NULL DEFAULT '{}',

    -- Why no document was produced (FR-5). NULL unless outcome = WITHHELD.
    withheld_reason report_withheld_reason,

    -- The produced artifact (a ref/URL to the stored PDF, never the bytes inline). NULL unless
    -- outcome = RENDERED.
    artifact_ref    TEXT,

    -- Provenance / reproducibility (FR-9/FR-11): the report is re-derivable from exactly these
    -- even after an input row is superseded.
    source_analysis_ids BIGINT[] NOT NULL DEFAULT '{}',  -- analysis_results.id(s) rendered
    standard_code       TEXT,                            -- e.g. 'IRC:6' (NULL if unavailable)
    standard_version    TEXT,                            -- pinned at render time
    template_version    TEXT     NOT NULL,               -- which ReportConfig template was used

    -- Correction chain (re-render): never UPDATE a prior artifact; INSERT the new one and set the
    -- OLD row's superseded_by. NULL superseded_by = current; NOT NULL = historical.
    superseded_by BIGINT      REFERENCES report_artifacts(id),

    -- FR-9: a RENDERED row must carry an artifact_ref (a produced document has a location).
    CONSTRAINT rendered_has_artifact
        CHECK (outcome <> 'RENDERED' OR artifact_ref IS NOT NULL),

    -- FR-5: a WITHHELD row must carry exactly one reason and NO artifact (no document produced).
    CONSTRAINT withheld_has_reason
        CHECK (outcome <> 'WITHHELD' OR (withheld_reason IS NOT NULL AND artifact_ref IS NULL)),

    -- A withheld_reason belongs ONLY to a WITHHELD row (RENDERED/ERROR carry none).
    CONSTRAINT reason_only_when_withheld
        CHECK (withheld_reason IS NULL OR outcome = 'WITHHELD'),

    -- An ERROR row is a structured failure: no document, no reason.
    CONSTRAINT error_has_neither
        CHECK (outcome <> 'ERROR' OR (artifact_ref IS NULL AND withheld_reason IS NULL)),

    -- No document ⇒ no document marks (marks belong only to a RENDERED row).
    CONSTRAINT marks_only_when_rendered
        CHECK (outcome = 'RENDERED' OR cardinality(marks) = 0)
);

-- Look up the current report for a bridge over time (dashboard / trend).
CREATE INDEX IF NOT EXISTS idx_report_bridge_time
    ON report_artifacts (bridge_id, rendered_at DESC);

-- Idempotency (FR-10 redelivery): at most ONE current (non-superseded) report per
-- (assessment_id, assessment_version). A redelivered trigger for an already-rendered version is a
-- no-op; a re-render supersedes the old row first, freeing the slot. Standard partial unique
-- index over current rows only (standard B-tree, no time-series extension).
CREATE UNIQUE INDEX IF NOT EXISTS uq_report_current_assessment_version
    ON report_artifacts (assessment_id, assessment_version)
    WHERE superseded_by IS NULL;

-- ---------------------------------------------------------------------------
-- Corrections are append + supersede, never in-place edits to an existing artifact. We allow
-- exactly one UPDATE shape: stamping superseded_by on an older row to link it to its replacement.
-- Any attempt to mutate the outcome, marks, artifact_ref, or pinned provenance of an
-- already-written report is blocked. This keeps the old -> new history intact (Constitution VI;
-- FR-9/FR-11 reproducibility).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION report_artifacts_guard_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.outcome             IS DISTINCT FROM OLD.outcome
    OR NEW.marks               IS DISTINCT FROM OLD.marks
    OR NEW.withheld_reason     IS DISTINCT FROM OLD.withheld_reason
    OR NEW.artifact_ref        IS DISTINCT FROM OLD.artifact_ref
    OR NEW.bridge_id           IS DISTINCT FROM OLD.bridge_id
    OR NEW.cycle_id            IS DISTINCT FROM OLD.cycle_id
    OR NEW.assessment_id       IS DISTINCT FROM OLD.assessment_id
    OR NEW.assessment_version  IS DISTINCT FROM OLD.assessment_version
    OR NEW.source_analysis_ids IS DISTINCT FROM OLD.source_analysis_ids
    OR NEW.standard_version    IS DISTINCT FROM OLD.standard_version
    OR NEW.template_version    IS DISTINCT FROM OLD.template_version THEN
        RAISE EXCEPTION
            'report_artifacts is correct-by-append: mutating the outcome/artifact/provenance of an existing report is blocked (set superseded_by instead)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_report_guard_update ON report_artifacts;
CREATE TRIGGER trg_report_guard_update
    BEFORE UPDATE ON report_artifacts
    FOR EACH ROW EXECUTE FUNCTION report_artifacts_guard_update();

-- DELETE is never allowed: a report history a regulator relies on is permanent.
CREATE OR REPLACE FUNCTION report_artifacts_block_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'report_artifacts history is permanent (Constitution VI): DELETE blocked';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_report_block_delete ON report_artifacts;
CREATE TRIGGER trg_report_block_delete
    BEFORE DELETE ON report_artifacts
    FOR EACH ROW EXECUTE FUNCTION report_artifacts_block_delete();

REVOKE DELETE, TRUNCATE ON report_artifacts FROM PUBLIC;
