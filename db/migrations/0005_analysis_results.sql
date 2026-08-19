-- Migration 0005 — analysis_results (D202)
-- Structural Analysis Agent (Agent 002): the CALCULATION layer. One row per eligible
-- (sensor, calculation, block, input_version) — the structured result of running an engineering
-- calculation (RMS / FFT / deflection / threshold) on a block or scalar of validated readings. This
-- table did not previously exist (the 0006/0008 headers reference it as "migration 0005" but no file
-- was ever written — research §1); creating it here closes the provenance chain
-- raw_readings (0001) -> validated_readings (0002) -> analysis_results (0005) ->
-- risk_assessments (0006) -> report_artifacts (0008) / alert_dispatches (0010).
--
-- This agent EMITS numbers, ratios, and pass/fail-vs-limit facts — never a danger verdict (that is
-- the Risk agent's job). Distinct from validated_readings (0002): that is the trustworthy reading;
-- THIS is the calculation computed from it.
--
-- Stack (CLAUDE.md / constitution v2.1.0): Neon / PostgreSQL, standard B-tree indexes only.
-- NO TimescaleDB. The (sensor_id, computed_at) read + the idempotency partial-unique (D203) are
-- served by standard B-tree indexes; there is no hypertable.
--
-- Grain: one row per (sensor_id, calculation, block_id, input_version). See the ratified column
-- manifest specs/database/analysis_results_manifest.md (D201).
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live constraint
-- enforcement is verified when an instance exists. The in-memory FakeAnalysisStore
-- (src/db/analysis_store.py) mirrors these guarantees for the logic tests, exactly as the
-- DCA/Risk/Report/Alert fakes do.
--
-- NOTE (cross-agent, Principle III): source_validated_ids references validated_readings(id) as a
-- SOFT provenance array (BIGINT[]), NOT a hard FK — same deliberate decoupling as
-- validated_readings.source_raw_ids / risk_assessments.source_analysis_ids. Tenancy (sensor_id ->
-- sensors, and a denormalized municipality_id) is NOT added inline here: the sensors table (0014)
-- is created after this migration, so the hard tenant FK is wired uniformly in 0015.

-- The calculation kind. Closed set — MIRRORS agents.structural_analysis.config.calculations.Calculation
-- (v1 active: RMS/FFT/DEFLECTION_LIMIT/THRESHOLD; declared-but-deferred: FATIGUE/MODAL/CRACK_RATE, which
-- a v1 build must never emit — SA FR-10/FR-11). Kept as a closed enum so schema + code cannot drift.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'analysis_calc') THEN
        CREATE TYPE analysis_calc AS ENUM (
            'RMS',
            'FFT',
            'DEFLECTION_LIMIT',
            'THRESHOLD',
            'FATIGUE',
            'MODAL',
            'CRACK_RATE'
        );
    END IF;
END $$;

-- What happened to a (sensor, calc, block) evaluation (SA FR-13). Closed set.
--   RAN      a finite, sane value was produced
--   SKIPPED  deliberately not run / not emitted as a value (carries a reason_code)
--   ERROR    an unexpected per-item failure — structured, never a crash
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'analysis_outcome') THEN
        CREATE TYPE analysis_outcome AS ENUM (
            'RAN',
            'SKIPPED',
            'ERROR'
        );
    END IF;
END $$;

