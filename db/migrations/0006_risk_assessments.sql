-- Migration 0006 — risk_assessments (R203)
-- Risk Reasoning Agent (Agent 003): the JUDGMENT layer. One row per whole-bridge assessment
-- (one per bridge per SA-cycle-complete, FR-3a), carrying the deterministic risk score, the
-- model's plain-language explanation, and everything needed to reproduce and audit the verdict.
--
-- This is the system-of-record half of the dual audit (the other half is the SDK trace, linked
-- by trace_id). Distinct from analysis_results (SA, migration 0005): that table holds the raw
-- numbers/ratios; THIS table holds the danger judgment built from them.
--
-- Constitution I/II/VI:
--   * FR-1 / mandate #1 — a score and its explanation are inseparable: every row carries a
--     non-empty explanation; a scored row carries a severity band.
--   * FR-6/FR-7 — a withheld assessment (NULL score) is a first-class row, not silence: it has
--     NULL severity and is held PENDING_HUMAN_REVIEW.
--   * FR-11 / mandate #3 — a CRITICAL assessment is NEVER FINAL on the agent's say-so alone.
--   * FR-9/FR-10 — reproducible from exactly the pinned inputs (source ids + standard version +
--     weights version + model version); corrections append + supersede, never overwrite.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Supabase instance). Live
-- constraint/trigger enforcement is verified when an instance exists. The in-memory FakeRiskStore
-- (R901) mirrors these guarantees for the logic tests.
--
-- NOTE (cross-agent): source_analysis_ids references SA's analysis_results(id) (migration 0005),
-- which is not yet built. We keep it as a BIGINT[] provenance array (same shape as
-- validated_readings.source_raw_ids) rather than a hard FK, exactly as analysis_results will
-- reference validated_readings — a deliberate, documented decoupling (Principle III).

-- The four severity bands (FR-4). Closed set, ordered SAFE -> CRITICAL. Mirrors
-- agents.risk_reasoning.statuses.Severity.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'severity') THEN
        CREATE TYPE severity AS ENUM (
            'SAFE',
            'WATCH',
            'WARNING',
            'CRITICAL'
        );
    END IF;
END $$;

-- Finality flag (FR-11). Mirrors agents.risk_reasoning.statuses.ReviewStatus.
--   FINAL                 may be consumed as-is downstream
--   PENDING_HUMAN_REVIEW  must be human-reviewed before any downstream agent treats it as final
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_status') THEN
        CREATE TYPE review_status AS ENUM (
            'FINAL',
            'PENDING_HUMAN_REVIEW'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS risk_assessments (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Scope (FR-3a): one assessment = the whole bridge at one SA cycle.
    bridge_id     TEXT        NOT NULL,
    cycle_id      TEXT        NOT NULL,

    -- When this assessment was computed (audit clock).
    assessed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- The verdict. score + severity are NULL together when WITHHELD (FR-6/FR-7); the
    -- CHECKs below keep the scored/withheld shapes coherent.
    risk_score    INTEGER,                 -- 0-100; NULL when withheld
    severity      severity,                -- band; NULL when withheld
    recommendation TEXT       NOT NULL,

    -- The WHY (FR-1) — a first-class safety output, logged VERBATIM, never empty, present
    -- even on a withheld assessment (it states what was missing).
    explanation   TEXT        NOT NULL,

    -- Structured backing for the narrative (FR-2 factors): per-factor source id, ratio,
    -- weight, contribution, direction. JSONB because the factor list is variable-length.
    contributing_factors JSONB NOT NULL DEFAULT '[]',

    -- Annotation only (FR-6a): does NOT move the score; gates the degraded/withhold decision.
    confidence        DOUBLE PRECISION,
    data_completeness DOUBLE PRECISION,

    -- Finality (FR-11).
    review_status review_status NOT NULL,

    -- Provenance / reproducibility (FR-9/FR-10): an assessment is re-derivable from exactly
    -- these even after a standard is revised or an SA result is superseded.
    source_analysis_ids   BIGINT[] NOT NULL DEFAULT '{}',  -- analysis_results.id(s) consulted
    baseline_ref          TEXT,                            -- which historical baseline (nullable)
    standard_code         TEXT,                            -- e.g. 'IRC:6' (NULL if unavailable)
    standard_version      TEXT,                            -- pinned at decision time
    score_weights_version TEXT     NOT NULL,               -- which ScoreConfig weights were used
    model_id              TEXT     NOT NULL,               -- the frontier model used
    model_version         TEXT     NOT NULL,
    trace_id              TEXT     NOT NULL,               -- links to the SDK trace (dual audit)

    -- Correction chain (re-assessment): never UPDATE a prior verdict; INSERT the new one and
    -- set the OLD row's superseded_by. NULL superseded_by = current; NOT NULL = historical.
    superseded_by BIGINT      REFERENCES risk_assessments(id),

    -- FR-1: the WHY is part of every output. An empty explanation is an invalid assessment.
    CONSTRAINT explanation_present
        CHECK (length(btrim(explanation)) > 0),

    -- FR-1: a numeric score must carry its band; FR-6/FR-7: a withheld (NULL) score carries
    -- no band. The two move together.
    CONSTRAINT score_has_band
        CHECK ((risk_score IS NULL) = (severity IS NULL)),

    -- FR-6/FR-7: a withheld assessment is held for a human (never silently FINAL).
    CONSTRAINT withheld_is_pending_review
        CHECK (risk_score IS NOT NULL OR review_status = 'PENDING_HUMAN_REVIEW'),

    -- FR-11 / mandate #3: a CRITICAL assessment is never FINAL on the agent's say-so alone.
    CONSTRAINT critical_not_final
        CHECK (severity IS DISTINCT FROM 'CRITICAL' OR review_status = 'PENDING_HUMAN_REVIEW'),

    -- A score, when present, is on the 0-100 scale.
    CONSTRAINT score_in_range
        CHECK (risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100))
);

