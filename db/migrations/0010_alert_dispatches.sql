-- Migration 0010 — alert_dispatches (A203)
-- Alert & Escalation Agent (Agent 005): the DISPATCH layer — the single real-world-action
-- chokepoint. One row per dispatch attempt: the system-of-record entry for notifying a human of a
-- finalized risk verdict (risk_assessments 0006). This agent NOTIFIES and ESCALATES, it does not
-- re-judge: the score/severity/recommendation/explanation are copied from the verdict, never
-- recomputed. This table records WHAT was dispatched, on WHICH channel to WHOM, under WHICH
-- approval, and how far the escalation ladder got — so an alert is reproducible and auditable long
-- after its verdict is superseded.
--
-- Distinct from risk_assessments (0006): that table holds the danger JUDGMENT; THIS table holds the
-- NOTIFICATION built from it. Distinct from report_artifacts (0008): that renders a document; this
-- dispatches an alert and gates the physical action. No model is involved in producing these rows.
--
-- Constitution I/II/VI:
--   * FR-5  — this is the human-approval chokepoint: a NEEDS_APPROVAL dispatch carries an
--     approval_state (the sign-off is audited: who approved, when). An un-gated (AUTO_FIRE /
--     DASHBOARD_ONLY) dispatch carries no approval_state.
--   * FR-6/FR-7 — distinct delivery states (SENT != DELIVERED != ACKNOWLEDGED); the escalation
--     ladder closes on DELIVERED (SAFE/WATCH) or ACKNOWLEDGED (WARNING/CRITICAL).
--   * FR-10 — idempotent: at most one current dispatch per (assessment_id, assessment_version).
--   * FR-11/FR-13 — reproducible + end-to-end traceable from exactly the pinned verdict version and
--     the upstream trace_id; corrections append + supersede, never overwrite.
--
-- [DB-DEP] Written and reviewable now; not executable locally (no Neon instance). Live
-- constraint/trigger enforcement is verified when an instance exists. The in-memory FakeAlertStore
-- (A801) mirrors these guarantees for the logic tests.
--
-- Constitution v2.1.0: Neon/Postgres, standard B-tree indexes only (no time-series extension). A
-- partial unique index over current rows covers the idempotency pattern.
--
-- NOTE (cross-agent): assessment_id references risk_assessments(id) (migration 0006). We keep it as
-- a plain BIGINT + version rather than a hard FK — a deliberate, documented decoupling (Principle
-- III), same shape as report_artifacts (0008).

-- The resolved dispatch tier (FR-2/FR-3). Closed set. Mirrors
-- agents.alert_escalation.statuses.DispatchDecision.
--   AUTO_FIRE       dispatched without human approval (SAFE/WATCH, internal, FINAL)
--   NEEDS_APPROVAL  blocked until a human approves (WARNING/CRITICAL, authority, or pending verdict)
--   DASHBOARD_ONLY  no outbound push (SAFE — dashboard/timeline only)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dispatch_decision') THEN
        CREATE TYPE dispatch_decision AS ENUM (
            'AUTO_FIRE',
            'NEEDS_APPROVAL',
            'DASHBOARD_ONLY'
        );
    END IF;
END $$;

-- Where a single dispatch is on the wire (FR-7). Closed set. Mirrors
-- agents.alert_escalation.statuses.DeliveryState. SENT (provider accepted) is NOT DELIVERED
-- (receipt confirmed) is NOT ACKNOWLEDGED (a human confirmed).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'delivery_state') THEN
        CREATE TYPE delivery_state AS ENUM (
            'QUEUED',
            'SENT',
            'DELIVERED',
            'FAILED',
            'ACKNOWLEDGED'
        );
    END IF;
END $$;

-- Where the escalation ladder is for an alert (FR-6). Closed set. Mirrors
-- agents.alert_escalation.statuses.EscalationState.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'escalation_state') THEN
        CREATE TYPE escalation_state AS ENUM (
            'OPEN',
            'ESCALATED',
            'CLOSED'
        );
    END IF;
END $$;