-- The closed skip taxonomy (SA FR-6/FR-9/FR-12/FR-13). A SKIPPED row carries exactly one.
--   NO_CHANGE             FFT within the learned RMS baseline, no trigger (FR-6)
--   NO_CALC               the sensor type has no calculation mapped (FR-12)
--   LIMIT_NOT_CONFIGURED  type mapped to a check but its design limit is unset (FR-9)
--   NO_REFERENCE          a displacement sensor's reference zero is missing/stale (FR-9)
--   DEGENERATE_RESULT     a non-finite/empty computation, validated out — never a RAN NaN (FR-13)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'analysis_skip_reason') THEN
        CREATE TYPE analysis_skip_reason AS ENUM (
            'NO_CHANGE',
            'NO_CALC',
            'LIMIT_NOT_CONFIGURED',
            'NO_REFERENCE',
            'DEGENERATE_RESULT'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS analysis_results (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- What was computed, on what (grain).
    sensor_id     TEXT           NOT NULL,   -- the reporting sensor (tenant FK wired in 0015)
    calculation   analysis_calc  NOT NULL,   -- which calculation
    block_id      TEXT           NOT NULL,   -- the block / scalar reading identity

    -- The outcome (closed vocabulary).
    outcome       analysis_outcome NOT NULL,

    -- Why SKIPPED (NULL unless outcome = SKIPPED).
    reason_code   analysis_skip_reason,

    -- Structured per-item failure text (NULL unless outcome = ERROR); an ERROR carries no value.
    error_detail  TEXT,

    -- Result value(s) — populated on a RAN. A scalar RAN (RMS/threshold/deflection) has `value`;
    -- an FFT RAN has `fft_peaks`. All NULL for SKIPPED/ERROR.
    value         DOUBLE PRECISION,          -- scalar result (RMS severity, threshold/deflection actual)
    limit_value   DOUBLE PRECISION,          -- the configured design limit (threshold/deflection, FR-9)
    ratio         DOUBLE PRECISION,          -- value / limit (FR-9)
    passed        BOOLEAN,                   -- pass/fail-vs-limit; NO danger band (Risk's job)
    fft_peaks     JSONB,                     -- top-N frequencies+amplitudes + rate/window meta (FR-6)

    -- Provenance / reproducibility (FR-13/FR-16/FR-17).
    source_validated_ids BIGINT[] NOT NULL DEFAULT '{}',  -- SOFT: validated_readings.id(s) consulted
    input_version        TEXT     NOT NULL,               -- the input version (idempotency key member)
    config_version       TEXT     NOT NULL,               -- which SA config/constants were in force
    constants_used       JSONB    NOT NULL DEFAULT '{}',  -- the actual constant values used (FR-17)

    -- Result flags (co-exist with any outcome).
    interpolated_input BOOLEAN NOT NULL DEFAULT FALSE,     -- input included INTERPOLATED data (FR-13)
    clock_drift        BOOLEAN NOT NULL DEFAULT FALSE,     -- input carried a clock_drift flag (FR-14)
    rate_mismatch      BOOLEAN NOT NULL DEFAULT FALSE,     -- block rate/length mismatch (FR-2)
    abnormal_quiet     BOOLEAN NOT NULL DEFAULT FALSE,     -- FFT low-side (went quiet) trigger (FR-6)

    -- Correction chain (FR-8): never UPDATE a prior result; INSERT the new one and set the OLD row's
    -- superseded_by. NULL = current; NOT NULL = historical. Self-FK is hard (internal consistency).
    -- The guard/delete triggers + the idempotency partial-unique index are added in 0005's companion
    -- work (D203); this migration establishes the column + self-reference.
    superseded_by BIGINT REFERENCES analysis_results(id),

    -- When this result was computed (audit; distinct from the reading's sensor_time).
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- ------- shape-coherence (mirrors report_artifacts 0008 / risk_assessments 0006) -------

    -- A RAN result must carry a result: a scalar value OR an FFT peak set (not both empty).
    CONSTRAINT ran_has_result
        CHECK (outcome <> 'RAN' OR value IS NOT NULL OR fft_peaks IS NOT NULL),

    -- A RAN scalar value, when present, must be finite — a NaN/Inf is never a RAN (FR-13: it is
    -- SKIPPED/DEGENERATE_RESULT). 'NaN'::float is the only value NOT equal to itself; Inf is caught
    -- by the finite-range check.
    CONSTRAINT ran_value_is_finite
        CHECK (value IS NULL OR (value = value AND value <> 'Infinity'::float8 AND value <> '-Infinity'::float8)),

    -- A SKIPPED result carries exactly one reason_code and no value/peaks/error.
    CONSTRAINT skipped_has_reason
        CHECK (outcome <> 'SKIPPED' OR (reason_code IS NOT NULL
                                        AND value IS NULL AND fft_peaks IS NULL AND error_detail IS NULL)),

    -- A reason_code belongs only to a SKIPPED row.
    CONSTRAINT reason_only_when_skipped
        CHECK (reason_code IS NULL OR outcome = 'SKIPPED'),

    -- An ERROR result carries error_detail and no value/peaks/reason.
    CONSTRAINT error_has_detail_only
        CHECK (outcome <> 'ERROR' OR (error_detail IS NOT NULL
                                      AND value IS NULL AND fft_peaks IS NULL AND reason_code IS NULL)),

    -- error_detail belongs only to an ERROR row.
    CONSTRAINT error_detail_only_when_error
        CHECK (error_detail IS NULL OR outcome = 'ERROR')
);

-- Read the current results for a sensor over time (Risk consumes current RAN results per scope;
-- SA §102 per-sensor chronological window). Standard B-tree; no TimescaleDB. This is the
-- analysis_results member of the (sensor_id, <time>) index family (plan §4/§5, verified in D501).
CREATE INDEX IF NOT EXISTS idx_analysis_sensor_time
    ON analysis_results (sensor_id, computed_at DESC);

-- Idempotency (SA FR-16 / spec-002 FR-10): at most ONE current (non-superseded) result per
-- (sensor_id, calculation, block_id, input_version). A redelivered/duplicate trigger for the same
-- input version is a no-op; a genuine input CORRECTION (a new input_version) supersedes the old row
-- first (FR-8), freeing the slot. Standard Postgres partial unique index over current rows only
-- (standard B-tree, no TimescaleDB). Mirrors uq_risk_current_bridge_cycle (0006) /
-- uq_report_current_assessment_version (0008).
CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_current_sensor_calc_block_version
    ON analysis_results (sensor_id, calculation, block_id, input_version)
    WHERE superseded_by IS NULL;

-- ---------------------------------------------------------------------------
-- Corrections are append + supersede, never in-place edits to an existing result. We allow exactly
-- one UPDATE shape: stamping superseded_by on an older row to link it to its replacement. Any attempt
-- to mutate the outcome, value(s), reason/error, or pinned provenance/identity of an already-written
-- result is blocked. This keeps the old -> new history intact (Constitution VI; SA FR-8; FR-16/FR-17
-- reproducibility).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analysis_results_guard_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.outcome              IS DISTINCT FROM OLD.outcome
    OR NEW.reason_code          IS DISTINCT FROM OLD.reason_code
    OR NEW.error_detail         IS DISTINCT FROM OLD.error_detail
    OR NEW.value                IS DISTINCT FROM OLD.value
    OR NEW.limit_value          IS DISTINCT FROM OLD.limit_value
    OR NEW.ratio                IS DISTINCT FROM OLD.ratio
    OR NEW.passed               IS DISTINCT FROM OLD.passed
    OR NEW.fft_peaks            IS DISTINCT FROM OLD.fft_peaks
    OR NEW.sensor_id            IS DISTINCT FROM OLD.sensor_id
    OR NEW.calculation          IS DISTINCT FROM OLD.calculation
    OR NEW.block_id             IS DISTINCT FROM OLD.block_id
    OR NEW.source_validated_ids IS DISTINCT FROM OLD.source_validated_ids
    OR NEW.input_version        IS DISTINCT FROM OLD.input_version
    OR NEW.config_version       IS DISTINCT FROM OLD.config_version THEN
        RAISE EXCEPTION
            'analysis_results is correct-by-append: mutating the outcome/value/provenance of an existing result is blocked (set superseded_by instead)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_analysis_guard_update ON analysis_results;
CREATE TRIGGER trg_analysis_guard_update
    BEFORE UPDATE ON analysis_results
    FOR EACH ROW EXECUTE FUNCTION analysis_results_guard_update();

-- DELETE is never allowed: a result history a regulator relies on is permanent.
CREATE OR REPLACE FUNCTION analysis_results_block_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'analysis_results history is permanent (Constitution VI): DELETE blocked';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_analysis_block_delete ON analysis_results;
CREATE TRIGGER trg_analysis_block_delete
    BEFORE DELETE ON analysis_results
    FOR EACH ROW EXECUTE FUNCTION analysis_results_block_delete();

REVOKE DELETE, TRUNCATE ON analysis_results FROM PUBLIC;
