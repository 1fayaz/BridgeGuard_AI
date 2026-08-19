-- Migration 0016 — rls_policies (D305 / D306)
-- Database Layer (Spec 002): the migration that switches on multi-tenant ISOLATION. After 0015 wired
-- the ownership chain municipalities -> bridges -> sensors -> readings and denormalized a
-- municipality_id onto every tenant-scoped table, this migration makes Postgres enforce that a
-- session may only see rows of the ONE municipality it is scoped to (spec AC-4: municipality A
-- receives ZERO rows of municipality B, even when the query omits a scope filter).
--
-- Stack: Neon / PostgreSQL, standard row-level security. NO TimescaleDB, no hypertable — isolation
-- is a native Postgres RLS feature, not an extension. [DB-DEP] no Neon instance locally, so this
-- migration is reviewable but not executable here; the live A-can't-see-B check runs in D601 against
-- a seeded two-municipality database. The FakeTenantStore already mirrors the ownership chain the
-- policies key on.
--
-- Built in two parts across two tasks, each independently reviewable:
--   PART A (D305, this section): ENABLE + FORCE ROW LEVEL SECURITY on every tenant-scoped table.
--   PART B (D306): the per-table SELECT + INSERT (WITH CHECK) policies keyed on
--          `municipality_id = current_setting('app.current_municipality_id', true)`, granted to the
--          bridgeguard_service role, fail-closed when the GUC is unset.
--
-- Why FORCE, not just ENABLE (plan §2): by default a table's OWNER — and any role with BYPASSRLS —
-- skips row-level policies entirely. BridgeGuard's single `bridgeguard_service` role OWNS these
-- tables and is also the role the application connects as, so ENABLE alone would leave the app's own
-- connection seeing every tenant's rows. FORCE ROW LEVEL SECURITY removes the owner exemption, so the
-- policies bind the service role too. Enabling on a table with no policy yet is fail-closed by design
-- (a table with RLS on and zero policies returns zero rows) — part B then opens exactly the scoped
-- rows back up.

-- ===========================================================================
-- PART A (D305) — ENABLE + FORCE row-level security on all eleven tenant-scoped tables.
-- Order: tenancy foundation first (municipalities, bridges, sensors), then the eight data tables
-- that carry a denormalized municipality_id (0015). A table missing FORCE would be a silent
-- isolation hole, so every table gets both statements.
-- ===========================================================================

-- Tenancy foundation (0012 / 0013 / 0014).
ALTER TABLE municipalities ENABLE ROW LEVEL SECURITY;
ALTER TABLE municipalities FORCE  ROW LEVEL SECURITY;

ALTER TABLE bridges ENABLE ROW LEVEL SECURITY;
ALTER TABLE bridges FORCE  ROW LEVEL SECURITY;

ALTER TABLE sensors ENABLE ROW LEVEL SECURITY;
ALTER TABLE sensors FORCE  ROW LEVEL SECURITY;

-- Sensor-keyed data tables (0001 / 0002 / 0005 / 0003 / 0004).
ALTER TABLE raw_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_readings FORCE  ROW LEVEL SECURITY;

ALTER TABLE validated_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE validated_readings FORCE  ROW LEVEL SECURITY;

ALTER TABLE analysis_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_results FORCE  ROW LEVEL SECURITY;

ALTER TABLE sensor_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE sensor_status FORCE  ROW LEVEL SECURITY;

ALTER TABLE decision_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_log FORCE  ROW LEVEL SECURITY;

-- Judgment tables (0006 / 0008 / 0010).
ALTER TABLE risk_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_assessments FORCE  ROW LEVEL SECURITY;

ALTER TABLE report_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_artifacts FORCE  ROW LEVEL SECURITY;

ALTER TABLE alert_dispatches ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_dispatches FORCE  ROW LEVEL SECURITY;

-- ===========================================================================
-- PART B (D306) — the per-table policies: open EXACTLY the scoped tenant's rows.
--
-- Two directions per table (spec AC-4):
--   * SELECT (USING)      — a read returns only rows of the current municipality;
--   * INSERT (WITH CHECK) — a write may only create rows for the current municipality (you cannot
--                           attribute a new row to a foreign tenant).
--
-- The predicate is one denormalized single equality everywhere:
--     municipality_id = current_setting('app.current_municipality_id', true)
-- `municipalities` is the exception (no municipality_id column) — it self-predicates on its PK id.
--
-- Fail-closed: current_setting(..., true) passes missing_ok = true, so an UNSET GUC yields NULL
-- rather than erroring, and `<col> = NULL` is never true — an unscoped session sees ZERO rows, never
-- everything. All policies are granted to the single application role bridgeguard_service.
-- ===========================================================================

-- municipalities: self-scope on the PK (the tenant root only ever sees its own row).
CREATE POLICY municipalities_select ON municipalities
    FOR SELECT TO bridgeguard_service
    USING (id = current_setting('app.current_municipality_id', true));
CREATE POLICY municipalities_insert ON municipalities
    FOR INSERT TO bridgeguard_service
    WITH CHECK (id = current_setting('app.current_municipality_id', true));

-- bridges
CREATE POLICY bridges_select ON bridges
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY bridges_insert ON bridges
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- sensors
CREATE POLICY sensors_select ON sensors
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY sensors_insert ON sensors
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- sensor_status
CREATE POLICY sensor_status_select ON sensor_status
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY sensor_status_insert ON sensor_status
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- raw_readings
CREATE POLICY raw_readings_select ON raw_readings
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY raw_readings_insert ON raw_readings
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- validated_readings
CREATE POLICY validated_readings_select ON validated_readings
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY validated_readings_insert ON validated_readings
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- analysis_results
CREATE POLICY analysis_results_select ON analysis_results
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY analysis_results_insert ON analysis_results
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- decision_log
CREATE POLICY decision_log_select ON decision_log
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY decision_log_insert ON decision_log
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- risk_assessments
CREATE POLICY risk_assessments_select ON risk_assessments
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY risk_assessments_insert ON risk_assessments
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- report_artifacts
CREATE POLICY report_artifacts_select ON report_artifacts
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY report_artifacts_insert ON report_artifacts
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));

-- alert_dispatches
CREATE POLICY alert_dispatches_select ON alert_dispatches
    FOR SELECT TO bridgeguard_service
    USING (municipality_id = current_setting('app.current_municipality_id', true));
CREATE POLICY alert_dispatches_insert ON alert_dispatches
    FOR INSERT TO bridgeguard_service
    WITH CHECK (municipality_id = current_setting('app.current_municipality_id', true));