-- The human sign-off on a NEEDS_APPROVAL dispatch (FR-5). Closed set. Mirrors
-- agents.alert_escalation.statuses.ApprovalState.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'approval_state') THEN
        CREATE TYPE approval_state AS ENUM (
            'AWAITING_APPROVAL',
            'APPROVED',
            'REJECTED'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS alert_dispatches (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Scope (for lookup/trend): the bridge + SA cycle the alerted verdict belongs to.
    bridge_id     TEXT        NOT NULL,
    cycle_id      TEXT        NOT NULL,

    -- WHICH finalized verdict this alert acted on (identity + version, FR-11). The version pins the
    -- exact verdict dispatched so the alert is reproducible even after the verdict is superseded.
    assessment_id      BIGINT   NOT NULL,
    assessment_version INTEGER  NOT NULL,

    -- The resolved dispatch tier (FR-2/FR-3).
    dispatch_decision  dispatch_decision NOT NULL,

    -- The dispatch itself. NULL on a DASHBOARD_ONLY (no push) or an awaiting-approval hold.
    channel             TEXT,
    recipient           TEXT,
    provider_message_id TEXT,

    -- Delivery + escalation state (FR-6/FR-7). close_reason records WHICH condition closed it
    -- (DELIVERED for SAFE/WATCH, ACKNOWLEDGED for WARNING/CRITICAL).
    delivery_state      delivery_state,
    escalation_state    escalation_state,
    close_reason        delivery_state,

    -- The human sign-off audit (FR-5). NULL on an un-gated (AUTO_FIRE / DASHBOARD_ONLY) dispatch.
    approval_state      approval_state,
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,

    -- End-to-end provenance (FR-11/FR-13): links this alert to the upstream verdict's SDK trace.
    trace_id      TEXT        NOT NULL,

    -- When this dispatch was attempted (audit clock).
    attempted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Correction chain (re-dispatch): never UPDATE a prior dispatch's identity; INSERT the new one
    -- and set the OLD row's superseded_by. NULL superseded_by = current; NOT NULL = historical.
    superseded_by BIGINT      REFERENCES alert_dispatches(id),

    -- FR-5: a NEEDS_APPROVAL dispatch must carry an approval_state (the sign-off is audited).
    CONSTRAINT gated_has_approval_state
        CHECK (dispatch_decision <> 'NEEDS_APPROVAL' OR approval_state IS NOT NULL),

    -- FR-5: an un-gated dispatch (AUTO_FIRE / DASHBOARD_ONLY) needs no sign-off — approval_state
    -- must be NULL so a spurious approval cannot be recorded against an un-gated action.
    CONSTRAINT ungated_has_no_approval_state
        CHECK (dispatch_decision = 'NEEDS_APPROVAL' OR approval_state IS NULL),

    -- An approver is recorded only alongside an approval_state.
    CONSTRAINT approver_only_when_gated
        CHECK (approved_by IS NULL OR approval_state IS NOT NULL),

    -- A DASHBOARD_ONLY dispatch pushes nothing: no channel, no delivery state.
    CONSTRAINT dashboard_only_has_no_push
        CHECK (dispatch_decision <> 'DASHBOARD_ONLY' OR (channel IS NULL AND delivery_state IS NULL))
);

-- Look up the current dispatch for a bridge over time (dashboard / alert timeline).
CREATE INDEX IF NOT EXISTS idx_alert_bridge_time
    ON alert_dispatches (bridge_id, attempted_at DESC);

-- Find alerts still open / escalating (the escalation queue, FR-6).
CREATE INDEX IF NOT EXISTS idx_alert_open_escalation
    ON alert_dispatches (escalation_state)
    WHERE escalation_state IN ('OPEN', 'ESCALATED');

-- Idempotency (FR-10 redelivery): at most ONE current (non-superseded) dispatch per
-- (assessment_id, assessment_version). A redelivered trigger for an already-handled verdict is a
-- no-op; a re-dispatch supersedes the old row first, freeing the slot. Standard partial unique
-- index over current rows only (standard B-tree, no time-series extension).
CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_current_assessment_version
    ON alert_dispatches (assessment_id, assessment_version)
    WHERE superseded_by IS NULL;

-- ---------------------------------------------------------------------------
-- Corrections are append + supersede, never in-place edits to an existing dispatch's IDENTITY. The
-- delivery/escalation/approval state machine advances on the current row (a dispatch legitimately
-- moves SENT -> DELIVERED -> ACKNOWLEDGED and OPEN -> ESCALATED -> CLOSED as reality unfolds), but
-- the pinned verdict identity, trace, and decision of a written dispatch may never be rewritten.
-- This keeps the old -> new history intact (Constitution VI; FR-11/FR-13 reproducibility).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION alert_dispatches_guard_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.bridge_id           IS DISTINCT FROM OLD.bridge_id
    OR NEW.cycle_id            IS DISTINCT FROM OLD.cycle_id
    OR NEW.assessment_id       IS DISTINCT FROM OLD.assessment_id
    OR NEW.assessment_version  IS DISTINCT FROM OLD.assessment_version
    OR NEW.dispatch_decision   IS DISTINCT FROM OLD.dispatch_decision
    OR NEW.trace_id            IS DISTINCT FROM OLD.trace_id THEN
        RAISE EXCEPTION
            'alert_dispatches is correct-by-append: mutating the verdict identity/decision/trace of an existing dispatch is blocked (set superseded_by instead)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_alert_guard_update ON alert_dispatches;
CREATE TRIGGER trg_alert_guard_update
    BEFORE UPDATE ON alert_dispatches
    FOR EACH ROW EXECUTE FUNCTION alert_dispatches_guard_update();

-- DELETE is never allowed: an alert-dispatch history a regulator relies on is permanent.
CREATE OR REPLACE FUNCTION alert_dispatches_block_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'alert_dispatches history is permanent (Constitution VI): DELETE blocked';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_alert_block_delete ON alert_dispatches;
CREATE TRIGGER trg_alert_block_delete
    BEFORE DELETE ON alert_dispatches
    FOR EACH ROW EXECUTE FUNCTION alert_dispatches_block_delete();

REVOKE DELETE, TRUNCATE ON alert_dispatches FROM PUBLIC;