-- Look up the current assessment for a bridge over time (dashboard / trend).
CREATE INDEX IF NOT EXISTS idx_risk_bridge_time
    ON risk_assessments (bridge_id, assessed_at DESC);

-- Idempotency (FR-3a redelivery): at most ONE current (non-superseded) assessment per
-- (bridge_id, cycle_id). A redelivered trigger is a no-op; a re-assessment supersedes the old
-- row first, freeing the slot. Partial unique index over current rows only.
CREATE UNIQUE INDEX IF NOT EXISTS uq_risk_current_bridge_cycle
    ON risk_assessments (bridge_id, cycle_id)
    WHERE superseded_by IS NULL;

-- Find assessments awaiting human review (the PENDING_HUMAN_REVIEW queue, FR-11).
CREATE INDEX IF NOT EXISTS idx_risk_pending_review
    ON risk_assessments (review_status)
    WHERE review_status = 'PENDING_HUMAN_REVIEW';

-- ---------------------------------------------------------------------------
-- Corrections are append + supersede, never in-place edits to the VERDICT of an existing
-- assessment. We allow exactly one UPDATE shape: stamping superseded_by on an older row to link
-- it to its replacement. Any attempt to mutate the score, severity, explanation, review_status,
-- or pinned provenance of an already-written assessment is blocked. This keeps the old -> new
-- history intact (Constitution VI; FR-10 reproducibility).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION risk_assessments_guard_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.risk_score            IS DISTINCT FROM OLD.risk_score
    OR NEW.severity              IS DISTINCT FROM OLD.severity
    OR NEW.explanation           IS DISTINCT FROM OLD.explanation
    OR NEW.recommendation        IS DISTINCT FROM OLD.recommendation
    OR NEW.review_status         IS DISTINCT FROM OLD.review_status
    OR NEW.bridge_id             IS DISTINCT FROM OLD.bridge_id
    OR NEW.cycle_id              IS DISTINCT FROM OLD.cycle_id
    OR NEW.source_analysis_ids   IS DISTINCT FROM OLD.source_analysis_ids
    OR NEW.standard_version      IS DISTINCT FROM OLD.standard_version
    OR NEW.score_weights_version IS DISTINCT FROM OLD.score_weights_version
    OR NEW.model_version         IS DISTINCT FROM OLD.model_version
    OR NEW.trace_id              IS DISTINCT FROM OLD.trace_id THEN
        RAISE EXCEPTION
            'risk_assessments is correct-by-append: mutating the verdict/provenance of an existing assessment is blocked (set superseded_by instead)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_risk_guard_update ON risk_assessments;
CREATE TRIGGER trg_risk_guard_update
    BEFORE UPDATE ON risk_assessments
    FOR EACH ROW EXECUTE FUNCTION risk_assessments_guard_update();

-- DELETE is never allowed: an assessment history a regulator relies on is permanent.
CREATE OR REPLACE FUNCTION risk_assessments_block_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'risk_assessments history is permanent (Constitution VI): DELETE blocked';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_risk_block_delete ON risk_assessments;
CREATE TRIGGER trg_risk_block_delete
    BEFORE DELETE ON risk_assessments
    FOR EACH ROW EXECUTE FUNCTION risk_assessments_block_delete();

REVOKE DELETE, TRUNCATE ON risk_assessments FROM PUBLIC;
